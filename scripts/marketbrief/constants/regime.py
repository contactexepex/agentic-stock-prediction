"""Constants and messages of the market regime classification (PASDS file 07)."""
REGIME_CALM, REGIME_TRENDING, REGIME_EVENT_HEAVY, REGIME_UNSTABLE = "CALM", "TRENDING", "EVENT_HEAVY", "UNSTABLE"
REGIME_ORDER = [REGIME_CALM, REGIME_TRENDING, REGIME_EVENT_HEAVY, REGIME_UNSTABLE]
MSG_STRESS = "stress: vol index jumped {change} in one day"
MSG_NO_VOL_INDEX = "vol index unavailable: conservative EVENT_HEAVY floor"
MSG_BENCHMARK_INCOMPLETE = "benchmark history incomplete"
MSG_NO_BENCHMARK_TREND = "no benchmark trend data: raised to EVENT_HEAVY"
