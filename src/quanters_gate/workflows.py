# 编排数据构建与研究流水线。

from argparse import Namespace
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pandas as pd

from quanters_gate.backtest.continuous import (
    run_continuous_top_n_backtest,
    summarize_continuous_backtest,
)
from quanters_gate.backtest.execution import add_next_open_execution_returns
from quanters_gate.backtest.portfolio import run_monthly_top_n_backtest, summarize_backtest
from quanters_gate.data.cache import (
    cache_daily_bar_batch,
    load_cached_daily_bars,
)
from quanters_gate.data.cleaning import build_cleaning_summary, clean_daily_bars
from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.data.fundamentals import (
    FINANCIAL_FACTOR_COLUMNS,
    attach_fundamentals_asof,
    cache_fundamental_batch,
    load_cached_fundamentals,
)
from quanters_gate.data.provider import (
    MarketDataProvider,
    MarketDataProviderFactory,
    fetch_universe_daily_bars,
)
from quanters_gate.data.universe import (
    ELIGIBILITY_COLUMN,
    attach_membership_eligibility,
    build_index_stock_pool,
    build_index_stock_pool_history,
    monthly_rebalance_dates,
    normalize_membership_history,
    normalize_symbols,
    select_eligible_signals,
)
from quanters_gate.paths import (
    FACTOR_PROCESSED_DIR,
    FACTOR_RAW_DIR,
    FUNDAMENTALS_PROCESSED_DIR,
    FUNDAMENTALS_RAW_DIR,
    MARKET_EXECUTION_BY_SYMBOL_DIR,
    MARKET_EXECUTION_DIR,
    MARKET_PROCESSED_DIR,
    MARKET_RAW_BY_SYMBOL_DIR,
    MARKET_RAW_DIR,
    REPORT_DIR,
    UNIVERSE_DIR,
    ensure_project_directories,
)
from quanters_gate.research.evaluation import (
    build_factor_diagnostic_summary,
    calculate_factor_rank_correlations,
    calculate_quantile_returns,
    calculate_rank_ic,
    summarize_factor_rank_correlations,
    summarize_quantile_returns,
    summarize_rank_ic,
    summarize_rank_ic_by_year,
    summarize_top_bottom_spreads,
)
from quanters_gate.research.factors import PRICE_FACTOR_COLUMNS, calculate_price_factors
from quanters_gate.research.preprocessing import build_preprocess_summary, preprocess_factors
from quanters_gate.research.returns import add_forward_returns
from quanters_gate.settings import PROJECT_CONFIG, RunConfig, serialize_run_config
from quanters_gate.storage import atomic_write_csv, atomic_write_text
from quanters_gate.validation import (
    require_columns,
    require_positive,
    validate_date_range,
    validate_non_overlapping_sample,
)

CSV_ENCODING = "utf-8-sig"


def _membership_path() -> Path:
    universe = PROJECT_CONFIG.universe
    return UNIVERSE_DIR / f"{universe.index_code}_{universe.rebalance_frequency}_membership.csv"


def _history_panel_path(directory: Path) -> Path:
    universe = PROJECT_CONFIG.universe
    return directory / f"{universe.index_code}_{universe.rebalance_frequency}_panel.csv"


def _write_csv(data: pd.DataFrame, path: Path) -> None:
    atomic_write_csv(data, path, encoding=CSV_ENCODING)


def _normalized_research_dates(args: Namespace) -> tuple[str, str]:
    start, end = validate_date_range(args.start, args.end)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _normalized_single_date(value: str) -> str:
    date, _ = validate_date_range(value, value)
    return date.strftime("%Y-%m-%d")


def _resolve_run_config(args: Namespace, resolved_symbols: list[str]) -> RunConfig:
    start_date, end_date = _normalized_research_dates(args)
    if args.run_market_history:
        mode = "historical_market"
    elif args.universe_date:
        mode = "universe_snapshot"
    else:
        mode = "symbols"
    return RunConfig(
        schema_version=PROJECT_CONFIG.schema_version,
        mode=mode,
        universe_date=_normalized_single_date(args.universe_date) if args.universe_date else None,
        with_preprocess=any(
            (
                args.with_preprocess,
                args.with_analysis,
                args.with_evaluation,
                args.with_backtest,
                args.with_execution_backtest,
                args.with_continuous_backtest,
            )
        ),
        with_analysis=args.with_analysis or args.with_evaluation,
        with_evaluation=args.with_evaluation,
        with_backtest=args.with_backtest,
        with_execution_backtest=args.with_execution_backtest,
        with_continuous_backtest=args.with_continuous_backtest,
        research=replace(
            PROJECT_CONFIG.research,
            start_date=start_date,
            end_date=end_date,
            forward_days=args.horizon,
        ),
        universe=replace(
            PROJECT_CONFIG.universe,
            symbols=tuple(normalize_symbols(resolved_symbols)),
            snapshot_batch_size=args.max_universe_snapshots,
            market_fetch_batch_size=args.max_market_symbols,
        ),
        data=PROJECT_CONFIG.data,
        portfolio=PROJECT_CONFIG.portfolio,
    )


