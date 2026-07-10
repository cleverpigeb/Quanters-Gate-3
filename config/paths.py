from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

MARKET_DIR = DATA_DIR / "market"
MARKET_RAW_DIR = MARKET_DIR / "raw"
MARKET_PROCESSED_DIR = MARKET_DIR / "processed"

FACTOR_DIR = DATA_DIR / "factors"
FACTOR_RAW_DIR = FACTOR_DIR / "raw"
FACTOR_PROCESSED_DIR = FACTOR_DIR / "processed"

REPORT_DIR = DATA_DIR / "reports"


def ensure_project_directories() -> None:
    for directory in (
        MARKET_RAW_DIR,
        MARKET_PROCESSED_DIR,
        FACTOR_RAW_DIR,
        FACTOR_PROCESSED_DIR,
        REPORT_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
