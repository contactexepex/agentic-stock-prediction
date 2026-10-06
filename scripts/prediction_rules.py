"""The CLAUDE.md prediction rules as one record check, shared by the daily gate
(validate.py --stage forecast) and the as-of replay (ai_replay.py record)."""
from __future__ import annotations

from marketbrief.core.schemas import SCHEMAS
from marketbrief.utils.timefmt import as_utc_timestamp

HORIZONS = (1, 5)
CONF_MIN, CONF_MAX, WIDEN_MAX, RATIONALE_WORDS = 0.50, 0.90, 0.5, 40
REQUIRED = ("id", "as_of_date", "ticker", "horizon_days", "direction", "confidence", "rationale",
            "evidence_ids", "prompt_version")


def check_prediction(rec, ctx: dict, seen: set[str], as_of=None, require_made_at: bool = False,
                     as_of_label: str = "the latest price date",
                     evidence_label: str = "the stored news/filings/announcements") -> list[str]:
    """Reasons a forecaster record breaks the schema or the CLAUDE.md prediction rules (empty = valid).

    ctx: `tickers` (watchlist), `features` {ticker: {quality, days_to_earnings}}, `evidence`
    (citable ids: a set, or a dict id -> when it became public; with a dict, each cited id must
    be public by the record's made_at). as_of: the required as_of_date, one date for every ticker
    or a dict ticker -> date (the latest price date in the context pack). seen: ids already stored."""
    if not isinstance(rec, dict):
        return ["not a JSON object"]
    cols = SCHEMAS["predictions"][1]
    errs = [f"unknown field {k!r}" for k in rec if k not in cols]
    for k in REQUIRED + (("made_at",) if require_made_at else ()):
        if rec.get(k) in (None, ""):
            errs.append(f"missing {k}")
    if errs:
        return errs
    t, h = rec["ticker"], rec["horizon_days"]
    if t not in ctx["tickers"]:
        errs.append(f"unknown ticker {t!r}")
    if not isinstance(h, int) or isinstance(h, bool) or h not in HORIZONS:
        errs.append(f"horizon_days must be 1 or 5 (got {h!r})")
    want = as_of.get(t) if isinstance(as_of, dict) else as_of
    if as_of is not None and str(rec["as_of_date"]) != str(want):
        errs.append(f"as_of_date {rec['as_of_date']} is not {as_of_label} {want}")
    if rec["id"] != f"{rec['as_of_date']}-{t}-{h}d":
        errs.append(f"id must be <as_of_date>-<ticker>-<horizon>d = {rec['as_of_date']}-{t}-{h}d (got {rec['id']!r})")
    if rec["id"] in seen:
        errs.append(f"id {rec['id']} already recorded")
    if rec["direction"] not in ("up", "down"):
        errs.append(f"direction must be up or down (got {rec['direction']!r})")
    c = rec["confidence"]
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not (CONF_MIN <= c <= CONF_MAX):
        errs.append(f"confidence must be {CONF_MIN:.2f}-{CONF_MAX:.2f} (got {c!r})")
    w = rec.get("range_widen")
    if w is not None and (not isinstance(w, (int, float)) or isinstance(w, bool) or not 0 <= w <= WIDEN_MAX):
        errs.append(f"range_widen must be 0-{WIDEN_MAX} (got {w!r})")
    if not isinstance(rec["rationale"], str) or len(rec["rationale"].split()) > RATIONALE_WORDS:
        errs.append(f"rationale must be text of at most {RATIONALE_WORDS} words")
    made = None
    if rec.get("made_at") is not None:
        made = as_utc_timestamp(rec["made_at"])
        if made is None:
            errs.append(f"made_at is not a timestamp ({rec['made_at']!r})")
    ids = rec["evidence_ids"]
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
        errs.append("evidence_ids must be a non-empty list of ids")
    else:
        unknown = [x for x in ids if x not in ctx["evidence"]]
        if unknown:
            errs.append(f"evidence ids not in {evidence_label}: {unknown}")
        if isinstance(ctx["evidence"], dict) and made is not None:
            late = [x for x in ids if ctx["evidence"].get(x) is not None and ctx["evidence"][x] > made]
            if late:
                errs.append(f"evidence published after made_at {made.isoformat()}: {late}")
    if not isinstance(rec["prompt_version"], str):
        errs.append("prompt_version must be text")
    f = ctx["features"].get(t)
    if t in ctx["tickers"]:
        if f is None:
            errs.append(f"no indicator snapshot for {t}" + (f" on {want}" if want is not None else ""))
        else:
            if f["quality"] == "BLOCKED":
                errs.append(f"{t} indicator quality is BLOCKED")
            if f["days_to_earnings"] is not None and f["days_to_earnings"] <= 1:
                errs.append(f"{t} has earnings within 1 day (days_to_earnings {f['days_to_earnings']})")
    return errs
