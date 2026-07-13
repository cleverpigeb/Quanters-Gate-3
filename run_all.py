import argparse

import pandas as pd

from config.paths import (
    FACTOR_PROCESSED_DIR,
    FACTOR_RAW_DIR,
    MARKET_PROCESSED_DIR,
    MARKET_RAW_DIR,
    REPORT_DIR,
    UNIVERSE_DIR,
    ensure_project_directories,
)
from config.settings import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    DEFAULT_UNIVERSE,
    FORWARD_DAYS,
    IC_SAMPLE_STEP,
    INITIAL_UNIVERSE_INDEX,
    PRICE_FACTOR_COLUMNS,
    QUANTILE_COUNT,
    REBALANCE_FREQUENCY,
    UNIVERSE_SNAPSHOT_BATCH_SIZE,
)
from src.data_cleaner import build_cleaning_summary, clean_daily_bars
from src.data_fetcher import LixingerClient, fetch_universe_daily_bars
from src.factor_calculator import calculate_price_factors
from src.factor_evaluator import (
    calculate_quantile_returns,
    summarize_quantile_returns,
    summarize_top_bottom_spreads,
)
from src.factor_preprocessor import build_preprocess_summary, preprocess_factors
from src.ic_analyzer import add_forward_returns, calculate_rank_ic, summarize_rank_ic
from src.stock_pool import (
    build_index_stock_pool,
    build_index_stock_pool_history,
    monthly_rebalance_dates,
    normalize_symbols,
)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the A-share multi-factor research pipeline.")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_UNIVERSE))
    parser.add_argument(
        "--universe-date",
        help="Use a point-in-time CSI 300 constituent snapshot instead of --symbols.",
    )
    parser.add_argument(
        "--build-universe-history",
        action="store_true",
        help="Build monthly point-in-time CSI 300 membership history and exit.",
    )
    parser.add_argument(
        "--max-universe-snapshots",
        type=int,
        default=UNIVERSE_SNAPSHOT_BATCH_SIZE,
        help="Maximum missing monthly constituent snapshots to fetch in one run.",
    )
    parser.add_argument("--start", default=DEFAULT_START_DATE)
    parser.add_argument("--end", default=DEFAULT_END_DATE)
    parser.add_argument("--horizon", type=int, default=FORWARD_DAYS)
    parser.add_argument("--with-preprocess", action="store_true")
    parser.add_argument("--with-analysis", action="store_true")
    parser.add_argument("--with-evaluation", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_project_directories()

    client = LixingerClient()
    if args.build_universe_history:
        if args.universe_date:
            raise ValueError("Use either --universe-date or --build-universe-history, not both.")
        if args.max_universe_snapshots <= 0:
            raise ValueError("Maximum universe snapshots must be positive.")
        index_bars = client.fetch_index_daily_bars(INITIAL_UNIVERSE_INDEX, args.start, args.end)
        rebalancing_dates = monthly_rebalance_dates(index_bars["date"])
        snapshot_dir = UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_monthly_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshots: dict[pd.Timestamp, pd.DataFrame] = {}
        missing_dates: list[pd.Timestamp] = []
        for date in rebalancing_dates:
            snapshot_path = snapshot_dir / f"{date:%Y-%m-%d}.csv"
            if snapshot_path.exists():
                snapshots[date] = pd.read_csv(snapshot_path, dtype={"symbol": "string"})
            else:
                missing_dates.append(date)

        for date in missing_dates[:args.max_universe_snapshots]:
            snapshot = client.fetch_index_constituents(INITIAL_UNIVERSE_INDEX, date.strftime("%Y-%m-%d"))
            snapshot.to_csv(snapshot_dir / f"{date:%Y-%m-%d}.csv", index=False, encoding="utf-8-sig")
            snapshots[date] = snapshot

        if len(snapshots) < len(rebalancing_dates):
            print(
                f"Saved {len(snapshots)}/{len(rebalancing_dates)} monthly snapshots. "
                "Run the same command again to continue."
            )
            return

        membership = build_index_stock_pool_history(snapshots, INITIAL_UNIVERSE_INDEX)
        membership.to_csv(
            UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_membership.csv",
            index=False,
            encoding="utf-8-sig",
        )
        print(f"Built {len(rebalancing_dates)} monthly snapshots with {len(membership)} membership rows.")
        return

    if args.universe_date:
        constituents = client.fetch_index_constituents(INITIAL_UNIVERSE_INDEX, args.universe_date)
        stock_pool = build_index_stock_pool(constituents, INITIAL_UNIVERSE_INDEX, args.universe_date)
        stock_pool.to_csv(
            UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_{args.universe_date}.csv",
            index=False,
            encoding="utf-8-sig",
        )
        symbols = stock_pool["symbol"].tolist()
    else:
        symbols = normalize_symbols(args.symbols)

    raw_data = fetch_universe_daily_bars(symbols, args.start, args.end, client=client)
    raw_data.to_csv(MARKET_RAW_DIR / "daily_bars.csv", index=False, encoding="utf-8-sig")
    clean_data = clean_daily_bars(raw_data)
    clean_data.to_csv(MARKET_PROCESSED_DIR / "daily_bars.csv", index=False, encoding="utf-8-sig")
    build_cleaning_summary(raw_data, clean_data).to_csv(
        REPORT_DIR / "market_cleaning_summary.csv", index=False, encoding="utf-8-sig"
    )

    factor_data = calculate_price_factors(clean_data)
    factor_data.to_csv(FACTOR_RAW_DIR / "price_factors.csv", index=False, encoding="utf-8-sig")
    if not (args.with_preprocess or args.with_analysis or args.with_evaluation):
        print("Base pipeline completed. Use --with-preprocess or --with-analysis for research outputs.")
        return

    factor_columns = list(PRICE_FACTOR_COLUMNS)
    factor_data = preprocess_factors(factor_data, factor_columns)
    factor_data = add_forward_returns(factor_data, args.horizon)
    factor_data.to_csv(FACTOR_PROCESSED_DIR / "factor_panel_processed.csv", index=False, encoding="utf-8-sig")
    build_preprocess_summary(factor_data, factor_columns).to_csv(
        REPORT_DIR / "preprocess_summary.csv", index=False, encoding="utf-8-sig"
    )
    if not (args.with_analysis or args.with_evaluation):
        print("Preprocessing completed.")
        return

    rank_ic = calculate_rank_ic(factor_data, factor_columns, args.horizon, IC_SAMPLE_STEP)
    summary = summarize_rank_ic(rank_ic)
    rank_ic.to_csv(REPORT_DIR / f"rank_ic_timeseries_{args.horizon}d.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(REPORT_DIR / f"rank_ic_summary_{args.horizon}d.csv", index=False, encoding="utf-8-sig")

    if args.with_evaluation:
        quantile_returns = calculate_quantile_returns(
            factor_data, factor_columns, args.horizon, QUANTILE_COUNT, IC_SAMPLE_STEP
        )
        quantile_summary = summarize_quantile_returns(quantile_returns)
        quantile_returns.to_csv(
            REPORT_DIR / f"quantile_return_timeseries_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )
        quantile_summary.to_csv(
            REPORT_DIR / f"quantile_return_summary_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )
        summarize_top_bottom_spreads(quantile_summary, QUANTILE_COUNT).to_csv(
            REPORT_DIR / f"quantile_spread_summary_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )

    print("Research analysis completed.")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
