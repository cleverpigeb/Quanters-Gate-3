import pandas as pd
import pytest

from quanters_gate.trading.orders import TradingCostModel, generate_rebalance_orders


def _quotes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["000001", "000002"],
            "price": [10.0, 20.0],
            "is_tradable": [True, True],
        }
    )


def test_orders_sell_before_buy_and_preserve_account_value() -> None:
    result = generate_rebalance_orders(
        current_shares={"000001": 10.0},
        target_weights={"000002": 1.0},
        quotes=_quotes(),
        portfolio_value=100.0,
        cash=0.0,
        date="2024-02-01",
        signal_date="2024-01-31",
    )

    assert result.orders["side"].tolist() == ["sell", "buy"]
    assert result.orders["status"].tolist() == ["accepted", "accepted"]
    assert result.resulting_shares == {"000002": pytest.approx(5.0)}
    assert result.resulting_cash == pytest.approx(0.0)
    assert result.gross_traded_value == pytest.approx(200.0)


def test_orders_keep_a_suspended_position_and_reject_unfunded_buy() -> None:
    quotes = _quotes()
    quotes.loc[quotes["symbol"].eq("000001"), "is_tradable"] = False

    result = generate_rebalance_orders(
        current_shares={"000001": 10.0},
        target_weights={"000002": 1.0},
        quotes=quotes,
        portfolio_value=100.0,
        cash=0.0,
    )

    sell = result.orders.loc[result.orders["side"].eq("sell")].iloc[0]
    buy = result.orders.loc[result.orders["side"].eq("buy")].iloc[0]
    assert sell["status"] == "rejected"
    assert sell["reject_reason"] == "suspended_or_no_trade"
    assert buy["status"] == "rejected"
    assert buy["reject_reason"] == "below_lot_or_insufficient_cash"
    assert result.resulting_shares == {"000001": 10.0}
    assert result.blocked_sell_count == 1
    assert result.blocked_buy_count == 1


def test_orders_use_explicit_limit_flags_and_reasons() -> None:
    quotes = _quotes().iloc[[0]].copy()
    quotes["can_buy"] = False
    quotes["buy_block_reason"] = "limit_up"

    result = generate_rebalance_orders(
        current_shares={},
        target_weights={"000001": 1.0},
        quotes=quotes,
        portfolio_value=10_000.0,
        cash=10_000.0,
        lot_size=100,
    )

    assert result.orders.loc[0, "status"] == "rejected"
    assert result.orders.loc[0, "reject_reason"] == "limit_up"
    assert result.resulting_cash == 10_000.0


def test_orders_apply_lots_slippage_and_minimum_commission() -> None:
    result = generate_rebalance_orders(
        current_shares={},
        target_weights={"000001": 1.0},
        quotes=_quotes().iloc[[0]],
        portfolio_value=10_000.0,
        cash=10_000.0,
        lot_size=100,
        cost_model=TradingCostModel(
            commission_rate=0.0003,
            minimum_commission=5.0,
            stamp_duty_rate=0.0005,
            slippage_rate=0.001,
        ),
    )

    order = result.orders.iloc[0]
    assert order["estimated_price"] == pytest.approx(10.01)
    assert order["filled_shares"] == 900
    assert order["commission"] == pytest.approx(5.0)
    assert order["stamp_duty"] == 0
    assert result.resulting_cash == pytest.approx(10_000 - 900 * 10.01 - 5)


def test_orders_liquidate_an_odd_lot_and_apply_sell_taxes() -> None:
    result = generate_rebalance_orders(
        current_shares={"000001": 105.0},
        target_weights={},
        quotes=_quotes().iloc[[0]],
        portfolio_value=1_050.0,
        cash=0.0,
        lot_size=100,
        cost_model=TradingCostModel(
            commission_rate=0.0003,
            minimum_commission=5.0,
            stamp_duty_rate=0.0005,
            slippage_rate=0.001,
        ),
    )

    order = result.orders.iloc[0]
    gross_value = 105 * 9.99
    assert order["filled_shares"] == 105
    assert order["gross_value"] == pytest.approx(gross_value)
    assert order["commission"] == pytest.approx(5.0)
    assert order["stamp_duty"] == pytest.approx(gross_value * 0.0005)
    assert result.resulting_shares == {}
    assert result.resulting_cash == pytest.approx(gross_value - 5.0 - gross_value * 0.0005)


def test_orders_scale_buys_proportionally_when_cash_is_limited() -> None:
    result = generate_rebalance_orders(
        current_shares={},
        target_weights={"000001": 0.5, "000002": 0.5},
        quotes=_quotes(),
        portfolio_value=1_000.0,
        cash=500.0,
    )

    assert result.orders["status"].tolist() == ["partial", "partial"]
    assert result.resulting_shares["000001"] == pytest.approx(25.0)
    assert result.resulting_shares["000002"] == pytest.approx(12.5)
    assert result.resulting_cash == pytest.approx(0.0)


def test_orders_reject_target_weights_above_full_investment() -> None:
    with pytest.raises(ValueError, match="权重总和"):
        generate_rebalance_orders(
            current_shares={},
            target_weights={"000001": 0.6, "000002": 0.6},
            quotes=_quotes(),
            portfolio_value=1_000.0,
            cash=1_000.0,
        )
