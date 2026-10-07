"""Settings, codes and messages of the AI traders, the EOD analyst and the research director (B3; docs/SPEC.md F4,
F6). Research only: a trader's prediction is a paper record, never an order."""
from __future__ import annotations

import re

# ---------- the traders' protocol (F4) ----------
DEADLINE_MINUTES = 15            # a trader not through its gate this long before D's open abstains (timeout)
FUTURE_TOLERANCE_MINUTES = 5     # made_at may run ahead of the gate's clock by this much (clock skew)
MAX_ATTEMPTS = 2                 # the first gate pass plus one retry, then the trader abstains (gate_failed)
REASON_WORDS = 60                # a trader's reason, an abstention's reason, an AI trade reason
MAX_EVIDENCE = 3                 # up to 3 evidence ids per prediction (F4.2)
PROB_DECIMALS = 4
CONF_MIN, CONF_MAX = 0.50, 0.90  # the CLAUDE.md confidence band applies to AI traders (F2.6)
UNSTABLE_CONF_CAP = 0.65         # forecaster.md: in UNSTABLE call only with confidence <= 0.65
REGIME_UNSTABLE = "UNSTABLE"
WIDEN_MAX = 0.5
PRICE_TOLERANCE = 0.005          # a copied or derived price may differ from the stored one by half a cent/paisa
PROB_TOLERANCE = 0.0005
QUALITY_BLOCKED = "BLOCKED"
EARNINGS_DAYS_BLOCK = 1          # no call with days_to_earnings <= 1
WORK_DIR = "traders"             # work/traders/<strategy_id>.jsonl (the trader's file), <strategy_id>.md (input)
METHOD_VERSION = "traders-v1"

# confidence bands of the track-record rule: a band with >= MIN_BAND_TRADES settled trades whose hit rate is below
# the band's lower edge refuses any new confidence inside it (F2.6: lower confidence or abstain)
CONFIDENCE_BANDS: tuple[tuple[float, float], ...] = ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90))
MIN_BAND_TRADES = 20

# evidence ids that are not news: the inputs a trader read (F2.6). `features:<as_of>-<ticker>`,
# `regime:<as_of_date>`, `model_scores:<as_of>-<ticker>-<k>d`
INPUT_PREFIXES = ("features:", "regime:", "model_scores:")
INPUT_FEATURES, INPUT_REGIME, INPUT_MODEL = INPUT_PREFIXES
# per input category of config/strategies.yaml: the evidence-id kinds it lets a trader cite
CITABLE_BY_INPUT = {
    "news": "news", "results": "news", "filings": "news", "events": "news",
    "prices": INPUT_FEATURES, "indicators": INPUT_FEATURES, "sectors": INPUT_FEATURES, "cues": INPUT_REGIME,
    "regime": INPUT_REGIME, "model_score": INPUT_MODEL,
}
CITE_NEWS = "news"

# fields a trader writes (the gate derives every other column from stored data)
PREDICTION_FIELDS = (
    "strategy_id", "ticker", "horizon_days", "direction", "prob_up", "target_price", "range_widen",
    "evidence_ids", "reason", "made_at", "prompt_version", "model_prob", "agent_adjustment", "adjustment_reason",
)
COPYABLE_FIELDS = ("id", "as_of_date", "session_date", "exit_date", "base_close", "lo50", "hi50", "lo80", "hi80",
                   "confidence", "range_id", "model_score_id")
ANCHOR_FIELDS = ("model_prob", "agent_adjustment", "adjustment_reason")
ABSTAIN_FIELDS = ("strategy_id", "ticker", "abstain", "horizons", "reason", "made_at", "prompt_version")

# abstention reason codes (contracts.protocol.ABSTENTION_CODES)
AB_ABSTAINED, AB_GATE_FAILED, AB_TIMEOUT = "abstained", "gate_failed", "timeout"
AB_BLOCKED, AB_EARNINGS, AB_KILLED = "blocked_quality", "earnings_window", "killed"

