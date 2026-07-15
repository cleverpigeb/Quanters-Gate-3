"""编排数据构建与研究流水线。"""

from argparse import Namespace
from pathlib import Path

import pandas as pd

from quanters_gate.cache import (
    cache_daily_bar_batch,
    fetch_universe_daily_bars,
    load_cached_daily_bars,
)
from quanters_gate.cleaning import build_cleaning_summary, clean_daily_bars
from quanters_gate.evaluation import (
    calculate_quantile_returns,
    calculate_rank_ic,
    summarize_quantile_returns,
    summarize_rank_ic,
    summarize_top_bottom_spreads,
)
from quanters_gate.factors import calculate_price_factors
from quanters_gate.lixinger import LixingerClient
from quanters_gate.paths import (
    FACTOR_PROCESSED_DIR,
    FACTOR_RAW_DIR,
    MARKET_EXECUTION_BY_SYMBOL_DIR,
    MARKET_EXECUTION_DIR,
    MARKET_PROCESSED_DIR,
    MARKET_RAW_BY_SYMBOL_DIR,
    MARKET_RAW_DIR,
    REPORT_DIR,
    UNIVERSE_DIR,
    ensure_project_directories,
)
from quanters_gate.portfolio import run_monthly_top_n_backtest, summarize_backtest
from quanters_gate.preprocessing import build_preprocess_summary, preprocess_factors
from quanters_gate.returns import add_forward_returns, add_next_open_execution_returns
from quanters_gate.settings import (
    IC_SAMPLE_STEP,
    INITIAL_UNIVERSE_INDEX,
    LIXINGER_EXECUTION_PRICE_TYPE,
    LIXINGER_RESEARCH_PRICE_TYPE,
    PORTFOLIO_FACTOR_WEIGHTS,
    PORTFOLIO_ONE_WAY_COST_RATE,
    PORTFOLIO_TOP_N,
    PRICE_FACTOR_COLUMNS,
    QUANTILE_COUNT,
    REBALANCE_FREQUENCY,
)
from quanters_gate.universe import (
    ELIGIBILITY_COLUMN,
    attach_membership_eligibility,
    build_index_stock_pool,
    build_index_stock_pool_history,
    monthly_rebalance_dates,
    normalize_symbols,
    select_eligible_signals,
)
from quanters_gate.validation import require_columns, require_positive, validate_date_range

CSV_ENCODING = "utf-8-sig"


def _membership_path() -> Path:
    return UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_membership.csv"


def _history_panel_path(directory: Path) -> Path:
    return directory / f"{INITIAL_UNIVERSE_INDEX}_{REBALANCE_FREQUENCY}_panel.csv"


def _write_csv(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False, encoding=CSV_ENCODING)


def build_universe_history(args: Namespace) -> None:
    """分批构建月末指数成分历史。"""
    require_positive(args.max_universe_snapshots, "单批最大成分快照数")
    with LixingerClient() as client:
        index_bars = client.fetch_index_daily_bars(
            INITIAL_UNIVERSE_INDEX,
            args.start,
            args.end,
        )
        rebalancing_dates = monthly_rebalance_dates(index_bars["date"])
        snapshot_dir = UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_monthly_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        snapshots: dict[pd.Timestamp, pd.DataFrame] = {}
        missing_dates: list[pd.Timestamp] = []
        for date in rebalancing_dates:
            snapshot_path = snapshot_dir / f"{date:%Y-%m-%d}.csv"
            if snapshot_path.exists():
                try:
                    snapshot = pd.read_csv(snapshot_path, dtype={"symbol": "string"})
                except OSError, pd.errors.ParserError:
                    missing_dates.append(date)
                    continue
                required = {"symbol", "name", "market", "area_code"}
                if snapshot.empty or not required.issubset(snapshot.columns):
                    missing_dates.append(date)
                    continue
                snapshots[date] = snapshot
            else:
                missing_dates.append(date)

        for date in missing_dates[: args.max_universe_snapshots]:
            snapshot = client.fetch_index_constituents(
                INITIAL_UNIVERSE_INDEX,
                date.strftime("%Y-%m-%d"),
            )
            if snapshot.empty:
                raise RuntimeError(f"指数在 {date:%Y-%m-%d} 的成分快照为空，请稍后重试。")
            _write_csv(snapshot, snapshot_dir / f"{date:%Y-%m-%d}.csv")
            snapshots[date] = snapshot

    if len(snapshots) < len(rebalancing_dates):
        print(
            f"已保存 {len(snapshots)}/{len(rebalancing_dates)} 个月度快照，请再次执行相同命令继续。"
        )
        return

    membership = build_index_stock_pool_history(snapshots, INITIAL_UNIVERSE_INDEX)
    _write_csv(membership, _membership_path())
    print(f"已构建 {len(rebalancing_dates)} 个月度快照，共 {len(membership)} 条成分记录。")


