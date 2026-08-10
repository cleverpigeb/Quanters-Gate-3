# 根据目标权重、账户状态和显式交易约束生成可审计订单。

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quanters_gate.data.universe import normalize_symbol_values
from quanters_gate.validation import (
    normalize_boolean_values,
    require_columns,
    require_non_negative_finite,
    require_positive,
    require_unique_rows,
)

ORDER_COLUMNS = [
    "account",
    "date",
    "signal_date",
    "symbol",
    "side",
    "reference_price",
    "estimated_price",
    "target_weight",
    "current_shares",
    "requested_shares",
    "filled_shares",
    "gross_value",
    "commission",
    "stamp_duty",
    "transaction_cost",
    "status",
    "reject_reason",
]


@dataclass(frozen=True)
class TradingCostModel:
    commission_rate: float = 0.0
    minimum_commission: float = 0.0
    stamp_duty_rate: float = 0.0
    slippage_rate: float = 0.0

    def __post_init__(self) -> None:
        for value, label in (
            (self.commission_rate, "佣金率"),
            (self.minimum_commission, "最低佣金"),
            (self.stamp_duty_rate, "印花税率"),
            (self.slippage_rate, "滑点率"),
        ):
            require_non_negative_finite(value, label)
        if self.commission_rate > 1 or self.stamp_duty_rate > 1 or self.slippage_rate > 1:
            raise ValueError("佣金率、印花税率和滑点率不能大于 1。")

    def execution_price(self, reference_price: float, side: str) -> float:
        direction = 1 if side == "buy" else -1
        return reference_price * (1 + direction * self.slippage_rate)

    def costs(self, gross_value: float, side: str) -> tuple[float, float]:
        if gross_value <= 0:
            return 0.0, 0.0
        commission = max(gross_value * self.commission_rate, self.minimum_commission)
        stamp_duty = gross_value * self.stamp_duty_rate if side == "sell" else 0.0
        return commission, stamp_duty


@dataclass(frozen=True)
class OrderGenerationResult:
    orders: pd.DataFrame
    resulting_shares: dict[str, float]
    resulting_cash: float
    gross_traded_value: float
    transaction_cost: float
    blocked_buy_count: int
    blocked_sell_count: int


def _normalize_quotes(quotes: pd.DataFrame) -> pd.DataFrame:
    require_columns(quotes, ("symbol", "price", "is_tradable"), "交易行情")
    result = quotes.copy()
    result["symbol"] = normalize_symbol_values(result["symbol"], "交易行情")
    require_unique_rows(result, ("symbol",), "交易行情")
    result["price"] = pd.to_numeric(result["price"], errors="coerce")
    if not (np.isfinite(result["price"]) & result["price"].gt(0)).all():
        raise ValueError("交易行情价格必须是有限正数。")
    result["is_tradable"] = normalize_boolean_values(
        result["is_tradable"],
        "交易行情可交易性标记",
    )
    for side in ("buy", "sell"):
        column = f"can_{side}"
        if column in result.columns:
            result[column] = normalize_boolean_values(result[column], f"交易行情 {column}")
        else:
            result[column] = result["is_tradable"]
        reason_column = f"{side}_block_reason"
        if reason_column not in result.columns:
            result[reason_column] = pd.NA
    return result.set_index("symbol", drop=False)