# ---------- gate codes ----------
CODE_SCHEMA = "TRADER_SCHEMA"              # unknown or missing field, wrong type
CODE_STRATEGY = "TRADER_STRATEGY"          # strategy id of another trader, wrong prompt_version, horizon not its own
CODE_TICKER = "TRADER_TICKER"              # not an active company
CODE_DUPLICATE = "TRADER_DUPLICATE"        # the same id twice in the file
CODE_STORED = "ALREADY_STORED"             # warning: the id is stored already, the line is skipped
CODE_TIME = "TRADER_TIME"                  # made_at not ISO UTC, in the future, after the deadline or before inputs
CODE_TIMEOUT = "TRADER_TIMEOUT"            # the gate ran after the deadline (open - 15 minutes)
CODE_BLOCKED = "QUALITY_BLOCKED"
CODE_EARNINGS = "EARNINGS_WINDOW"
CODE_PROBABILITY = "TRADER_PROBABILITY"    # direction vs prob_up, confidence band, regime cap
CODE_RANGE = "RANGE_NARROWED"              # range edges narrower than ranges.py's, bad range_widen, no range
CODE_NUMBERS = "NUMBERS_MISMATCH"          # a copied or stated number differs from stored data
CODE_TARGET = "TARGET_PRICE"               # target outside the widened 80% range or on the wrong side of C
CODE_EVIDENCE = "EVIDENCE_UNKNOWN"         # invented id, more than 3, an input id of another ticker/day
CODE_LOOKAHEAD = "LOOK_AHEAD"              # evidence, score or range made public after made_at
CODE_BLIND = "BLIND_INPUT"                 # a blind trader cites or states what it must not see
CODE_ANCHOR = "MODEL_ADJUSTMENT"           # the forecast-v11 anchor (combined traders)
CODE_TRACK = "TRACK_RECORD_BAND"           # confidence in a band its own track record does not support
CODE_REASON = "TRADER_REASON"              # reason missing or over 60 words
CODE_NO_RECORD = "NO_RECORD"               # an active company the trader wrote nothing for
CODE_INPUTS = "INPUTS_UNAVAILABLE"         # per-horizon ranges or scores not available (B10 not merged)

MSG_UNKNOWN_FIELD = "unknown field {field!r}"
MSG_MISSING = "missing {field}"
MSG_NOT_TRADER = "strategy_id {strategy_id!r} is not this trader ({want})"
MSG_PROMPT_VERSION = "prompt_version {got!r} is not this trader's {want!r}"
MSG_HORIZON = "horizon_days {horizon!r} is not one of this trader's horizons {horizons}"
MSG_TICKER = "{ticker!r} is not an active company of this market"
MSG_DUPLICATE = "id {id} is repeated in the file"
MSG_STORED = "id {id} is already stored: skipped"
MSG_MADE_AT = "made_at {made_at!r} is not an ISO 8601 UTC timestamp"
MSG_FUTURE = "made_at {made_at} is after the gate's clock {now}"
MSG_AFTER_DEADLINE = "made_at {made_at} is after the deadline {deadline} (D's open {open} - {minutes} min)"
MSG_TIMEOUT = "gate run at {now}, after the deadline {deadline}: every company without a stored prediction abstains"
MSG_BEFORE_INPUT = "made_at {made_at} is before its {what} was published ({published})"
MSG_BLOCKED = "{ticker} indicator quality is BLOCKED: no prediction"
MSG_EARNINGS = "{ticker} has earnings within 1 day (days_to_earnings {days}): no prediction"
MSG_DIRECTION = "direction {direction!r} is not the side of 0.5 that prob_up {prob} is on"
MSG_HALF = "prob_up is 0.5: abstain"
MSG_PROB = "prob_up must be a number between 0 and 1 (got {prob!r})"
MSG_CONFIDENCE = "confidence {confidence} outside {low:.2f}-{high:.2f}"
MSG_UNSTABLE = "regime UNSTABLE: confidence {confidence} above {cap}"
MSG_NO_RANGE = "no published range {range_id} for this session (ranges.py per horizon)"
MSG_RANGE_SESSION = "the range {range_id} is for session {range_session}, not D = {session}"
MSG_WIDEN = "range_widen must be 0-{widen_max} (got {widen!r})"
MSG_NARROWED = "{edge} {given} is narrower than ranges.py's {published}"
MSG_COPY = "{field} {given!r} is not the stored {stored!r}"
MSG_TARGET_BAND = "target_price {target} outside the 80% range {low}-{high}"
MSG_TARGET_SIDE = "target_price {target} is not {side} the as-of close {close} of an {direction} call"
MSG_EVIDENCE_COUNT = "evidence_ids must hold 1-{most} distinct ids (got {count})"
MSG_EVIDENCE_UNKNOWN = "evidence ids not stored: {ids}"
MSG_EVIDENCE_LATE = "evidence published after made_at {made_at}: {ids}"
MSG_INPUT_ID = "input id {id!r} is not {want}"
MSG_BLIND_CITE = "{strategy_id} does not see {kind} and cannot cite {ids}"
MSG_BLIND_FIELD = "{strategy_id} does not see the model score and cannot state {fields}"
MSG_ADJUSTMENT_EVIDENCE = "agent_adjustment {adjustment} needs a news, filing or announcement id the model cannot see"
MSG_SCORE_LATE = "model score {id} was computed at {computed} after made_at {made_at}"
MSG_PROB_SUM = "prob_up {prob} is not model_prob + agent_adjustment = {final}"
MSG_TRACK = ("confidence {confidence} is in band {band}, where this trader's {n} settled trades hit {rate:.0%} "
             "(< {low:.0%}): lower the confidence below the band or abstain")
