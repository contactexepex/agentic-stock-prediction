"""Names, feature groups, labels and messages of the signal model (marketbrief/model; docs/DESIGN.md section 15)."""

# ---------- data kinds and files ----------
KIND_MODEL_SCORES = "model_scores"
KIND_MODEL_VERSIONS = "model_versions"
KIND_AGENT_REASONING = "agent_reasoning"
FILE_MODEL_CONFIG = "model.yaml"
FILE_COSTS_CONFIG = "costs.yaml"
FILE_REASONING_WORK = "reasoning.jsonl"

# ---------- label conventions (the owner's trade: buy at an open, sell at a close) ----------
LABEL_OPEN_TO_CLOSE = "open_to_close"     # primary: open of D -> close of D + (h == 1 ? 1 : h - 1)
LABEL_CLOSE_TO_CLOSE = "close_to_close"   # secondary: as-of close -> close of the h-th session after it
LABEL_CONVENTIONS = (LABEL_OPEN_TO_CLOSE, LABEL_CLOSE_TO_CLOSE)
LABEL_DESCRIPTIONS = {
    LABEL_OPEN_TO_CLOSE: "buy at the open of D (the first session after the as-of close), sell at the close of "
                         "D+1 (1-day) or D+4 (5-day)",
    LABEL_CLOSE_TO_CLOSE: "as-of close to the close of the h-th session after it (D for 1-day, D+4 for 5-day)",
}
HORIZONS = (1, 5)

# ---------- feature names and groups ----------
TECHNICAL_FEATURES = ("ret_1d", "ret_3d", "ret_5d", "ret_20d", "roc_10", "ema_ratio", "price_vs_20d_high",
                      "rsi_14", "atr_pct", "realized_vol_10d", "ewma_vol", "bb_width", "obv_trend",
                      "volume_ratio_20d", "beta_1y", "rel_sector_5d")
MARKET_FEATURES = ("bench_ret_5d", "bench_vol_10d", "vol_level", "vol_change_1d", "cue_ret_1d")
REGIME_FEATURES = ("regime_calm", "regime_trending", "regime_event_heavy", "regime_unstable")
EVENT_FEATURES = ("earnings_in_window", "ex_dividend_in_window")
FLOW_FEATURES = {"india": ("fii_net_cr", "dii_net_cr", "fpi_equity_net_cr"),
                 "us": ("insider_net_30d", "short_volume_pct")}
GROUP_MOMENTUM, GROUP_OSCILLATOR, GROUP_VOLATILITY = "momentum", "oscillator", "volatility"
GROUP_VOLUME, GROUP_RELATIVE, GROUP_MARKET = "volume", "relative strength", "market"
GROUP_REGIME, GROUP_EVENTS, GROUP_FLOWS, GROUP_NEWS = "regime", "events", "flows", "news"
GROUP_BASELINE = "baseline"
FEATURE_GROUPS = {
    **{f: GROUP_MOMENTUM for f in ("ret_1d", "ret_3d", "ret_5d", "ret_20d", "roc_10", "ema_ratio",
                                   "price_vs_20d_high")},
    "rsi_14": GROUP_OSCILLATOR,
    **{f: GROUP_VOLATILITY for f in ("atr_pct", "realized_vol_10d", "ewma_vol", "bb_width")},
    "obv_trend": GROUP_VOLUME, "volume_ratio_20d": GROUP_VOLUME,
    "beta_1y": GROUP_RELATIVE, "rel_sector_5d": GROUP_RELATIVE,
    **{f: GROUP_MARKET for f in MARKET_FEATURES},
    **{f: GROUP_REGIME for f in REGIME_FEATURES},
    **{f: GROUP_EVENTS for f in EVENT_FEATURES},
    **{f: GROUP_FLOWS for fs in FLOW_FEATURES.values() for f in fs},
}
REGIME_COLUMNS = {"CALM": "regime_calm", "TRENDING": "regime_trending", "EVENT_HEAVY": "regime_event_heavy",
                  "UNSTABLE": "regime_unstable"}

