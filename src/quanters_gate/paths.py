# 集中管理项目数据目录。

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

UNIVERSE_DIR = DATA_DIR / "universe"

MARKET_DIR = DATA_DIR / "market"
MARKET_RAW_DIR = MARKET_DIR / "raw"
MARKET_RAW_BY_SYMBOL_DIR = MARKET_RAW_DIR / "by_symbol"
MARKET_PROCESSED_DIR = MARKET_DIR / "processed"
MARKET_EXECUTION_DIR = MARKET_DIR / "execution"
MARKET_EXECUTION_BY_SYMBOL_DIR = MARKET_EXECUTION_DIR / "by_symbol"

FACTOR_DIR = DATA_DIR / "factors"
FACTOR_RAW_DIR = FACTOR_DIR / "raw"
FACTOR_PROCESSED_DIR = FACTOR_DIR / "processed"

REPORT_DIR = DATA_DIR / "reports"

PROJECT_DIRECTORIES = (
    UNIVERSE_DIR,
    MARKET_RAW_DIR,
    MARKET_RAW_BY_SYMBOL_DIR,
    MARKET_PROCESSED_DIR,
    MARKET_EXECUTION_DIR,
    MARKET_EXECUTION_BY_SYMBOL_DIR,
    FACTOR_RAW_DIR,
    FACTOR_PROCESSED_DIR,
    REPORT_DIR,
)


def ensure_project_directories() -> None:
    # 创建项目运行所需的全部目录。
    for directory in PROJECT_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
