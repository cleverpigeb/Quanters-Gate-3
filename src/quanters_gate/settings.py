# 读取并校验项目级 TOML 配置。

import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType

from quanters_gate.paths import PROJECT_ROOT
from quanters_gate.research.factors import PRICE_FACTOR_COLUMNS
from quanters_gate.validation import validate_non_overlapping_sample

CONFIG_PATH = PROJECT_ROOT / "config" / "default.toml"


@dataclass(frozen=True)
class ResearchConfig:
    start_date: str
    end_date: str
    forward_days: int
    ic_sample_step: int
    quantile_count: int
    random_seed: int


@dataclass(frozen=True)
class UniverseConfig:
    symbols: tuple[str, ...]
    index_code: str
    index_name: str
    rebalance_frequency: str
    snapshot_batch_size: int
    market_fetch_batch_size: int


@dataclass(frozen=True)
class DataConfig:
    provider: str
    research_price_type: str
    execution_price_type: str


@dataclass(frozen=True)
class PortfolioConfig:
    top_n: int
    one_way_cost_rate: float
    factor_weights: Mapping[str, float]


@dataclass(frozen=True)
class ProjectConfig:
    source_path: Path
    schema_version: int
    research: ResearchConfig
    universe: UniverseConfig
    data: DataConfig
    portfolio: PortfolioConfig


@dataclass(frozen=True)
class RunConfig:
    schema_version: int
    mode: str
    universe_date: str | None
    with_preprocess: bool
    with_analysis: bool
    with_evaluation: bool
    with_backtest: bool
    with_execution_backtest: bool
    research: ResearchConfig
    universe: UniverseConfig
    data: DataConfig
    portfolio: PortfolioConfig


def _require_table(data: Mapping[str, object], key: str, label: str) -> Mapping[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"配置文件缺少表 [{label}]，或该表的格式无效。")
    return value


def _reject_unknown_keys(data: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = set(data).difference(allowed)
    if unknown:
        names = "、".join(sorted(unknown))
        raise ValueError(f"配置表 {label} 包含无法识别的配置项：{names}")


def _require_string(data: Mapping[str, object], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"配置项 {label} 必须是非空字符串。")
    return value.strip()


def _require_date(data: Mapping[str, object], key: str, label: str) -> date:
    value = data.get(key)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError(f"配置项 {label} 必须是 YYYY-MM-DD 格式的日期。")


def _require_positive_integer(data: Mapping[str, object], key: str, label: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"配置项 {label} 必须是正整数。")
    return value


def _require_non_negative_integer(data: Mapping[str, object], key: str, label: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"配置项 {label} 必须是非负整数。")
    return value


def _require_non_negative_number(data: Mapping[str, object], key: str, label: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"配置项 {label} 必须是非负有限数值。")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"配置项 {label} 必须是非负有限数值。")
    return result


