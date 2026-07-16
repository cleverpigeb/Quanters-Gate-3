import pytest

from quanters_gate.cli import (
    AkShareClient,
    LixingerClient,
    build_parser,
    main,
    parse_args,
    provider_factory_for,
)
from quanters_gate.settings import PROJECT_CONFIG


def test_primary_modes_are_mutually_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--build-market-history", "--run-market-history"])
    error_output = capsys.readouterr().err

    assert "命令行参数无效" in error_output


def test_help_and_defaults_are_chinese() -> None:
    parser = build_parser()
    help_text = parser.format_help()

    assert "运行 A 股多因子研究流水线" in help_text
    assert "研究开始日期" in help_text
    assert "用法：" in help_text
    assert "选项：" in help_text
    assert "显示帮助信息并退出" in help_text


def test_command_defaults_come_from_toml_config() -> None:
    args = parse_args([])

    assert args.symbols == list(PROJECT_CONFIG.universe.symbols)
    assert args.start == PROJECT_CONFIG.research.start_date
    assert args.end == PROJECT_CONFIG.research.end_date
    assert args.horizon == PROJECT_CONFIG.research.forward_days
    assert args.max_universe_snapshots == PROJECT_CONFIG.universe.snapshot_batch_size
    assert args.max_market_symbols == PROJECT_CONFIG.universe.market_fetch_batch_size


def test_provider_factory_uses_the_configured_provider_registry() -> None:
    assert provider_factory_for("akshare") is AkShareClient
    assert provider_factory_for("lixinger") is LixingerClient


def test_main_rejects_reversed_date_range_in_chinese(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--start", "2024-02-01", "--end", "2024-01-01"])

    assert exit_info.value.code == 1
    assert "开始日期不能晚于结束日期" in capsys.readouterr().err