# ---------- plain-language driver text: feature -> (label, kind of value) ----------
VALUE_PERCENT, VALUE_LEVEL, VALUE_PLAIN, VALUE_FLAG = "percent", "level_percent", "plain", "flag"
FEATURE_TEXT = {
    "ret_1d": ("1-day return", VALUE_PERCENT), "ret_3d": ("3-day return", VALUE_PERCENT),
    "ret_5d": ("5-day return", VALUE_PERCENT), "ret_20d": ("20-day return", VALUE_PERCENT),
    "roc_10": ("10-day rate of change", VALUE_PERCENT), "ema_ratio": ("EMA 9/21 ratio", VALUE_PLAIN),
    "price_vs_20d_high": ("close vs 20-day high", VALUE_PLAIN), "rsi_14": ("RSI", VALUE_PLAIN),
    "atr_pct": ("ATR", VALUE_LEVEL), "realized_vol_10d": ("10-day realized vol", VALUE_LEVEL),
    "ewma_vol": ("EWMA vol", VALUE_LEVEL), "bb_width": ("Bollinger width", VALUE_LEVEL),
    "obv_trend": ("OBV 5-day trend", VALUE_PLAIN), "volume_ratio_20d": ("volume vs 20-day average", VALUE_PLAIN),
    "beta_1y": ("beta", VALUE_PLAIN), "rel_sector_5d": ("5-day return vs sector peers", VALUE_PERCENT),
    "bench_ret_5d": ("benchmark 5-day return", VALUE_PERCENT), "bench_vol_10d": ("benchmark 10-day vol", VALUE_LEVEL),
    "vol_level": ("vol index", VALUE_PLAIN), "vol_change_1d": ("vol index 1-day change", VALUE_PERCENT),
    "cue_ret_1d": ("overnight cue (index cue's last daily return)", VALUE_PERCENT),
    "regime_calm": ("regime CALM", VALUE_FLAG), "regime_trending": ("regime TRENDING", VALUE_FLAG),
    "regime_event_heavy": ("regime EVENT_HEAVY", VALUE_FLAG), "regime_unstable": ("regime UNSTABLE", VALUE_FLAG),
    "earnings_in_window": ("earnings inside the holding window", VALUE_FLAG),
    "ex_dividend_in_window": ("ex-dividend inside the holding window", VALUE_FLAG),
    "fii_net_cr": ("FII net cash flow (Rs cr)", VALUE_PLAIN), "dii_net_cr": ("DII net cash flow (Rs cr)", VALUE_PLAIN),
    "fpi_equity_net_cr": ("NSDL FPI equity net (Rs cr)", VALUE_PLAIN),
    "insider_net_30d": ("insider net buying, 30 days (signed log USD)", VALUE_PLAIN),
    "short_volume_pct": ("FINRA short-volume share", VALUE_PLAIN),
}
RSI_OVERSOLD, RSI_NEAR_OVERSOLD, RSI_NEAR_OVERBOUGHT, RSI_OVERBOUGHT = 30.0, 40.0, 60.0, 70.0
TEXT_OVERSOLD, TEXT_NEAR_OVERSOLD = "oversold", "near oversold"
TEXT_NEAR_OVERBOUGHT, TEXT_OVERBOUGHT = "near overbought", "overbought"
TEXT_NEWS = "verified news score {score:+.2f} ({n} item(s))"
TEXT_BASELINE = "model baseline vs base rate"
DRIVER_TEMPLATE = "{text}: {points:+.1f} pts"
TOP_DRIVERS = 3
DRIVER_MIN_POINTS = 0.05   # drivers smaller than this many points are not listed

# ---------- news prior (not trainable yet: no historical news archive) ----------
NEWS_STATUS_WEIGHTS_KEY = "status_weights"
NEWS_MATERIALITY_KEY = "materiality_weights"

# ---------- messages ----------
MSG_NO_MODEL_CONFIG = "config/{name} is missing (the signal model's settings; docs/DESIGN.md section 15)"
MSG_TOO_LITTLE_HISTORY = "not enough resolved labels by {cutoff} to train ({sessions} sessions, need {need})"
MSG_SCORE_STALE = "{ticker}: newest bar {last} is older than the as-of date {as_of}; no score"
MSG_EXCLUDED_COVERAGE = "coverage {share:.0%} in the training rows < {need:.0%}"
MSG_EXCLUDED_CONSTANT = "no variation in the training rows"
MSG_NEWS_NOT_TRAINED = "news: fixed prior weights (not trained: no historical news archive)"
MSG_GBM_SKIPPED = "gradient boosting comparison skipped: scikit-learn is not installed"