def _build_market_history(
    args: Namespace,
    cache_dir: Path,
    panel_dir: Path,
    price_type: str,
    label: str,
) -> None:
    membership_path = _membership_path()
    if not membership_path.exists():
        raise FileNotFoundError("请先构建月度指数成分历史。")
    require_positive(args.max_market_symbols, "单批最大行情股票数")

    membership = pd.read_csv(membership_path, dtype={"symbol": "string"})
    require_columns(membership, ("as_of_date", "symbol"), "成分历史")
    symbols = normalize_symbols(sorted(membership["symbol"].dropna().unique().tolist()))
    with LixingerClient() as client:
        progress = cache_daily_bar_batch(
            symbols,
            args.start,
            args.end,
            cache_dir,
            client,
            args.max_market_symbols,
            price_type,
        )

    if progress["remaining"]:
        completed = progress["cached"] + progress["fetched"]
        print(f"已缓存 {completed}/{progress['total']} 只股票的{label}，请再次运行继续。")
        return

    full_history = load_cached_daily_bars(cache_dir, symbols)
    panel = attach_membership_eligibility(full_history, membership)
    _write_csv(panel, _history_panel_path(panel_dir))
    eligible_rows = int(panel[ELIGIBILITY_COLUMN].sum())
    print(f"已构建{label}：完整行情 {len(panel)} 行，其中信号日可选记录 {eligible_rows} 行。")


def build_research_market_history(args: Namespace) -> None:
    """构建复权研究行情的完整历史面板。"""
    _build_market_history(
        args,
        MARKET_RAW_BY_SYMBOL_DIR,
        MARKET_RAW_DIR,
        LIXINGER_RESEARCH_PRICE_TYPE,
        "研究行情",
    )


def build_execution_market_history(args: Namespace) -> None:
    """构建未复权执行行情的完整历史面板。"""
    _build_market_history(
        args,
        MARKET_EXECUTION_BY_SYMBOL_DIR,
        MARKET_EXECUTION_DIR,
        LIXINGER_EXECUTION_PRICE_TYPE,
        "执行行情",
    )


def _load_historical_panel() -> pd.DataFrame:
    path = _history_panel_path(MARKET_RAW_DIR)
    if not path.exists():
        raise FileNotFoundError("请先构建历史研究行情面板。")
    panel = pd.read_csv(path, dtype={"symbol": "string"})
    if ELIGIBILITY_COLUMN in panel.columns:
        return panel

    membership_path = _membership_path()
    if not membership_path.exists():
        raise FileNotFoundError("旧版行情面板缺少资格列，且找不到月度指数成分历史。")
    membership = pd.read_csv(membership_path, dtype={"symbol": "string"})
    print(
        "警告：当前共享行情是旧版成分过滤面板，无法恢复股票退出指数后的缺失价格。"
        "本次运行保持可用，但必须重新执行 --build-market-history 才能完全修复未来收益口径。"
    )
    return attach_membership_eligibility(panel, membership)


def _load_pipeline_input(args: Namespace) -> pd.DataFrame:
    if args.run_market_history:
        return _load_historical_panel()

    if args.universe_date:
        with LixingerClient() as client:
            constituents = client.fetch_index_constituents(
                INITIAL_UNIVERSE_INDEX,
                args.universe_date,
            )
            stock_pool = build_index_stock_pool(
                constituents,
                INITIAL_UNIVERSE_INDEX,
                args.universe_date,
            )
            _write_csv(
                stock_pool,
                UNIVERSE_DIR / f"{INITIAL_UNIVERSE_INDEX}_{args.universe_date}.csv",
            )
            return fetch_universe_daily_bars(
                stock_pool["symbol"].tolist(),
                args.start,
                args.end,
                client=client,
            )

    symbols = normalize_symbols(args.symbols)
    with LixingerClient() as client:
        return fetch_universe_daily_bars(
            symbols,
            args.start,
            args.end,
            client=client,
        )


def _advanced_research_requested(args: Namespace) -> bool:
    return any(
        (
            args.with_preprocess,
            args.with_analysis,
            args.with_evaluation,
            args.with_backtest,
            args.with_execution_backtest,
        )
    )


def _run_portfolio_backtest(
    factor_data: pd.DataFrame,
    args: Namespace,
) -> pd.DataFrame:
    backtest = run_monthly_top_n_backtest(
        factor_data,
        PORTFOLIO_FACTOR_WEIGHTS,
        args.horizon,
        PORTFOLIO_TOP_N,
    )
    _write_csv(backtest, REPORT_DIR / f"portfolio_backtest_{args.horizon}d.csv")
    summary = summarize_backtest(backtest)
    _write_csv(summary, REPORT_DIR / f"portfolio_backtest_summary_{args.horizon}d.csv")
    return summary


