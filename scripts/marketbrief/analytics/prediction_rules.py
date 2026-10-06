"""The CLAUDE.md prediction rules as one record check, shared by the daily gate
(validate.py --stage forecast) and the as-of replay (ai_replay.py record), and the news-verification
rules on the cited evidence (check_news_status; the daily gate only)."""

from __future__ import annotations

from typing import NamedTuple

from marketbrief.constants.prediction_rules import (
    CONF_MAX,
    CONF_MIN,
    DEFAULT_AS_OF_LABEL,
    DEFAULT_EVIDENCE_LABEL,
    HORIZONS,
    RATIONALE_WORDS,
    REQUIRED,
    WIDEN_MAX,
)
from marketbrief.constants.verification import (
    CODE_NEWS_STATUS_BLOCKED,
    CODE_NEWS_STATUS_CONFIDENCE,
    CODE_NEWS_STATUS_CONTRADICTED,
    CODE_NEWS_STATUS_MAIN,
    MAIN_EVIDENCE_STATUSES,
    NEVER_SUPPORT_STATUSES,
    WEAK_CONFIDENCE_PENALTY,
    WEAK_STATUSES,
    WIDEN_ONLY_STATUSES,
)
from marketbrief.core.schemas import SCHEMAS
from marketbrief.utils.timefmt import as_utc_timestamp
from marketbrief.constants.prediction_rules import (
    MSG_AS_OF_DATE_IS_NOT,
    MSG_CONFIDENCE_MUST_BE_GOT,
    MSG_DIRECTION_MUST_BE_UP_OR_DOWN,
    MSG_EVIDENCE_IDS_NOT_IN,
    MSG_EVIDENCE_PUBLISHED_AFTER_MADE_AT,
    MSG_HAS_EARNINGS_WITHIN_1_DAY_DAYS,
    MSG_HORIZON_DAYS_MUST_BE_1_OR,
    MSG_ID_ALREADY_RECORDED,
    MSG_ID_MUST_BE_AS_OF_DATE,
    MSG_INDICATOR_QUALITY_IS_BLOCKED,
    MSG_MADE_AT_IS_NOT_A_TIMESTAMP,
    MSG_MISSING,
    MSG_PROMPT_VERSION_MUST_BE_TEXT,
    MSG_RANGE_WIDEN_MUST_BE_0_GOT,
    MSG_RATIONALE_MUST_BE_TEXT_OF_AT,
    MSG_UNKNOWN_TICKER,
)


class RuleLabels(NamedTuple):
    """How the messages name the required as-of date and the evidence source (the replay words them differently)."""

    as_of: str = DEFAULT_AS_OF_LABEL
    evidence: str = DEFAULT_EVIDENCE_LABEL


def identity_errors(rec: dict, ctx: dict, seen: set[str], want, as_of, label: str) -> list[str]:
    """Ticker, horizon, as_of_date and id rules."""
    errs = []
    ticker, horizon = rec["ticker"], rec["horizon_days"]
    if ticker not in ctx["tickers"]:
        errs.append(MSG_UNKNOWN_TICKER.format(ticker=ticker))
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon not in HORIZONS:
        errs.append(MSG_HORIZON_DAYS_MUST_BE_1_OR.format(horizon=horizon))
    if as_of is not None and str(rec["as_of_date"]) != str(want):
        errs.append(MSG_AS_OF_DATE_IS_NOT.format(as_of_date=rec["as_of_date"], label=label, want=want))
    if rec["id"] != f"{rec['as_of_date']}-{ticker}-{horizon}d":
        errs.append(
            MSG_ID_MUST_BE_AS_OF_DATE.format(as_of_date=rec["as_of_date"], ticker=ticker, horizon=horizon, id=rec["id"])
        )
    if rec["id"] in seen:
        errs.append(MSG_ID_ALREADY_RECORDED.format(id=rec["id"]))
    return errs


def value_errors(rec: dict) -> list[str]:
    """Direction, confidence, range_widen and rationale rules."""
    errs = []
    if rec["direction"] not in ("up", "down"):
        errs.append(MSG_DIRECTION_MUST_BE_UP_OR_DOWN.format(direction=rec["direction"]))
    c = rec["confidence"]
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not (CONF_MIN <= c <= CONF_MAX):
        errs.append(MSG_CONFIDENCE_MUST_BE_GOT.format(conf_min=CONF_MIN, conf_max=CONF_MAX, c=c))
    w = rec.get("range_widen")
    if w is not None and (not isinstance(w, (int, float)) or isinstance(w, bool) or not 0 <= w <= WIDEN_MAX):
        errs.append(MSG_RANGE_WIDEN_MUST_BE_0_GOT.format(widen_max=WIDEN_MAX, w=w))
    if not isinstance(rec["rationale"], str) or len(rec["rationale"].split()) > RATIONALE_WORDS:
        errs.append(MSG_RATIONALE_MUST_BE_TEXT_OF_AT.format(rationale_words=RATIONALE_WORDS))
    return errs


