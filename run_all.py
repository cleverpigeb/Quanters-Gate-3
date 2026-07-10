import argparse

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
)
from src.data_cleaner import clean_daily_bars
from src.data_fetcher import LixingerClient, fetch_universe_daily_bars
from src.factor_calculator import calculate_price_factors
from src.factor_evaluator import calculate_quantile_returns, summarize_quantile_returns
from src.factor_preprocessor import build_preprocess_summary, preprocess_factors
from src.ic_analyzer import add_forward_returns, calculate_rank_ic, summarize_rank_ic
from src.stock_pool import build_index_stock_pool, normalize_symbols

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the A-share multi-factor research pipeline.")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_UNIVERSE))
    parser.add_argument(
        "--universe-date",
        help="Use a point-in-time CSI 300 constituent snapshot instead of --symbols.",
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
            factor_data, factor_columns, args.horizon, QUANTILE_COUNT
        )
        summarize_quantile_returns(quantile_returns).to_csv(
            REPORT_DIR / f"quantile_returns_{args.horizon}d.csv", index=False, encoding="utf-8-sig"
        )

    print("Research analysis completed.")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
