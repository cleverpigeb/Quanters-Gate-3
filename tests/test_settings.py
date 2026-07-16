from pathlib import Path

import pytest

from quanters_gate.settings import CONFIG_PATH, PROJECT_CONFIG, load_project_config

VALID_CONFIG = (
    "schema_version = 1\n"
    "\n"
    "[research]\n"
    "start_date = 2020-01-01\n"
    "end_date = 2024-12-31\n"
    "forward_days = 10\n"
    "ic_sample_step = 10\n"
    "quantile_count = 4\n"
    "random_seed = 7\n"
    "\n"
    "[universe]\n"
    'symbols = ["000001", "600000"]\n'
    'index_code = "000905"\n'
    'index_name = "中证 500"\n'
    'rebalance_frequency = "ME"\n'
    "snapshot_batch_size = 6\n"
    "market_fetch_batch_size = 8\n"
    "\n"
    "[data]\n"
    'provider = "lixinger"\n'
    'research_price_type = "lxr_fc_rights"\n'
    'execution_price_type = "ex_rights"\n'
    "\n"
    "[portfolio]\n"
    "top_n = 20\n"
    "one_way_cost_rate = 0.002\n"
    "\n"
    "[portfolio.factor_weights]\n"
    "momentum_20d = 0.7\n"
    "reversal_5d = -0.3\n"
)


def test_default_config_is_loaded_from_config_directory() -> None:
    assert CONFIG_PATH.parts[-2:] == ("config", "default.toml")
    assert PROJECT_CONFIG.source_path == CONFIG_PATH.resolve()


def test_load_project_config_reads_typed_toml_values(tmp_path: Path) -> None:
    config_path = tmp_path / "research.toml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")
    original_content = config_path.read_bytes()
    original_modified_time = config_path.stat().st_mtime_ns

    config = load_project_config(config_path)

    assert config_path.read_bytes() == original_content
    assert config_path.stat().st_mtime_ns == original_modified_time
    assert config.source_path == config_path.resolve()
    assert config.schema_version == 1
    assert config.research.forward_days == 10
    assert config.research.random_seed == 7
    assert config.universe.symbols == ("000001", "600000")
    assert config.universe.index_code == "000905"
    assert config.portfolio.top_n == 20
    assert dict(config.portfolio.factor_weights) == {
        "momentum_20d": 0.7,
        "reversal_5d": -0.3,
    }


def test_load_project_config_rejects_invalid_price_convention(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(
        VALID_CONFIG.replace(
            'research_price_type = "lxr_fc_rights"', 'research_price_type = "normal"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="研究价格必须使用前复权口径"):
        load_project_config(config_path)


def test_load_project_config_accepts_akshare(tmp_path: Path) -> None:
    config_path = tmp_path / "akshare.toml"
    config_path.write_text(
        VALID_CONFIG.replace('provider = "lixinger"', 'provider = "akshare"'), encoding="utf-8"
    )

    assert load_project_config(config_path).data.provider == "akshare"


def test_load_project_config_rejects_malformed_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("[research\n", encoding="utf-8")

    with pytest.raises(ValueError, match="不是有效的 TOML"):
        load_project_config(config_path)


def test_load_project_config_rejects_unknown_schema(tmp_path: Path) -> None:
    config_path = tmp_path / "future.toml"
    config_path.write_text(
        VALID_CONFIG.replace("schema_version = 1", "schema_version = 2"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="当前仅支持版本 1"):
        load_project_config(config_path)


def test_load_project_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "typo.toml"
    config_path.write_text(
        VALID_CONFIG.replace("forward_days = 10", "forward_day = 10"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="无法识别的配置项：forward_day"):
        load_project_config(config_path)
