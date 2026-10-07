"""Kinds, enums, ids and messages of the intraday checks (WS5)."""

KIND_INTRADAY_CHECKS = "intraday_checks"
KIND_INTRADAY_RUNS = "intraday_runs"
KIND_INTRADAY_EXPLANATIONS = "intraday_explanations"

FILE_INTRADAY_CONFIG = "intraday.yaml"
METHOD_VERSION = "intraday-v1"
CHECK_ID_PREFIX = "ic"
EXPLANATION_ID_PREFIX = "ix"
PAPER_ONLY = "Paper only — no proven edge yet"

# run status (one intraday_runs row per check time)
RUN_OK = "ok"
RUN_MARKET_CLOSED = "market_closed"
RUN_STALE = "stale"

# per-ticker data quality
QUALITY_OK = "ok"
QUALITY_STALE = "stale_quote"
QUALITY_NO_QUOTE = "no_quote"

# band position of the last price
BAND_BELOW80, BAND_BELOW50, BAND_INSIDE50 = "below80", "below50", "inside50"
BAND_ABOVE50, BAND_ABOVE80 = "above50", "above80"

# flags
FLAG_OUTSIDE_1D_80 = "outside_1d_80"
FLAG_OUTSIDE_1D_50 = "outside_1d_50"
FLAG_OUTSIDE_5D_80 = "outside_5d_80"
FLAG_LARGE_MOVE = "large_move"
FLAG_LARGE_RESIDUAL = "large_residual"
FLAG_AGAINST_CALL = "against_call"
FLAG_AGAINST_MODEL = "against_model"
ALL_FLAGS = (
    FLAG_OUTSIDE_1D_80, FLAG_OUTSIDE_1D_50, FLAG_OUTSIDE_5D_80, FLAG_LARGE_MOVE, FLAG_LARGE_RESIDUAL,
    FLAG_AGAINST_CALL, FLAG_AGAINST_MODEL,
)

# attribution candidate kinds and their id prefixes (news, announcement and event ids are the stored ids)
CAND_BENCHMARK = "benchmark"
CAND_SECTOR = "sector"
CAND_CUE = "cue"
CAND_NEWS = "news"
CAND_ANNOUNCEMENT = "announcement"
CAND_EVENT = "event"
CAND_PREFIX = {CAND_BENCHMARK: "bench:", CAND_SECTOR: "sector:", CAND_CUE: "cue:"}
SECTOR_SOURCE_ETF = "sector_etf"
SECTOR_SOURCE_PEERS = "peers"
EVENT_TYPES = ("earnings", "ex_dividend")
NEWS_SINCE_OPEN, NEWS_SINCE_PREV_CLOSE = "open", "prev_close"

# call sources
CALL_PREDICTION = "prediction"
CALL_MODEL = "model"

# the explainer's attribution enum: a candidate kind, or no candidate fits
ATTRIBUTION_IDIOSYNCRATIC = "idiosyncratic"
ATTRIBUTION_UNEXPLAINED = "unexplained"
ATTRIBUTIONS = (
    CAND_BENCHMARK, CAND_SECTOR, CAND_CUE, CAND_NEWS, CAND_ANNOUNCEMENT, CAND_EVENT,
    ATTRIBUTION_IDIOSYNCRATIC, ATTRIBUTION_UNEXPLAINED,
)
EXPLAINER_FIELDS = ("check_row_id", "text", "cited_ids", "attribution", "prompt_version")

# learning loop
OUTCOME_HELD, OUTCOME_REVERSED, OUTCOME_FADED, OUTCOME_PENDING = "held", "reversed", "faded", "pending"

# words that would make a note a prediction or a trade instruction (checked case-insensitively)
FORBIDDEN_WORDS_RE = (
    r"\b(buy|buying|sell(?!-off)|selling|will|should|expect\w*|recommend\w*|predict\w*|forecast\w*|"
    r"target|likely to|going to|could|might|stop[- ]loss)\b"
)
NUM_RE = r"([+\-−]?)(\d[\d,]*(?:\.\d+)?)(\s?%)?"
SKIP_RE = r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.+Z\-]+)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b"

MSG_MARKET_CLOSED = "market closed at {check_at} (session {session})"
MSG_ALREADY_CHECKED = "check {check_id} already stored; nothing written"
MSG_NOT_A_JSON_OBJECT = "not a JSON object"
MSG_UNKNOWN_FIELD = "unknown field {key!r}"
MSG_MISSING_FIELD = "missing {key}"
MSG_NOT_TEXT = "{key} must be text"
MSG_NOT_LIST = "cited_ids must be a list of ids"
MSG_UNKNOWN_ROW = "check row {row_id} is not a stored flagged check row"
MSG_ALREADY_EXPLAINED = "check row {row_id} already has a stored explanation"
MSG_DUPLICATE_IN_FILE = "check row {row_id} appears twice in the file"
MSG_WORD_COUNT = "text must be 1-{max_words} words (has {word_count})"
MSG_ID_NOT_CANDIDATE = "cited id {cited!r} is not an attribution candidate of this check row"
MSG_NEEDS_CITATION = "attribution {attribution} needs at least one cited id of that kind"
MSG_BAD_ATTRIBUTION = "attribution {attribution!r} is not one of {allowed}"
MSG_NUMBER_MATCHES_NOTHING = "number {sign}{num}{unit} matches no stored measure of this row"
MSG_WRONG_SIGN = "signed number {sign}{num}{unit} has the wrong sign (stored {what} {value:+.4f})"
MSG_FORBIDDEN_WORD = "text predicts or recommends ({word!r}); describe only what happened"
MSG_PROMPT_VERSION = "prompt_version {found!r} is not the configured {expected!r}"
MSG_PATH_DOES_NOT_EXIST = "{path} does not exist"
