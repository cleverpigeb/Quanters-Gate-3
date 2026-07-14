import argparse

import pandas as pd

from config.paths import (
    FACTOR_PROCESSED_DIR,
    FACTOR_RAW_DIR,
    MARKET_PROCESSED_DIR,
    MARKET_EXECUTION_BY_SYMBOL_DIR,
    MARKET_EXECUTION_DIR,
    MARKET_RAW_DIR,
    MARKET_RAW_BY_SYMBOL_DIR,
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
    LIXINGER_EXECUTION_PRICE_TYPE,
    MARKET_FETCH_BATCH_SIZE,
    PRICE_FACTOR_COLUMNS,
    PORTFOLIO_FACTOR_WEIGHTS,
    PORTFOLIO_ONE_WAY_COST_RATE,
    PORTFOLIO_TOP_N,
    QUANTILE_COUNT,
    REBALANCE_FREQUENCY,
    UNIVERSE_SNAPSHOT_BATCH_SIZE,
)
from src.data_cleaner import build_cleaning_summary, clean_daily_bars
from src.data_fetcher import (
    LixingerClient,
    cache_daily_bar_batch,
    fetch_universe_daily_bars,
    load_cached_daily_bars,
)
from src.factor_calculator import calculate_price_factors
from src.execution_returns import add_next_open_execution_returns
from src.factor_evaluator import (
    calculate_quantile_returns,
    summarize_quantile_returns,
    summarize_top_bottom_spreads,
)
from src.factor_preprocessor import build_preprocess_summary, preprocess_factors
from src.ic_analyzer import add_forward_returns, calculate_rank_ic, summarize_rank_ic
from src.portfolio_backtester import run_monthly_top_n_backtest, summarize_backtest
from src.stock_pool import (
    build_index_stock_pool,
    build_index_stock_pool_history,
    filter_to_membership_history,
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
    parser.add_argument(
        "--build-market-history",
        action="store_true",
        help="Fetch cached daily bars for all symbols in monthly CSI 300 membership history and exit.",
    )
    parser.add_argument(
        "--build-execution-history",
        action="store_true",
        help="Fetch unadjusted execution-price history and build the eligible panel.",
    )
    parser.add_argument(
        "--run-market-history",
        action="store_true",
        help="Run the research pipeline on the completed monthly CSI 300 historical market panel.",
    )
    parser.add_argument(
        "--max-market-symbols",
        type=int,
        default=MARKET_FETCH_BATCH_SIZE,
        help="Maximum missing symbol histories to fetch in one market-history run.",
    )
    parser.add_argument("--start", default=DEFAULT_START_DATE)
    parser.add_argument("--end", default=DEFAULT_END_DATE)
    parser.add_argument("--horizon", type=int, default=FORWARD_DAYS)
    parser.add_argument("--with-preprocess", action="store_true")
    parser.add_argument("--with-analysis", action="store_true")
    parser.add_argument("--with-evaluation", action="store_true")
    parser.add_argument(
        "--with-backtest",
        action="store_true",
        help="Run the simple monthly Top N factor-portfolio research backtest.",
    )
    parser.add_argument(
        "--with-execution-backtest",
        action="store_true",
        help="Run the next-open, cost-adjusted research execution backtest.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_project_directories()

    membership_path = UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_membership.csv"
    if args.build_universe_history:
        if args.universe_date:
            raise ValueError("Use either --universe-date or --build-universe-history, not both.")
        if args.max_universe_snapshots <= 0:
            raise ValueError("Maximum universe snapshots must be positive.")
        client = LixingerClient()
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

    if args.build_market_history:
        if not membership_path.exists():
            raise FileNotFoundError("Build the monthly universe history before fetching market history.")
        client = LixingerClient()
        membership_history = pd.read_csv(membership_path, dtype={"symbol": "string"})
        symbols = sorted(membership_history["symbol"].unique().tolist())
        progress = cache_daily_bar_batch(
            symbols,
            args.start,
            args.end,
            MARKET_RAW_BY_SYMBOL_DIR,
            client,
            args.max_market_symbols,
        )
        if progress["remaining"]:
            print(
                f"Cached {progress['cached'] + progress['fetched']}/{progress['total']} symbol histories. "
                "Run the same command again to continue."
            )
            return
        raw_history = load_cached_daily_bars(MARKET_RAW_BY_SYMBOL_DIR, symbols)
        eligible_history = filter_to_membership_history(raw_history, membership_history)
        eligible_history.to_csv(
            MARKET_RAW_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_panel.csv",
            index=False,
            encoding="utf-8-sig",
        )
        print(f"Built historical market panel with {len(eligible_history)} eligible daily bars.")
        return

    if args.build_execution_history:
        if not membership_path.exists():
            raise FileNotFoundError("Build the monthly universe history before fetching execution history.")
        client = LixingerClient()
        membership_history = pd.read_csv(membership_path, dtype={"symbol": "string"})
        symbols = sorted(membership_history["symbol"].unique().tolist())
        progress = cache_daily_bar_batch(
            symbols, args.start, args.end, MARKET_EXECUTION_BY_SYMBOL_DIR, client,
            args.max_market_symbols, LIXINGER_EXECUTION_PRICE_TYPE,
        )
        if progress["remaining"]:
            print(f"Cached {progress['cached'] + progress['fetched']}/{progress['total']} execution histories. Run again to continue.")
            return
        execution = load_cached_daily_bars(MARKET_EXECUTION_BY_SYMBOL_DIR, symbols)
        filter_to_membership_history(execution, membership_history).to_csv(
            MARKET_EXECUTION_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_panel.csv",
            index=False, encoding="utf-8-sig",
        )
        print("Built historical execution panel.")
        return

    if args.run_market_history:
        if args.universe_date:
            raise ValueError("Use either --universe-date or --run-market-history, not both.")
        history_panel_path = MARKET_RAW_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_panel.csv"
        if not history_panel_path.exists():
            raise FileNotFoundError("Build the membership-filtered market panel before running historical research.")
        raw_data = pd.read_csv(history_panel_path, dtype={"symbol": "string"})
    elif args.universe_date:
        client = LixingerClient()
        constituents = client.fetch_index_constituents(INITIAL_UNIVERSE_INDEX, args.universe_date)
        stock_pool = build_index_stock_pool(constituents, INITIAL_UNIVERSE_INDEX, args.universe_date)
        stock_pool.to_csv(
            UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_{args.universe_date}.csv",
            index=False,
            encoding="utf-8-sig",
        )
        symbols = stock_pool["symbol"].tolist()
        raw_data = fetch_universe_daily_bars(symbols, args.start, args.end, client=client)
    else:
        client = LixingerClient()
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
    if not (args.with_preprocess or args.with_analysis or args.with_evaluation or args.with_backtest or args.with_execution_backtest):
        print("Base pipeline completed. Use --with-preprocess or --with-analysis for research outputs.")
        return

    factor_columns = list(PRICE_FACTOR_COLUMNS)
    factor_data = preprocess_factors(factor_data, factor_columns)
    factor_data = add_forward_returns(factor_data, args.horizon)
    factor_data.to_csv(FACTOR_PROCESSED_DIR / "factor_panel_processed.csv", index=False, encoding="utf-8-sig")
    build_preprocess_summary(factor_data, factor_columns).to_csv(
        REPORT_DIR / "preprocess_summary.csv", index=False, encoding="utf-8-sig"
    )
    if args.with_backtest:
        backtest = run_monthly_top_n_backtest(
            factor_data,
            PORTFOLIO_FACTOR_WEIGHTS,
            args.horizon,
            PORTFOLIO_TOP_N,
        )
        backtest.to_csv(
            REPORT_DIR / f"portfolio_backtest_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )
        portfolio_summary = summarize_backtest(backtest)
        portfolio_summary.to_csv(
            REPORT_DIR / f"portfolio_backtest_summary_{args.horizon}d.csv",
            index=False,
            encoding="utf-8-sig",
        )
    if args.with_execution_backtest:
        execution_path = MARKET_EXECUTION_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_panel.csv"
        if not execution_path.exists():
            raise FileNotFoundError("Build the unadjusted execution panel before running the execution backtest.")
        execution_bars = clean_daily_bars(pd.read_csv(execution_path, dtype={"symbol": "string"}))
        execution_panel = add_next_open_execution_returns(factor_data, execution_bars, args.horizon)
        execution_backtest = run_monthly_top_n_backtest(
            execution_panel, PORTFOLIO_FACTOR_WEIGHTS, args.horizon, PORTFOLIO_TOP_N,
            return_column="execution_return", one_way_cost_rate=PORTFOLIO_ONE_WAY_COST_RATE,
        )
        execution_backtest.to_csv(
            REPORT_DIR / f"execution_backtest_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )
        summarize_backtest(execution_backtest).to_csv(
            REPORT_DIR / f"execution_backtest_summary_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )
    if not (args.with_analysis or args.with_evaluation):
        if args.with_backtest:
            print("Portfolio research backtest completed.")
            print(portfolio_summary.to_string(index=False))
            return
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