def evidence_errors(rec: dict, ctx: dict, made, label: str) -> list[str]:
    """The cited evidence ids exist and (with public times) were public by made_at."""
    ids = rec["evidence_ids"]
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
        return ["evidence_ids must be a non-empty list of ids"]
    errs = []
    unknown = [x for x in ids if x not in ctx["evidence"]]
    if unknown:
        errs.append(MSG_EVIDENCE_IDS_NOT_IN.format(label=label, unknown=unknown))
    if isinstance(ctx["evidence"], dict) and made is not None:
        late = [x for x in ids if ctx["evidence"].get(x) is not None and ctx["evidence"][x] > made]
        if late:
            errs.append(MSG_EVIDENCE_PUBLISHED_AFTER_MADE_AT.format(isoformat=made.isoformat(), late=late))
    return errs


def feature_errors(ctx: dict, ticker: str, want) -> list[str]:
    """No call for a ticker without an indicator snapshot, with BLOCKED quality or earnings within a day."""
    features = ctx["features"].get(ticker)
    if ticker not in ctx["tickers"]:
        return []
    if features is None:
        return [f"no indicator snapshot for {ticker}" + (f" on {want}" if want is not None else "")]
    errs = []
    if features["quality"] == "BLOCKED":
        errs.append(MSG_INDICATOR_QUALITY_IS_BLOCKED.format(ticker=ticker))
    if features["days_to_earnings"] is not None and features["days_to_earnings"] <= 1:
        errs.append(
            MSG_HAS_EARNINGS_WITHIN_1_DAY_DAYS.format(ticker=ticker, days_to_earnings=features["days_to_earnings"])
        )
    return errs


def check_prediction(
    rec, ctx: dict, seen: set[str], as_of=None, require_made_at: bool = False, labels: RuleLabels | None = None
) -> list[str]:
    """Reasons a forecaster record breaks the schema or the CLAUDE.md prediction rules (empty = valid).

    ctx: `tickers` (watchlist), `features` {ticker: {quality, days_to_earnings}}, `evidence`
    (citable ids: a set, or a dict id -> when it became public; with a dict, each cited id must
    be public by the record's made_at). as_of: the required as_of_date, one date for every ticker
    or a dict ticker -> date (the latest price date in the context pack). seen: ids already stored."""
    if not isinstance(rec, dict):
        return ["not a JSON object"]
    labels = labels or RuleLabels()
    cols = SCHEMAS["predictions"][1]
    errs = [f"unknown field {k!r}" for k in rec if k not in cols]
    for k in REQUIRED + (("made_at",) if require_made_at else ()):
        if rec.get(k) in (None, ""):
            errs.append(MSG_MISSING.format(k=k))
    if errs:
        return errs
    ticker = rec["ticker"]
    want = as_of.get(ticker) if isinstance(as_of, dict) else as_of
    errs += identity_errors(rec, ctx, seen, want, as_of, labels.as_of)
    errs += value_errors(rec)
    made = None
    if rec.get("made_at") is not None:
        made = as_utc_timestamp(rec["made_at"])
        if made is None:
            errs.append(MSG_MADE_AT_IS_NOT_A_TIMESTAMP.format(made_at=rec["made_at"]))
    errs += evidence_errors(rec, ctx, made, labels.evidence)
    if not isinstance(rec["prompt_version"], str):
        errs.append(MSG_PROMPT_VERSION_MUST_BE_TEXT)
    return errs + feature_errors(ctx, ticker, want)


def check_news_status(rec: dict, statuses: list[str]) -> list[tuple[str, str]]:
    """(code, reason) for each news-verification rule a valid record breaks (forecaster.md; empty = ok).
    statuses: the status of each of rec["evidence_ids"] as of its made_at (evidence_status.py). The
    first id is the main evidence: confirmed_primary or corroborated. rumour and promotional ids never
    support a call; a contradicted id only with range_widen > 0; citing a single_source or unverified
    id caps the confidence at CONF_MAX - 0.05."""
    ids, out = rec["evidence_ids"], []
    if statuses[0] not in MAIN_EVIDENCE_STATUSES:
        out.append(
            (
                CODE_NEWS_STATUS_MAIN,
                f"main evidence {ids[0]} is {statuses[0]}; it must be {' or '.join(MAIN_EVIDENCE_STATUSES)}",
            )
        )
    blocked = [f"{i} ({s})" for i, s in zip(ids, statuses, strict=False) if s in NEVER_SUPPORT_STATUSES]
    if blocked:
        out.append((CODE_NEWS_STATUS_BLOCKED, f"evidence that cannot support a call: {', '.join(blocked)}"))
    contradicted = [i for i, s in zip(ids, statuses, strict=False) if s in WIDEN_ONLY_STATUSES]
    if contradicted and not (rec.get("range_widen") or 0) > 0:
        out.append(
            (
                CODE_NEWS_STATUS_CONTRADICTED,
                f"contradicted evidence {contradicted} may only be cited to widen the range (range_widen > 0)",
            )
        )
    weak = [f"{i} ({s})" for i, s in zip(ids, statuses, strict=False) if s in WEAK_STATUSES]
    cap = round(CONF_MAX - WEAK_CONFIDENCE_PENALTY, 2)
    if weak and rec["confidence"] > cap + 1e-9:
        out.append(
            (
                CODE_NEWS_STATUS_CONFIDENCE,
                f"confidence {rec['confidence']} above {cap:.2f} while citing {', '.join(weak)}",
            )
        )
    return out
