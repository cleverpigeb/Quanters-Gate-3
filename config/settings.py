DEFAULT_START_DATE = "2021-01-01"
DEFAULT_END_DATE = "2026-06-30"
DEFAULT_UNIVERSE = ("000001", "000002", "000063", "000333", "600000")

INITIAL_UNIVERSE_INDEX = "000300"
INITIAL_UNIVERSE_NAME = "CSI 300"
MIN_LISTING_DAYS = 60
REBALANCE_FREQUENCY = "ME"
UNIVERSE_SNAPSHOT_BATCH_SIZE = 12

LIXINGER_INDEX_CONSTITUENTS_URL = "https://open.lixinger.com/api/cn/index/constituents"
LIXINGER_INDEX_CANDLESTICK_URL = "https://open.lixinger.com/api/cn/index/candlestick"
LIXINGER_COMPANY_CANDLESTICK_URL = "https://open.lixinger.com/api/cn/company/candlestick"
LIXINGER_RESEARCH_PRICE_TYPE = "lxr_fc_rights"
LIXINGER_EXECUTION_PRICE_TYPE = "ex_rights"

FORWARD_DAYS = 20
IC_SAMPLE_STEP = 20
QUANTILE_COUNT = 5

PRICE_FACTOR_COLUMNS = (
    "momentum_20d",
    "reversal_5d",
    "volatility_20d",
    "turnover_proxy_20d",
)