def _load_toml(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到项目配置文件：{path}")
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError:
        raise ValueError(f"项目配置文件不是有效的 TOML：{path}") from None
    except OSError:
        raise RuntimeError(f"无法读取项目配置文件：{path}") from None


def _load_research_config(data: Mapping[str, object]) -> ResearchConfig:
    _reject_unknown_keys(
        data,
        {
            "start_date",
            "end_date",
            "forward_days",
            "ic_sample_step",
            "quantile_count",
            "random_seed",
        },
        "research",
    )
    start = _require_date(data, "start_date", "research.start_date")
    end = _require_date(data, "end_date", "research.end_date")
    if start > end:
        raise ValueError("配置中的研究开始日期不能晚于结束日期。")

    forward_days = _require_positive_integer(data, "forward_days", "research.forward_days")
    ic_sample_step = _require_positive_integer(
        data,
        "ic_sample_step",
        "research.ic_sample_step",
    )
    validate_non_overlapping_sample(forward_days, ic_sample_step)
    quantile_count = _require_positive_integer(data, "quantile_count", "research.quantile_count")
    if quantile_count < 2:
        raise ValueError("配置项 research.quantile_count 不能小于 2。")
    return ResearchConfig(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        forward_days=forward_days,
        ic_sample_step=ic_sample_step,
        quantile_count=quantile_count,
        random_seed=_require_non_negative_integer(data, "random_seed", "research.random_seed"),
    )


def _load_universe_config(data: Mapping[str, object]) -> UniverseConfig:
    _reject_unknown_keys(
        data,
        {
            "symbols",
            "index_code",
            "index_name",
            "rebalance_frequency",
            "snapshot_batch_size",
            "market_fetch_batch_size",
        },
        "universe",
    )
    symbols = data.get("symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols)
    ):
        raise ValueError("配置项 universe.symbols 必须是非空字符串数组。")
    normalized_symbols = tuple(symbol.strip() for symbol in symbols)
    if any(len(symbol) != 6 or not symbol.isdigit() for symbol in normalized_symbols):
        raise ValueError("配置项 universe.symbols 只能包含六位数字股票代码。")
    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ValueError("配置项 universe.symbols 不能包含重复股票代码。")
    index_code = _require_string(data, "index_code", "universe.index_code")
    if len(index_code) != 6 or not index_code.isdigit():
        raise ValueError("配置项 universe.index_code 必须是六位数字指数代码。")
    rebalance_frequency = _require_string(
        data,
        "rebalance_frequency",
        "universe.rebalance_frequency",
    )
    if rebalance_frequency != "ME":
        raise ValueError("当前仅支持按月末调仓，universe.rebalance_frequency 必须为 ME。")
    return UniverseConfig(
        symbols=normalized_symbols,
        index_code=index_code,
        index_name=_require_string(data, "index_name", "universe.index_name"),
        rebalance_frequency=rebalance_frequency,
        snapshot_batch_size=_require_positive_integer(
            data,
            "snapshot_batch_size",
            "universe.snapshot_batch_size",
        ),
        market_fetch_batch_size=_require_positive_integer(
            data,
            "market_fetch_batch_size",
            "universe.market_fetch_batch_size",
        ),
    )


def _load_data_config(data: Mapping[str, object]) -> DataConfig:
    _reject_unknown_keys(
        data,
        {"provider", "research_price_type", "execution_price_type"},
        "data",
    )
    provider = _require_string(data, "provider", "data.provider")
    research_price_type = _require_string(
        data,
        "research_price_type",
        "data.research_price_type",
    )
    execution_price_type = _require_string(
        data,
        "execution_price_type",
        "data.execution_price_type",
    )
    if provider not in {"akshare", "lixinger"}:
        raise ValueError("data.provider 仅支持 akshare 或 lixinger。")
    if research_price_type != "lxr_fc_rights":
        raise ValueError("研究价格必须使用前复权口径 lxr_fc_rights。")
    if execution_price_type != "ex_rights":
        raise ValueError("执行价格必须使用未复权口径 ex_rights。")
    return DataConfig(
        provider=provider,
        research_price_type=research_price_type,
        execution_price_type=execution_price_type,
    )


def _load_portfolio_config(data: Mapping[str, object]) -> PortfolioConfig:
    _reject_unknown_keys(
        data,
        {"top_n", "one_way_cost_rate", "factor_weights"},
        "portfolio",
    )
    factor_table = _require_table(data, "factor_weights", "portfolio.factor_weights")
    if not factor_table or any(
        isinstance(weight, bool) or not isinstance(weight, int | float)
        for weight in factor_table.values()
    ):
        raise ValueError("配置项 portfolio.factor_weights 必须全部是有限数值。") from None
    factor_weights = {factor: float(weight) for factor, weight in factor_table.items()}
    if any(not math.isfinite(weight) for weight in factor_weights.values()):
        raise ValueError("配置项 portfolio.factor_weights 必须包含有限数值。")
    unknown_factors = set(factor_weights).difference(PRICE_FACTOR_COLUMNS)
    if unknown_factors:
        names = "、".join(sorted(unknown_factors))
        raise ValueError(f"配置包含尚未实现的组合因子：{names}")
    if not any(weight != 0 for weight in factor_weights.values()):
        raise ValueError("配置中的组合因子权重不能全部为零。")
    one_way_cost_rate = _require_non_negative_number(
        data,
        "one_way_cost_rate",
        "portfolio.one_way_cost_rate",
    )
    if one_way_cost_rate > 1:
        raise ValueError("配置项 portfolio.one_way_cost_rate 不能大于 1。")
    return PortfolioConfig(
        top_n=_require_positive_integer(data, "top_n", "portfolio.top_n"),
        one_way_cost_rate=one_way_cost_rate,
        factor_weights=MappingProxyType(factor_weights),
    )


def load_project_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path).resolve()
    data = _load_toml(config_path)
    _reject_unknown_keys(
        data,
        {"schema_version", "research", "universe", "data", "portfolio"},
        "根配置",
    )
    schema_version = _require_positive_integer(data, "schema_version", "schema_version")
    if schema_version != 1:
        raise ValueError(f"不支持配置格式版本 {schema_version}，当前仅支持版本 1。")
    return ProjectConfig(
        source_path=config_path,
        schema_version=schema_version,
        research=_load_research_config(_require_table(data, "research", "research")),
        universe=_load_universe_config(_require_table(data, "universe", "universe")),
        data=_load_data_config(_require_table(data, "data", "data")),
        portfolio=_load_portfolio_config(_require_table(data, "portfolio", "portfolio")),
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def serialize_run_config(config: RunConfig) -> str:
    # 将实际生效的运行配置序列化为稳定、可审计的 TOML。
    lines = [
        f"schema_version = {config.schema_version}",
        "",
        "[run]",
        f"mode = {_toml_string(config.mode)}",
    ]
    if config.universe_date is not None:
        lines.append(f"universe_date = {_toml_string(config.universe_date)}")
    lines.extend(
        (
            f"with_preprocess = {str(config.with_preprocess).lower()}",
            f"with_analysis = {str(config.with_analysis).lower()}",
            f"with_evaluation = {str(config.with_evaluation).lower()}",
            f"with_backtest = {str(config.with_backtest).lower()}",
            f"with_execution_backtest = {str(config.with_execution_backtest).lower()}",
            "",
            "[research]",
            f"start_date = {config.research.start_date}",
            f"end_date = {config.research.end_date}",
            f"forward_days = {config.research.forward_days}",
            f"ic_sample_step = {config.research.ic_sample_step}",
            f"quantile_count = {config.research.quantile_count}",
            f"random_seed = {config.research.random_seed}",
            "",
            "[universe]",
            "symbols = ["
            + ", ".join(_toml_string(symbol) for symbol in config.universe.symbols)
            + "]",
            f"index_code = {_toml_string(config.universe.index_code)}",
            f"index_name = {_toml_string(config.universe.index_name)}",
            f"rebalance_frequency = {_toml_string(config.universe.rebalance_frequency)}",
            f"snapshot_batch_size = {config.universe.snapshot_batch_size}",
            f"market_fetch_batch_size = {config.universe.market_fetch_batch_size}",
            "",
            "[data]",
            f"provider = {_toml_string(config.data.provider)}",
            f"research_price_type = {_toml_string(config.data.research_price_type)}",
            f"execution_price_type = {_toml_string(config.data.execution_price_type)}",
            "",
            "[portfolio]",
            f"top_n = {config.portfolio.top_n}",
            f"one_way_cost_rate = {config.portfolio.one_way_cost_rate!r}",
            "",
            "[portfolio.factor_weights]",
        )
    )
    lines.extend(
        f"{factor} = {weight!r}" for factor, weight in config.portfolio.factor_weights.items()
    )
    return "\n".join(lines) + "\n"


PROJECT_CONFIG = load_project_config(CONFIG_PATH)