def _write_run_config(config: RunConfig) -> None:
    atomic_write_text(serialize_run_config(config), REPORT_DIR / "run_config.toml")


@contextmanager
def _provider_session(
    provider_factory: MarketDataProviderFactory,
) -> Iterator[MarketDataProvider]:
    provider = provider_factory()
    try:
        if provider.provider_name != PROJECT_CONFIG.data.provider:
            raise ValueError(
                f"配置的数据源 {PROJECT_CONFIG.data.provider} 与注入的数据源 "
                f"{provider.provider_name} 不一致。"
            )
        yield provider
    finally:
        provider.close()


def build_universe_history(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> None:
    # 分批构建月末指数成分历史。
    require_positive(args.max_universe_snapshots, "单批最大成分快照数")
    universe = PROJECT_CONFIG.universe
    with _provider_session(provider_factory) as provider:
        index_bars = provider.fetch_index_daily_bars(
            universe.index_code,
            args.start,
            args.end,
        )
        rebalancing_dates = monthly_rebalance_dates(index_bars["date"])
        snapshot_dir = UNIVERSE_DIR / f"{universe.index_code}_monthly_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        snapshots: dict[pd.Timestamp, pd.DataFrame] = {}
        missing_dates: list[pd.Timestamp] = []
        for date in rebalancing_dates:
            snapshot_path = snapshot_dir / f"{date:%Y-%m-%d}.csv"
            if snapshot_path.exists():
                try:
                    snapshot = pd.read_csv(snapshot_path, dtype={"symbol": "string"})
                    build_index_stock_pool(snapshot, universe.index_code, date)
                except OSError, ValueError, pd.errors.ParserError:
                    missing_dates.append(date)
                    continue
                snapshots[date] = snapshot
            else:
                missing_dates.append(date)

        for date in missing_dates[: args.max_universe_snapshots]:
            snapshot = provider.fetch_index_constituents(
                universe.index_code,
                date.strftime("%Y-%m-%d"),
            )
            if snapshot.empty:
                raise RuntimeError(f"指数在 {date:%Y-%m-%d} 的成分快照为空，请稍后重试。")
            build_index_stock_pool(snapshot, universe.index_code, date)
            _write_csv(snapshot, snapshot_dir / f"{date:%Y-%m-%d}.csv")
            snapshots[date] = snapshot

    if len(snapshots) < len(rebalancing_dates):
        print(
            f"已保存 {len(snapshots)}/{len(rebalancing_dates)} 个月度快照，请再次执行相同命令继续。"
        )
        return

    membership = build_index_stock_pool_history(snapshots, universe.index_code)
    _write_csv(membership, _membership_path())
    print(f"已构建 {len(rebalancing_dates)} 个月度快照，共 {len(membership)} 条成分记录。")


def _build_market_history(
    args: Namespace,
    cache_dir: Path,
    panel_dir: Path,
    price_type: str,
    label: str,
    provider_factory: MarketDataProviderFactory,
) -> None:
    membership_path = _membership_path()
    if not membership_path.exists():
        raise FileNotFoundError("请先构建月度指数成分历史。")
    require_positive(args.max_market_symbols, "单批最大行情股票数")

    membership = normalize_membership_history(
        pd.read_csv(membership_path, dtype={"index_code": "string", "symbol": "string"})
    )
    require_columns(membership, ("index_code",), "成分历史")
    if not membership["index_code"].eq(PROJECT_CONFIG.universe.index_code).all():
        raise ValueError("成分历史包含与当前配置不一致的指数代码。")
    symbols = normalize_symbols(sorted(membership["symbol"].dropna().unique().tolist()))
    with _provider_session(provider_factory) as provider:
        progress = cache_daily_bar_batch(
            symbols,
            args.start,
            args.end,
            cache_dir,
            provider,
            args.max_market_symbols,
            price_type,
        )

    if progress["remaining"]:
        completed = progress["cached"] + progress["fetched"]
        print(
            f"本次新缓存 {progress['fetched']} 只、已有有效缓存 {progress['cached']} 只、"
            f"失败 {progress['failed']} 只；当前已完成 {completed}/{progress['total']} 只股票的"
            f"{label}，请再次运行继续。"
        )
        return

    full_history = load_cached_daily_bars(cache_dir, symbols)
    panel = attach_membership_eligibility(full_history, membership)
    _write_csv(panel, _history_panel_path(panel_dir))
    eligible_rows = int(panel[ELIGIBILITY_COLUMN].sum())
    print(f"已构建{label}：完整行情 {len(panel)} 行，其中信号日可选记录 {eligible_rows} 行。")


def build_research_market_history(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> None:
    # 构建复权研究行情的完整历史面板。
    _build_market_history(
        args,
        MARKET_RAW_BY_SYMBOL_DIR,
        MARKET_RAW_DIR,
        PROJECT_CONFIG.data.research_price_type,
        "研究行情",
        provider_factory,
    )


def build_execution_market_history(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> None:
    # 构建未复权执行行情的完整历史面板。
    _build_market_history(
        args,
        MARKET_EXECUTION_BY_SYMBOL_DIR,
        MARKET_EXECUTION_DIR,
        PROJECT_CONFIG.data.execution_price_type,
        "执行行情",
        provider_factory,
    )


def build_fundamental_history(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> None:
    # 分批构建历史成分股的财务 point-in-time 输入面板。
    membership_path = _membership_path()
    if not membership_path.exists():
        raise FileNotFoundError("请先构建月度指数成分历史。")
    require_positive(args.max_fundamental_symbols, "单批最大财务股票数")
    membership = normalize_membership_history(
        pd.read_csv(membership_path, dtype={"index_code": "string", "symbol": "string"})
    )
    symbols = normalize_symbols(sorted(membership["symbol"].dropna().unique().tolist()))
    with _provider_session(provider_factory) as provider:
        if not hasattr(provider, "fetch_financial_abstract") or not hasattr(
            provider, "fetch_financial_statement_updates"
        ):
            raise ValueError("当前数据源不支持财务摘要和报表更新时间。")
        completed, failures = cache_fundamental_batch(
            symbols,
            provider,
            FUNDAMENTALS_RAW_DIR / "by_symbol",
            args.max_fundamental_symbols,
        )
        panel = load_cached_fundamentals(
            symbols,
            provider.provider_name,
            FUNDAMENTALS_RAW_DIR / "by_symbol",
        )
    cached_symbols = panel["symbol"].nunique()
    if cached_symbols < len(symbols):
        print(
            f"本次新缓存 {completed} 只、失败 {failures} 只；当前完成 {cached_symbols}/{len(symbols)} 只财务股票，请再次运行继续。"
        )
        return
    _write_csv(panel, FUNDAMENTALS_PROCESSED_DIR / "fundamental_panel.csv")
    print(
        f"已构建财务 point-in-time 面板：{len(panel)} 条报告期记录，覆盖 {cached_symbols} 只股票。"
    )


def _load_historical_panel() -> pd.DataFrame:
    path = _history_panel_path(MARKET_RAW_DIR)
    if not path.exists():
        raise FileNotFoundError("请先构建历史研究行情面板。")
    panel = pd.read_csv(path, dtype={"symbol": "string"})
    require_columns(panel, ("price_type",), "历史研究行情面板")
    price_types = panel["price_type"].astype("string")
    expected_price_type = PROJECT_CONFIG.data.research_price_type
    if price_types.isna().any() or not price_types.eq(expected_price_type).all():
        raise ValueError(f"历史研究行情面板必须全部使用 {expected_price_type} 价格口径。")
    if PROJECT_CONFIG.data.provider == "akshare":
        require_columns(panel, ("data_source",), "AKShare 历史研究行情面板")
        data_sources = panel["data_source"].astype("string")
        if data_sources.isna().any() or not data_sources.isin({"eastmoney", "sina"}).all():
            raise ValueError("AKShare 历史研究行情面板包含无效或缺失的数据来源标记。")
    elif "data_source" in panel.columns and panel["data_source"].notna().any():
        raise ValueError("历史研究行情面板的数据来源与当前理杏仁配置不一致。")
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


def _load_pipeline_input(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> pd.DataFrame:
    if args.run_market_history:
        return _load_historical_panel()

    if args.universe_date:
        universe = PROJECT_CONFIG.universe
        universe_date = _normalized_single_date(args.universe_date)
        with _provider_session(provider_factory) as provider:
            constituents = provider.fetch_index_constituents(
                universe.index_code,
                universe_date,
            )
            stock_pool = build_index_stock_pool(
                constituents,
                universe.index_code,
                universe_date,
            )
            _write_csv(
                stock_pool,
                UNIVERSE_DIR / f"{universe.index_code}_{universe_date}.csv",
            )
            return fetch_universe_daily_bars(
                stock_pool["symbol"].tolist(),
                args.start,
                args.end,
                provider=provider,
                price_type=PROJECT_CONFIG.data.research_price_type,
            )

    symbols = normalize_symbols(args.symbols)
    with _provider_session(provider_factory) as provider:
        return fetch_universe_daily_bars(
            symbols,
            args.start,
            args.end,
            provider=provider,
            price_type=PROJECT_CONFIG.data.research_price_type,
        )


def _filter_signal_date_range(data: pd.DataFrame, args: Namespace) -> pd.DataFrame:
    # 仅限制信号日期，因子回看和未来收益仍使用完整行情历史。
    require_columns(data, ("date",), "信号数据")
    start_date, end_date = _normalized_research_dates(args)
    result = data.copy()
    result["date"] = normalize_required_trade_dates(result["date"], "信号数据")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return result.loc[result["date"].between(start, end)].copy()


def _run_portfolio_backtest(
    factor_data: pd.DataFrame,
    args: Namespace,
) -> pd.DataFrame:
    portfolio = PROJECT_CONFIG.portfolio
    backtest = run_monthly_top_n_backtest(
        factor_data,
        portfolio.factor_weights,
        args.horizon,
        portfolio.top_n,
    )
    _write_csv(backtest, REPORT_DIR / f"portfolio_backtest_{args.horizon}d.csv")
    summary = summarize_backtest(backtest)
    _write_csv(summary, REPORT_DIR / f"portfolio_backtest_summary_{args.horizon}d.csv")
    return summary


def _run_execution_backtest(
    factor_data: pd.DataFrame,
    args: Namespace,
) -> pd.DataFrame:
    portfolio = PROJECT_CONFIG.portfolio
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
        portfolio.factor_weights,
        args.horizon,
        portfolio.top_n,
        return_column="execution_return",
        one_way_cost_rate=portfolio.one_way_cost_rate,
    )
    _write_csv(backtest, REPORT_DIR / f"execution_backtest_{args.horizon}d.csv")
    summary = summarize_backtest(backtest)
    _write_csv(summary, REPORT_DIR / f"execution_backtest_summary_{args.horizon}d.csv")
    return summary


def _run_continuous_backtest(
    factor_data: pd.DataFrame,
    market_bars: pd.DataFrame,
) -> pd.DataFrame:
    portfolio = PROJECT_CONFIG.portfolio
    result = run_continuous_top_n_backtest(
        factor_data,
        market_bars,
        portfolio.factor_weights,
        portfolio.top_n,
        portfolio.one_way_cost_rate,
    )
    _write_csv(result.daily, REPORT_DIR / "continuous_backtest.csv")
    _write_csv(result.orders, REPORT_DIR / "continuous_backtest_orders.csv")
    _write_csv(result.trades, REPORT_DIR / "continuous_backtest_trades.csv")
    _write_csv(result.holdings, REPORT_DIR / "continuous_backtest_holdings.csv")
    summary = summarize_continuous_backtest(result.daily)
    _write_csv(summary, REPORT_DIR / "continuous_backtest_summary.csv")
    return summary


def run_research_pipeline(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> None:
    # 运行行情清洗、因子、评估和组合研究。
    raw_data = _load_pipeline_input(args, provider_factory)
    _write_csv(raw_data, MARKET_RAW_DIR / "daily_bars.csv")

    clean_data = clean_daily_bars(raw_data)
    if clean_data.empty:
        raise ValueError("行情清洗后没有可用于研究的记录。")
    run_config = _resolve_run_config(args, clean_data["symbol"].drop_duplicates().tolist())
    _write_csv(clean_data, MARKET_PROCESSED_DIR / "daily_bars.csv")
    _write_csv(
        build_cleaning_summary(raw_data, clean_data),
        REPORT_DIR / "market_cleaning_summary.csv",
    )

    factor_data = calculate_price_factors(clean_data)
    fundamental_path = FUNDAMENTALS_PROCESSED_DIR / "fundamental_panel.csv"
    factors = list(PRICE_FACTOR_COLUMNS)
    if args.run_market_history and fundamental_path.exists():
        fundamentals = pd.read_csv(fundamental_path, dtype={"symbol": "string"})
        factor_data = attach_fundamentals_asof(factor_data, fundamentals)
        factors.extend(FINANCIAL_FACTOR_COLUMNS)
    _write_csv(factor_data, FACTOR_RAW_DIR / "price_factors.csv")
    if not run_config.with_preprocess:
        _write_run_config(run_config)
        print("基础流水线已完成。使用 --with-preprocess 或 --with-analysis 生成研究输出。")
        return

    factor_data = add_forward_returns(factor_data, args.horizon)
    factor_data = _filter_signal_date_range(factor_data, args)
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
    continuous_summary: pd.DataFrame | None = None
    if args.with_backtest:
        portfolio_summary = _run_portfolio_backtest(factor_data, args)
    if args.with_execution_backtest:
        execution_summary = _run_execution_backtest(factor_data, args)
    if args.with_continuous_backtest:
        continuous_summary = _run_continuous_backtest(factor_data, clean_data)

    rank_ic_summary: pd.DataFrame | None = None
    if args.with_analysis or args.with_evaluation:
        rank_ic = calculate_rank_ic(
            factor_data,
            factors,
            args.horizon,
            PROJECT_CONFIG.research.ic_sample_step,
        )
        rank_ic_summary = summarize_rank_ic(rank_ic)
        _write_csv(rank_ic, REPORT_DIR / f"rank_ic_timeseries_{args.horizon}d.csv")
        _write_csv(rank_ic_summary, REPORT_DIR / f"rank_ic_summary_{args.horizon}d.csv")
        _write_csv(
            summarize_rank_ic_by_year(rank_ic),
            REPORT_DIR / f"rank_ic_yearly_summary_{args.horizon}d.csv",
        )

    if args.with_evaluation:
        quantile_returns = calculate_quantile_returns(
            factor_data,
            factors,
            args.horizon,
            PROJECT_CONFIG.research.quantile_count,
            PROJECT_CONFIG.research.ic_sample_step,
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
            summarize_top_bottom_spreads(
                quantile_summary,
                PROJECT_CONFIG.research.quantile_count,
            ),
            REPORT_DIR / f"quantile_spread_summary_{args.horizon}d.csv",
        )
        _write_csv(
            build_factor_diagnostic_summary(
                rank_ic,
                quantile_summary,
                PROJECT_CONFIG.research.quantile_count,
            ),
            REPORT_DIR / f"factor_diagnostic_summary_{args.horizon}d.csv",
        )
        factor_correlations = calculate_factor_rank_correlations(
            factor_data,
            factors,
            args.horizon,
        )
        _write_csv(
            summarize_factor_rank_correlations(factor_correlations),
            REPORT_DIR / f"factor_rank_correlation_summary_{args.horizon}d.csv",
        )

    _write_run_config(run_config)
    if portfolio_summary is not None:
        print("组合研究回测已完成：")
        print(portfolio_summary.to_string(index=False))
    if execution_summary is not None:
        print("执行口径回测已完成：")
        print(execution_summary.to_string(index=False))
    if continuous_summary is not None:
        print("连续净值研究回测已完成：")
        print(continuous_summary.to_string(index=False))
    if rank_ic_summary is not None:
        print("因子研究分析已完成：")
        print(rank_ic_summary.to_string(index=False))
    elif portfolio_summary is None and execution_summary is None and continuous_summary is None:
        print("因子预处理已完成。")


def execute(
    args: Namespace,
    provider_factory: MarketDataProviderFactory,
) -> None:
    # 根据命令行参数选择唯一的主工作流。
    validate_date_range(args.start, args.end)
    require_positive(args.horizon, "未来收益周期")
    require_positive(args.max_universe_snapshots, "单批最大成分快照数")
    require_positive(args.max_market_symbols, "单批最大行情股票数")
    require_positive(args.max_fundamental_symbols, "单批最大财务股票数")
    if args.with_analysis or args.with_evaluation:
        validate_non_overlapping_sample(
            args.horizon,
            PROJECT_CONFIG.research.ic_sample_step,
        )
    ensure_project_directories()
    if args.build_universe_history:
        build_universe_history(args, provider_factory)
        return
    if args.build_market_history:
        build_research_market_history(args, provider_factory)
        return
    if args.build_execution_history:
        build_execution_market_history(args, provider_factory)
        return
    if args.build_fundamental_history:
        build_fundamental_history(args, provider_factory)
        return
    run_research_pipeline(args, provider_factory)