def _run_execution_backtest(
    factor_data: pd.DataFrame,
    args: Namespace,
) -> pd.DataFrame:
    execution_path = _history_panel_path(MARKET_EXECUTION_DIR)
    if not execution_path.exists():
        raise FileNotFoundError("请先构建未复权执行行情面板。")
    execution_raw = pd.read_csv(execution_path, dtype={"symbol": "string"})
    if ELIGIBILITY_COLUMN not in execution_raw.columns:
        print(
            "警告：当前执行行情是旧版成分过滤面板，必须重新执行 "
            "--build-execution-history 才能覆盖指数退出后的卖出价格。"
        )
    execution_bars = clean_daily_bars(execution_raw)
    execution_panel = add_next_open_execution_returns(
        factor_data,
        execution_bars,
        args.horizon,
    )
    backtest = run_monthly_top_n_backtest(
        execution_panel,
        PORTFOLIO_FACTOR_WEIGHTS,
        args.horizon,
        PORTFOLIO_TOP_N,
        return_column="execution_return",
        one_way_cost_rate=PORTFOLIO_ONE_WAY_COST_RATE,
    )
    _write_csv(backtest, REPORT_DIR / f"execution_backtest_{args.horizon}d.csv")
    summary = summarize_backtest(backtest)
    _write_csv(summary, REPORT_DIR / f"execution_backtest_summary_{args.horizon}d.csv")
    return summary


def run_research_pipeline(args: Namespace) -> None:
    """运行行情清洗、因子、评估和组合研究。"""
    raw_data = _load_pipeline_input(args)
    _write_csv(raw_data, MARKET_RAW_DIR / "daily_bars.csv")

    clean_data = clean_daily_bars(raw_data)
    if clean_data.empty:
        raise ValueError("行情清洗后没有可用于研究的记录。")
    _write_csv(clean_data, MARKET_PROCESSED_DIR / "daily_bars.csv")
    _write_csv(
        build_cleaning_summary(raw_data, clean_data),
        REPORT_DIR / "market_cleaning_summary.csv",
    )

    factor_data = calculate_price_factors(clean_data)
    _write_csv(factor_data, FACTOR_RAW_DIR / "price_factors.csv")
    if not _advanced_research_requested(args):
        print("基础流水线已完成。使用 --with-preprocess 或 --with-analysis 生成研究输出。")
        return

    factors = list(PRICE_FACTOR_COLUMNS)
    factor_data = add_forward_returns(factor_data, args.horizon)
    factor_data = select_eligible_signals(factor_data)
    if factor_data.empty:
        raise ValueError("当前日期范围内没有具备信号日资格的记录。")
    factor_data = preprocess_factors(factor_data, factors)
    _write_csv(factor_data, FACTOR_PROCESSED_DIR / "factor_panel_processed.csv")
    _write_csv(
        build_preprocess_summary(factor_data, factors),
        REPORT_DIR / "preprocess_summary.csv",
    )

    portfolio_summary: pd.DataFrame | None = None
    execution_summary: pd.DataFrame | None = None
    if args.with_backtest:
        portfolio_summary = _run_portfolio_backtest(factor_data, args)
    if args.with_execution_backtest:
        execution_summary = _run_execution_backtest(factor_data, args)

    rank_ic_summary: pd.DataFrame | None = None
    if args.with_analysis or args.with_evaluation:
        rank_ic = calculate_rank_ic(factor_data, factors, args.horizon, IC_SAMPLE_STEP)
        rank_ic_summary = summarize_rank_ic(rank_ic)
        _write_csv(rank_ic, REPORT_DIR / f"rank_ic_timeseries_{args.horizon}d.csv")
        _write_csv(rank_ic_summary, REPORT_DIR / f"rank_ic_summary_{args.horizon}d.csv")

    if args.with_evaluation:
        quantile_returns = calculate_quantile_returns(
            factor_data,
            factors,
            args.horizon,
            QUANTILE_COUNT,
            IC_SAMPLE_STEP,
        )
        quantile_summary = summarize_quantile_returns(quantile_returns)
        _write_csv(
            quantile_returns,
            REPORT_DIR / f"quantile_return_timeseries_{args.horizon}d.csv",
        )
        _write_csv(
            quantile_summary,
            REPORT_DIR / f"quantile_return_summary_{args.horizon}d.csv",
        )
        _write_csv(
            summarize_top_bottom_spreads(quantile_summary, QUANTILE_COUNT),
            REPORT_DIR / f"quantile_spread_summary_{args.horizon}d.csv",
        )

    if portfolio_summary is not None:
        print("组合研究回测已完成：")
        print(portfolio_summary.to_string(index=False))
    if execution_summary is not None:
        print("执行口径回测已完成：")
        print(execution_summary.to_string(index=False))
    if rank_ic_summary is not None:
        print("因子研究分析已完成：")
        print(rank_ic_summary.to_string(index=False))
    elif portfolio_summary is None and execution_summary is None:
        print("因子预处理已完成。")


def execute(args: Namespace) -> None:
    """根据命令行参数选择唯一的主工作流。"""
    validate_date_range(args.start, args.end)
    require_positive(args.horizon, "未来收益周期")
    ensure_project_directories()
    if args.build_universe_history:
        build_universe_history(args)
        return
    if args.build_market_history:
        build_research_market_history(args)
        return
    if args.build_execution_history:
        build_execution_market_history(args)
        return
    run_research_pipeline(args)