# ---------- forecast gate codes (validate.py --stage forecast) ----------
CODE_MODEL_ADJUSTMENT = "MODEL_ADJUSTMENT"
CODE_MODEL_SCORE_MISSING = "MODEL_SCORE_MISSING"
MAX_AGENT_ADJUSTMENT = 0.10
CONFIDENCE_TOLERANCE = 0.005
MODEL_PROB_TOLERANCE = 0.0005

MSG_ANCHOR_UNEXPECTED = "model_prob given but no model score is stored for this id"
MSG_ANCHOR_MISSING = "model_prob missing: the stored model score is {stored}"
MSG_ANCHOR_MISMATCH = "model_prob {given} is not the stored model score {stored}"
MSG_ADJUSTMENT_MISSING = "agent_adjustment missing (0 when the model probability is kept)"
MSG_ADJUSTMENT_TOO_LARGE = "|agent_adjustment| {size} above {cap}"
MSG_REASON_MISSING = "adjustment_reason is required when agent_adjustment is not 0"
MSG_FINAL_HALF = "final probability is 0.5: abstain"
MSG_DIRECTION_SIDE = "direction {direction} disagrees with the final probability of up {final:.4f}"
MSG_CONFIDENCE_IMPLIED = "confidence {confidence} is not max(final, 1 - final) = {implied:.4f}"
MSG_SCORE_MISSING_WARNING = ("line {line} ({id}): no model score stored for this id by made_at: checked without "
                             "the model anchor")
MSG_LINE_PREFIX = "line {line} ({id}): "

# ---------- agent reasoning (scripts/agent_reasoning.py) ----------
REASONING_CASE_WORDS = 80
REASONING_VERDICT_WORDS = 60
REASONING_DECISIONS = ("up", "down", "abstain")
MSG_REASONING_DUPLICATE = "id {id} already stored"
MSG_REASONING_TEXT = "{name} must be text of 1-{limit} words"
MSG_REASONING_DECISION = "decision_{horizon}d must be one of {choices}"
MSG_REASONING_IDS = "{name} must be a list of ids"
MSG_REASONING_UNKNOWN_EVIDENCE = "evidence ids not stored: {ids}"
MSG_REASONING_LATE_EVIDENCE = "evidence published after made_at: {ids}"
MSG_REASONING_NOT_A_CALL = "prediction {id} is not a stored call of {ticker} as of {as_of}"
MSG_REASONING_NO_CALL = "decision_{horizon}d {decision} has no stored {decision} call {call_id} in prediction_ids"
MSG_REASONING_ABSTAIN_LISTED = "decision_{horizon}d abstain but {call_id} is listed"
MSG_REASONING_NOT_OBJECT = "not a JSON object"
MSG_REASONING_UNKNOWN_FIELD = "unknown field {name!r}"
MSG_REASONING_MISSING_FIELD = "missing {name}"
MSG_REASONING_TICKER = "unknown ticker {ticker!r}"
MSG_REASONING_AS_OF = "as_of_date {given} is not the latest feature date {want}"
MSG_REASONING_ID = "id must be <as_of_date>-<ticker> = {want}"
MSG_REASONING_MADE_AT = "made_at {given!r} is not a timestamp up to now"
MSG_REASONING_NOT_JSON = "not JSON ({error})"

# ---------- backtest verdicts ----------
MSG_VERDICT_SCORES = "{market} {key}: Brier {brier} vs base rate {base} (skill {skill}), AUC {auc} (95% {auc95})"
MSG_VERDICT_NO_POSITIONS = "  p>={threshold}: no long positions (no stock-day reached the threshold)"
MSG_VERDICT_VS = ("  p>={threshold} long ({positions} positions) {word} {name} after costs: {mean}% per date, "
                  "95% [{low}, {high}]")
VERDICT_BEATS, VERDICT_WORSE, VERDICT_SAME = "beats", "is worse than", "is not distinguishable from"
MIN_VERDICT_DATES = 20   # fewer common dates than this: no verdict (the interval would mean nothing)
MSG_VERDICT_TOO_FEW = "  p>={threshold} vs {name}: {dates} common date(s), fewer than {need}: no verdict"
