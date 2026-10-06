"""The forecast stage of the daily gate (validate.py --stage forecast): work/predictions.jsonl before it is
appended. Every CLAUDE.md prediction rule (prediction_rules.check_prediction), evidence public before
made_at, no calls on a late or mid-session run, and the news-verification rules on the cited evidence
(prediction_rules.check_news_status, each id's status as of the record's made_at; codes NEWS_STATUS_*).
Before the first status row existed (days before the feature) the status rules are not applied and
NEWS_STATUS_MISSING is a warning."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from marketbrief.constants.verification import CODE_FORECAST_RULE, CODE_NEWS_STATUS_MISSING
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.utils.timefmt import ISO_UTC, as_utc_timestamp
from marketbrief.analytics.prediction_rules import check_news_status, check_prediction


def evidence_times(con) -> dict:
    """Citable id -> when it became public (UTC): news published_at, SEC acceptance (else the end
    of the filing date), NSE announcement time; first_seen_at when nothing else is stored."""
    out = {}
    for sql in (
        "SELECT id, coalesce(published_at, first_seen_at) FROM news",
        "SELECT id, coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ), first_seen_at) FROM filings",
        "SELECT id, coalesce(published_at, first_seen_at) FROM announcements",
    ):
        for i, t in con.execute(f"SELECT * FROM ({sql}) ORDER BY 1, 2").fetchall():  # per id the earliest wins
            out.setdefault(i, as_utc_timestamp(t))
    return out


def forecast_context(cfg: dict, con) -> tuple[dict, dict, set]:
    """(rule context, as-of date per ticker, stored prediction ids) for check_prediction."""
    feats = con.execute(
        "SELECT DISTINCT ON (ticker) ticker, as_of_date, quality, days_to_earnings "
        "FROM features_latest ORDER BY ticker, as_of_date DESC"
    ).df()
    ctx = {
        "tickers": set(cfg["tickers"]),
        "features": {
            r.ticker: {
                "quality": r.quality,
                "days_to_earnings": None if pd.isna(r.days_to_earnings) else int(r.days_to_earnings),
            }
            for r in feats.itertuples()
        },
        "evidence": evidence_times(con),
    }
    as_of = {r.ticker: pd.Timestamp(r.as_of_date).date() for r in feats.itertuples()}
    return ctx, as_of, {r[0] for r in con.execute("SELECT id FROM predictions").fetchall()}


def status_failures(res, rec: dict, line: int, statuses: EvidenceStatuses) -> bool:
    """Apply the news-verification rules to a record that passed the others; True when it passes."""
    made = as_utc_timestamp(rec["made_at"])
    if not statuses.active(made):
        res.warn(
            CODE_NEWS_STATUS_MISSING,
            f"line {line} ({rec['id']}): no news status rows by made_at "
            f"{made.isoformat()} (before the feature): evidence status rules not applied",
            [rec["ticker"]],
        )
        return True
    found = [statuses.of(i, rec["ticker"], made) for i in rec["evidence_ids"]]
    res.info.setdefault("evidence_status", {})[rec["id"]] = dict(zip(rec["evidence_ids"], found))
    broken = check_news_status(rec, found)
    for code, reason in broken:
        res.block(code, f"line {line} ({rec['id']}): {reason}", [rec["ticker"]])
    return not broken


def stage_forecast(res, cfg, con, st, now, vc, path: Path) -> None:  # noqa: PLR0913 - the stage signature
    """Check every record of the forecaster's file; failures and warnings go to `res`."""
    if not path.exists() or path.stat().st_size == 0:
        res.info["forecast"] = "no predictions (abstained or not run)"
        return
    raw = path.read_text(encoding="utf-8")
    if not raw.endswith("\n"):
        res.block("BAD_FILE", f"{path.name}: last line has no newline (truncated write?)")
    lines = [x for x in raw.splitlines() if x.strip()]
    if lines and (st["late_run"] or st["in_session"]):
        why = "late run" if st["late_run"] else "mid-session run"
        res.block(
            "CALLS_NOT_ALLOWED",
            f"{why}: the forecaster must abstain on every ticker, but {path.name} holds {len(lines)} record(s)",
        )
    ctx, as_of, seen = forecast_context(cfg, con)
    statuses = EvidenceStatuses(con)
    tol = pd.Timedelta(minutes=vc["future_tolerance_minutes"])
    good = 0
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            res.block(CODE_FORECAST_RULE, f"line {i}: not JSON ({e.msg})")
            continue
        errs = check_prediction(rec, ctx, seen, as_of=as_of, require_made_at=True)
        made = as_utc_timestamp(rec.get("made_at")) if isinstance(rec, dict) else None
        if made is not None:
            if made > now + tol:
                errs.append(f"made_at {rec['made_at']} is in the future")
            if not ISO_UTC.match(str(rec["made_at"])):
                errs.append("made_at is not ISO 8601 UTC")
        tk = [rec.get("ticker")] if isinstance(rec, dict) and rec.get("ticker") else []
        if errs:
            res.block(
                CODE_FORECAST_RULE,
                f"line {i} ({rec.get('id') if isinstance(rec, dict) else '?'}): " + "; ".join(errs),
                tk,
            )
        elif status_failures(res, rec, i, statuses):
            good += 1
        if isinstance(rec, dict) and rec.get("id"):
            seen.add(rec["id"])
    res.info["forecast"] = {"records": len(lines), "valid": good}
