import pandas as pd


def add_next_open_execution_returns(
    signals: pd.DataFrame,
    execution_bars: pd.DataFrame,
    horizon: int,
) -> pd.DataFrame:
    """Attach next-open to future-open returns from unadjusted execution prices."""
    if horizon <= 0:
        raise ValueError("Execution horizon must be positive.")
    required = {"date", "symbol", "open", "is_tradable", "price_type"}
    missing = required.difference(execution_bars.columns)
    if missing:
        raise ValueError(f"Execution bars are missing columns: {missing}")
    if not execution_bars["price_type"].eq("ex_rights").all():
        raise ValueError("Execution bars must use ex_rights prices.")

    bars = execution_bars.copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="coerce")
    bars["symbol"] = bars["symbol"].astype("string")
    bars = bars.dropna(subset=["date", "symbol", "open"]).sort_values(["symbol", "date"])
    grouped = bars.groupby("symbol")
    bars["entry_open"] = grouped["open"].shift(-1)
    bars["exit_open"] = grouped["open"].shift(-(horizon + 1))
    bars["entry_tradable"] = grouped["is_tradable"].shift(-1)
    bars["exit_tradable"] = grouped["is_tradable"].shift(-(horizon + 1))
    execution = bars[
        ["date", "symbol", "entry_open", "exit_open", "entry_tradable", "exit_tradable"]
    ]
    result = signals.merge(execution, on=["date", "symbol"], how="left", validate="one_to_one")
    ready = result["entry_tradable"].fillna(False) & result["exit_tradable"].fillna(False)
    result["execution_return"] = (result["exit_open"] / result["entry_open"] - 1).where(ready)
    return result