MSG_REASON = "reason must be text of 1-{words} words (got {count})"
MSG_NO_RECORD = "no prediction and no abstention for {ticker}"
MSG_HORIZON_TWICE = "{ticker} N+{horizon} is both predicted and abstained"
MSG_INPUTS = "per-horizon ranges or model scores are not available yet ({detail}): run after session B10 merges"
MSG_KILLED = "kill switch: {strategy_id} is disabled in {path}"

# ---------- EOD analyst (F6.1) ----------
EOD_PROMPT_VERSION = "eod-v1"
EOD_SUMMARY_WORDS = 150
BIGGEST_COUNT = 5
EOD_FACTS_FILE = "eod_facts.json"
EOD_AGENT_FILE = "eod_analysis.jsonl"
KIND_HEAD_TO_HEAD, KIND_WIN, KIND_MISS = "head_to_head", "biggest_win", "biggest_miss"
TYPE_SUMMARY = "summary"
EOD_REASON_FIELDS = ("id", "trade_id", "kind", "text", "cited_ids", "prompt_version")
EOD_SUMMARY_FIELDS = ("type", "summary", "cited_ids", "prompt_version")
# words the analyst's text may not use: it explains settled paper trades, it never advises or forecasts
ADVICE_WORDS = re.compile(
    r"\b(recommend\w*|advis\w*|should|you (?:can|could|may|might)|consider (?:buying|selling)|buy now|sell now|"
    r"go long|go short|strong buy|strong sell|outperform|underperform|overweight|underweight|price target|"
    r"will (?:rise|fall|rally|drop|gain|lose|go up|go down|recover|rebound))\b",
    re.I,
)
NUMBER = re.compile(r"(?<![\w.])([+\-−]?)(\d[\d,]*(?:\.\d+)?)(\s?%)?")
ID_TOKEN = re.compile(r"\b(?:acc|h2h|tra|nse-ann|ni|rr|eod)[:\-][\w:.\-@]+|\b[0-9a-f]{16}\b|\b\d{10}-\d{2}-\d{6}\b")
DATE_TOKEN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MSG_EOD_UNKNOWN_TRADE = "trade_id {trade_id!r} is not one the analyst was asked to explain as {kind}"
MSG_EOD_ID = "id {got!r} must be {want!r}"
MSG_EOD_MISSING = "no reason for {trade_id} ({kind})"
MSG_EOD_TWICE = "{trade_id} ({kind}) explained twice"
MSG_EOD_WORDS = "{what} must be 1-{words} words (got {count})"
MSG_EOD_CITE_TRADE = "cited_ids must start with the trade id {trade_id}"
MSG_EOD_CITE_UNKNOWN = "cited ids not among the trade's id and verified news ids: {ids}"
MSG_EOD_TEXT_ID = "ids named in the text but not cited: {ids}"
MSG_EOD_NUMBER = "numbers that match none of the stored facts: {numbers}"
MSG_EOD_SIGN = "{number}% has the wrong sign for {what} {value}"
MSG_EOD_ADVICE = "text must not advise or forecast (found {word!r})"
MSG_EOD_ENUM = "{field} {value!r} not one of {allowed}"
MSG_EOD_SUMMARY = "exactly one summary line is required (got {count})"
MSG_EOD_PROMPT = "prompt_version must be {want!r}"
MSG_EOD_STORED = "{id} is already stored"

# ---------- research director (F6.2) ----------
DIRECTOR_PROMPT_VERSION = "director-v1"
DIRECTOR_AGENT_FILE = "research_review.json"
PROPOSAL_KINDS = ("new_strategy_version", "weight", "threshold")
PROPOSAL_FILES = ("config/strategies.yaml", "config/model.yaml", "config/ranges.yaml", "config/costs.yaml")
PROPOSAL_STATUS = "proposed"
FINDING_WORDS = 60
RATIONALE_WORDS = 80
MSG_DIRECTOR_FILE = "proposal {pid}: file {file!r} is not one of {allowed}"
MSG_DIRECTOR_DIFF = "proposal {pid}: the diff does not apply to {file} as it is now ({detail})"
MSG_DIRECTOR_FIELD = "{where}: missing or bad {field}"
MSG_DIRECTOR_CITE = "{where}: cited ids not in the week's inputs: {ids}"
MSG_DIRECTOR_ID = "proposal_id {got!r} must be {want!r}"
MSG_DIRECTOR_WORDS = "{where}: text must be 1-{words} words (got {count})"
MSG_DIRECTOR_NEW_ID = "proposal {pid}: a changed strategy needs a new id (an id's behaviour never changes): {ids}"