def _normalize_mapping(
    values: Mapping[str, float],
    label: str,
    maximum: float | None = None,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw_symbol, raw_value in values.items():
        symbol = str(raw_symbol).strip()
        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError(f"{label}包含无效股票代码：{raw_symbol}")
        if isinstance(raw_value, bool):
            raise ValueError(f"{label}必须包含有限非负数值。")
        try:
            value = float(raw_value)
        except TypeError, ValueError:
            raise ValueError(f"{label}必须包含有限非负数值。") from None
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{label}必须包含有限非负数值。")
        if maximum is not None and value > maximum:
            raise ValueError(f"{label}中的单项数值不能大于 {maximum}。")
        if symbol in result:
            raise ValueError(f"{label}包含重复股票代码：{symbol}")
        if value > 0:
            result[symbol] = value
    return result


def _rounded_shares(shares: float, lot_size: int | None, liquidate: bool = False) -> float:
    if shares <= 0:
        return 0.0
    if lot_size is None or liquidate:
        return shares
    return float(np.floor(shares / lot_size) * lot_size)


def _constraint_reason(quote: pd.Series, side: str) -> str | None:
    if not bool(quote["is_tradable"]):
        return "suspended_or_no_trade"
    if not bool(quote[f"can_{side}"]):
        reason = quote[f"{side}_block_reason"]
        if pd.notna(reason) and str(reason).strip():
            return str(reason).strip()
        return f"{side}_restricted"
    return None


def _empty_order(
    account: str,
    date: pd.Timestamp,
    signal_date: pd.Timestamp,
    symbol: str,
    side: str,
    target_weight: float,
    current_shares: float,
    reason: str,
) -> dict[str, object]:
    return {
        "account": account,
        "date": date,
        "signal_date": signal_date,
        "symbol": symbol,
        "side": side,
        "reference_price": np.nan,
        "estimated_price": np.nan,
        "target_weight": target_weight,
        "current_shares": current_shares,
        "requested_shares": current_shares if side == "sell" else 0.0,
        "filled_shares": 0.0,
        "gross_value": 0.0,
        "commission": 0.0,
        "stamp_duty": 0.0,
        "transaction_cost": 0.0,
        "status": "rejected",
        "reject_reason": reason,
    }


def _cash_required(
    candidates: list[dict[str, object]],
    scale: float,
    lot_size: int | None,
    cost_model: TradingCostModel,
) -> float:
    required = 0.0
    for candidate in candidates:
        shares = _rounded_shares(float(candidate["requested_shares"]) * scale, lot_size)
        gross_value = shares * float(candidate["estimated_price"])
        commission, _ = cost_model.costs(gross_value, "buy")
        required += gross_value + commission
    return required


def _affordable_scale(
    candidates: list[dict[str, object]],
    cash: float,
    lot_size: int | None,
    cost_model: TradingCostModel,
) -> float:
    if not candidates or cash <= 0:
        return 0.0
    if _cash_required(candidates, 1.0, lot_size, cost_model) <= cash:
        return 1.0
    low = 0.0
    high = 1.0
    for _ in range(60):
        middle = (low + high) / 2
        if _cash_required(candidates, middle, lot_size, cost_model) <= cash:
            low = middle
        else:
            high = middle
    return low


def _filled_order(
    candidate: dict[str, object],
    filled_shares: float,
    cost_model: TradingCostModel,
) -> dict[str, object]:
    side = str(candidate["side"])
    gross_value = filled_shares * float(candidate["estimated_price"])
    commission, stamp_duty = cost_model.costs(gross_value, side)
    requested_shares = float(candidate["requested_shares"])
    if filled_shares <= 0:
        status = "rejected"
        reason = "below_lot_or_insufficient_cash"
    elif filled_shares + 1e-12 < requested_shares:
        status = "partial"
        reason = "cash_scaled"
    else:
        status = "accepted"
        reason = ""
    return {
        **candidate,
        "filled_shares": filled_shares,
        "gross_value": gross_value,
        "commission": commission,
        "stamp_duty": stamp_duty,
        "transaction_cost": commission + stamp_duty,
        "status": status,
        "reject_reason": reason,
    }


def generate_rebalance_orders(
    current_shares: Mapping[str, float],
    target_weights: Mapping[str, float],
    quotes: pd.DataFrame,
    portfolio_value: float,
    cash: float,
    cost_model: TradingCostModel | None = None,
    lot_size: int | None = None,
    account: str = "portfolio",
    date: object = None,
    signal_date: object = None,
) -> OrderGenerationResult:
    # 先处理卖单，再按同一比例缩放买单，返回成交后账户状态。
    require_non_negative_finite(portfolio_value, "组合净值")
    require_non_negative_finite(cash, "账户现金")
    if portfolio_value <= 0:
        raise ValueError("组合净值必须为正数。")
    if lot_size is not None:
        require_positive(lot_size, "每手股数")
    model = cost_model or TradingCostModel()
    positions = _normalize_mapping(current_shares, "当前持仓")
    targets = _normalize_mapping(target_weights, "目标权重", maximum=1.0)
    if sum(targets.values()) > 1 + 1e-12:
        raise ValueError("目标权重总和不能大于 1。")
    quote_data = _normalize_quotes(quotes)
    order_date = pd.Timestamp(date).normalize() if date is not None else pd.NaT
    source_date = pd.Timestamp(signal_date).normalize() if signal_date is not None else pd.NaT
    if (date is not None and pd.isna(order_date)) or (
        signal_date is not None and pd.isna(source_date)
    ):
        raise ValueError("订单日期和信号日期必须是有效日期。")

    sell_candidates: list[dict[str, object]] = []
    buy_candidates: list[dict[str, object]] = []
    rejected_orders: list[dict[str, object]] = []
    for symbol in sorted(set(positions) | set(targets)):
        current = positions.get(symbol, 0.0)
        target_weight = targets.get(symbol, 0.0)
        if symbol not in quote_data.index:
            if current > 0 or target_weight > 0:
                side = "sell" if current > 0 and target_weight == 0 else "buy"
                rejected_orders.append(
                    _empty_order(
                        account,
                        order_date,
                        source_date,
                        symbol,
                        side,
                        target_weight,
                        current,
                        "missing_quote",
                    )
                )
            continue
        quote = quote_data.loc[symbol]
        reference_price = float(quote["price"])
        current_value = current * reference_price
        target_value = portfolio_value * target_weight
        if abs(target_value - current_value) <= 1e-12:
            continue
        side = "buy" if target_value > current_value else "sell"
        estimated_price = model.execution_price(reference_price, side)
        desired_shares = target_value / estimated_price
        requested = abs(desired_shares - current)
        requested = _rounded_shares(
            requested,
            lot_size,
            liquidate=side == "sell" and target_weight == 0,
        )
        if requested <= 1e-12:
            continue
        candidate = {
            "account": account,
            "date": order_date,
            "signal_date": source_date,
            "symbol": symbol,
            "side": side,
            "reference_price": reference_price,
            "estimated_price": estimated_price,
            "target_weight": target_weight,
            "current_shares": current,
            "requested_shares": requested,
        }
        reason = _constraint_reason(quote, side)
        if reason is not None:
            rejected_orders.append(
                {
                    **candidate,
                    "filled_shares": 0.0,
                    "gross_value": 0.0,
                    "commission": 0.0,
                    "stamp_duty": 0.0,
                    "transaction_cost": 0.0,
                    "status": "rejected",
                    "reject_reason": reason,
                }
            )
        elif side == "sell":
            sell_candidates.append(candidate)
        else:
            buy_candidates.append(candidate)

    resulting = dict(positions)
    resulting_cash = float(cash)
    filled_orders: list[dict[str, object]] = []
    for candidate in sell_candidates:
        symbol = str(candidate["symbol"])
        filled = min(float(candidate["requested_shares"]), resulting[symbol])
        order = _filled_order(candidate, filled, model)
        resulting_cash += float(order["gross_value"]) - float(order["transaction_cost"])
        remaining = resulting[symbol] - filled
        if remaining <= 1e-12:
            resulting.pop(symbol)
        else:
            resulting[symbol] = remaining
        filled_orders.append(order)

    scale = _affordable_scale(buy_candidates, resulting_cash, lot_size, model)
    for candidate in buy_candidates:
        filled = _rounded_shares(float(candidate["requested_shares"]) * scale, lot_size)
        order = _filled_order(candidate, filled, model)
        symbol = str(candidate["symbol"])
        resulting_cash -= float(order["gross_value"]) + float(order["transaction_cost"])
        if filled > 0:
            resulting[symbol] = resulting.get(symbol, 0.0) + filled
        filled_orders.append(order)

    if abs(resulting_cash) < 1e-10:
        resulting_cash = 0.0
    if resulting_cash < -1e-8:
        raise RuntimeError("订单生成后账户现金为负，成本或资金缩放逻辑存在错误。")
    orders = pd.DataFrame(
        [*filled_orders, *rejected_orders],
        columns=ORDER_COLUMNS,
    )
    gross_traded = float(orders["gross_value"].sum()) if not orders.empty else 0.0
    transaction_cost = float(orders["transaction_cost"].sum()) if not orders.empty else 0.0
    blocked_buys = (
        int(((orders["side"] == "buy") & (orders["status"] == "rejected")).sum())
        if not orders.empty
        else 0
    )
    blocked_sells = (
        int(((orders["side"] == "sell") & (orders["status"] == "rejected")).sum())
        if not orders.empty
        else 0
    )
    return OrderGenerationResult(
        orders=orders,
        resulting_shares=resulting,
        resulting_cash=resulting_cash,
        gross_traded_value=gross_traded,
        transaction_cost=transaction_cost,
        blocked_buy_count=blocked_buys,
        blocked_sell_count=blocked_sells,
    )
