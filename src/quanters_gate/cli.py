# 定义项目命令行入口。

import argparse
import sys
from collections.abc import Sequence

from quanters_gate.data.akshare import AkShareClient
from quanters_gate.data.lixinger import LixingerClient
from quanters_gate.data.provider import MarketDataProviderFactory
from quanters_gate.settings import PROJECT_CONFIG
from quanters_gate.workflows import execute

PROVIDER_FACTORIES: dict[str, MarketDataProviderFactory] = {
    "akshare": AkShareClient,
    "lixinger": LixingerClient,
}


class ChineseArgumentParser(argparse.ArgumentParser):
    # 提供中文帮助标题和统一的中文参数错误。

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法：", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法：", 1).replace("options:", "选项：", 1)

    def error(self, _message: str) -> None:
        self.print_usage()
        self.exit(2, f"{self.prog}：命令行参数无效，请使用 --help 查看正确用法。\n")


def build_parser() -> argparse.ArgumentParser:
    # 创建带互斥主模式校验的命令行解析器。
    research = PROJECT_CONFIG.research
    universe = PROJECT_CONFIG.universe
    parser = ChineseArgumentParser(description="运行 A 股多因子研究流水线。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument(
        "--symbols", nargs="+", default=list(universe.symbols), help="临时股票代码列表。"
    )

    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--universe-date",
        help=f"使用指定日期的{universe.index_name} 成分快照代替 --symbols。",
    )
    modes.add_argument(
        "--build-universe-history",
        action="store_true",
        help=f"分批构建月末{universe.index_name} 成分历史后退出。",
    )
    modes.add_argument(
        "--build-market-history",
        action="store_true",
        help="分批构建历史成分股的完整复权行情后退出。",
    )
    modes.add_argument(
        "--build-execution-history",
        action="store_true",
        help="分批构建完整未复权执行行情后退出。",
    )
    modes.add_argument(
        "--build-fundamental-history",
        action="store_true",
        help="分批构建历史成分股的财务 point-in-time 面板后退出。",
    )
    modes.add_argument(
        "--run-market-history",
        action="store_true",
        help=f"使用已构建的{universe.index_name} 历史行情面板运行研究。",
    )

    parser.add_argument(
        "--max-universe-snapshots",
        type=int,
        default=universe.snapshot_batch_size,
        help="单次最多获取的缺失月度成分快照数。",
    )
    parser.add_argument(
        "--max-market-symbols",
        type=int,
        default=universe.market_fetch_batch_size,
        help="单次最多获取的缺失股票行情数。",
    )
    parser.add_argument(
        "--max-fundamental-symbols",
        type=int,
        default=universe.market_fetch_batch_size,
        help="单次最多获取的缺失财务股票数。",
    )
    parser.add_argument("--start", default=research.start_date, help="研究开始日期。")
    parser.add_argument("--end", default=research.end_date, help="研究结束日期。")
    parser.add_argument("--horizon", type=int, default=research.forward_days, help="未来收益周期。")
    parser.add_argument("--with-preprocess", action="store_true", help="执行因子预处理。")
    parser.add_argument("--with-analysis", action="store_true", help="执行 Rank IC 分析。")
    parser.add_argument("--with-evaluation", action="store_true", help="执行因子分组收益评估。")
    parser.add_argument(
        "--with-backtest",
        action="store_true",
        help="执行月度 Top N 因子组合研究回测。",
    )
    parser.add_argument(
        "--with-execution-backtest",
        action="store_true",
        help="执行次日开盘且扣除成本的执行口径回测。",
    )
    parser.add_argument(
        "--with-continuous-backtest",
        action="store_true",
        help="执行下一交易日开盘调仓的连续净值研究回测。",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    # 解析命令行参数。
    return build_parser().parse_args(argv)


def provider_factory_for(name: str) -> MarketDataProviderFactory:
    # 在组合根中选择配置指定的数据源实现。
    try:
        return PROVIDER_FACTORIES[name]
    except KeyError:
        raise ValueError(f"不支持的数据源：{name}") from None


def main(argv: Sequence[str] | None = None) -> None:
    # 运行命令行入口。
    try:
        execute(parse_args(argv), provider_factory_for(PROJECT_CONFIG.data.provider))
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1) from None
