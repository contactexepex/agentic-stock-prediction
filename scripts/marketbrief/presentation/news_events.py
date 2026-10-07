"""News events with their verification status for the context pack, and the evidence-status line of each
call in the report (news verification phase B; statuses from news_verified, as of a time)."""

from __future__ import annotations

import json

import pandas as pd

from marketbrief.constants.verification import (
    MAIN_EVIDENCE_STATUSES,
    MSG_MAIN_EVIDENCE_EVENTS,
    MSG_NO_MAIN_EVIDENCE,
    NEVER_SUPPORT_STATUSES,
    STATUS_PRECEDENCE,
    STATUS_UNVERIFIED,
    WIDEN_ONLY_STATUSES,
)
from marketbrief.core.clock import clock
from marketbrief.pipeline.claim_sources import clean_row
from marketbrief.pipeline.evidence_status import EvidenceStatuses

TITLE = (
    "News events and verification status (one row per same-event cluster instead of its headlines, "
    "highest status first; status as of now; cite = ids to cite, main evidence first)"
)
EVENTS_SQL = """
WITH c AS (SELECT * FROM news_clusters_asof(?::TIMESTAMPTZ) WHERE last_reported_at >= ?::TIMESTAMPTZ),
v AS (SELECT * FROM news_verified_asof(?::TIMESTAMPTZ) WHERE level = 'cluster')
SELECT c.ticker, c.cluster_id, c.news_ids, c.first_reported_at, c.last_reported_at, c.independent_origins,
       c.unread_vetted_origins, c.primary_ids AS candidates, v.status, v.primary_ids, v.conflicts, v.confirmed_at,
       v.status_ids, v.id_statuses, v.flags AS status_flags
FROM c LEFT JOIN v USING (cluster_id) ORDER BY c.ticker, c.last_reported_at DESC, c.cluster_id"""
TITLES_SQL = (   # the headline as of the context pack's clock
    "SELECT DISTINCT ON (id) id, title FROM news_lookup_asof(?::TIMESTAMPTZ) WHERE list_contains(?, id) "
    "ORDER BY id, first_seen_at"
)
CALLS_SQL = """
SELECT DISTINCT ON (id) id, ticker, horizon_days, direction, evidence_ids, made_at FROM predictions
WHERE as_of_date = ? ORDER BY id, made_at"""
HEADER = (
    "| ticker | event | status | verified origins | unread vetted | primary | conflicts | cite | first reported "
    "| confirmed |\n|---|---|---|---|---|---|---|---|---|---|\n"
)


def _short_time(value) -> str:
    """A timestamp as a short text, empty when missing."""
    return "" if value is None or pd.isna(value) else pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%d %H:%M")


def _conflicts(raw) -> str:
    """The conflicting statements of an event as a short text."""
    rows = json.loads(raw) if isinstance(raw, str) else raw or []
    return " vs ".join(
        f"{conflict['value']:g} {conflict['unit']}" + (" (primary)" if conflict.get("primary") else "")
        for conflict in rows
    )


def _cite(row: dict, status: str) -> list[str]:
    """Up to 3 ids a call may cite: confirming primary ids first, then news ids whose own status is the
    event's, unless that status can never support a call (rumour, promotional, contradicted)."""
    own = dict(zip(row.get("status_ids") or [], row.get("id_statuses") or []))
    news = (
        []
        if status in (*NEVER_SUPPORT_STATUSES, *WIDEN_ONLY_STATUSES)
        else [news_id for news_id in row.get("news_ids") or [] if own.get(news_id, STATUS_UNVERIFIED) == status]
    )
    return (list(row.get("primary_ids") or []) + news)[:3]


def event_rows(con, now, window_hours: float, per_ticker: int) -> list[dict]:
    """Current events (an item reported in the last window_hours) with their status: per ticker the
    per_ticker events of highest status precedence, newest first among equals."""
    now = pd.Timestamp(now)
    since = now - pd.Timedelta(hours=window_hours)
    event_frame = con.execute(EVENTS_SQL, [now.isoformat(), since.isoformat(), now.isoformat()]).df()
    rows = sorted(
        (clean_row(row) for row in event_frame.to_dict("records")),
        key=lambda row: (
            row["ticker"],
            STATUS_PRECEDENCE.index(row.get("status") or STATUS_UNVERIFIED),
            -pd.Timestamp(row["last_reported_at"]).value,
            row["cluster_id"],
        ),
    )
    kept, count = [], {}
    for row in rows:
        count[row["ticker"]] = count.get(row["ticker"], 0) + 1
        if count[row["ticker"]] <= per_ticker:
            kept.append(row)
    return kept


def context_section(con, window_hours: float = 72, per_ticker: int = 4) -> tuple[str, str]:
    """(title, markdown) of the context pack's news events section."""
    now = clock()
    rows = event_rows(con, now, window_hours, per_ticker)
    if not rows:
        return TITLE, "_none_\n"
    first_ids = [event["news_ids"][0] for event in rows if event.get("news_ids")]
    titles = dict(con.execute(TITLES_SQL, [now.isoformat(), first_ids]).fetchall())
    lines = []
    for event in rows:
        status = event.get("status") or STATUS_UNVERIFIED
        label = status if event.get("status") else f"{STATUS_UNVERIFIED} (no status row)"
        flags = [flag for flag in event.get("status_flags") or [] if flag]
        title = (titles.get((event.get("news_ids") or [""])[0]) or "").replace("|", "/")[:90]
        lines.append(
            f"| {event['ticker']} | {title} | {label}{' [' + ', '.join(flags) + ']' if flags else ''} | "
            f"{event['independent_origins']} | {event['unread_vetted_origins']} | "
            f"{', '.join(event.get('primary_ids') or []) or '–'} | {_conflicts(event.get('conflicts')) or '–'} | "
            f"{', '.join(_cite(event, status)) or '–'} | {_short_time(event['first_reported_at'])} | "
            f"{_short_time(event.get('confirmed_at'))} |"
        )
    return TITLE, main_evidence_line(rows) + "\n\n" + HEADER + "\n".join(lines) + "\n"


def main_evidence_line(rows: list[dict]) -> str:
    """How many shown events may be a call's main evidence now (issue #39: on a market's first days with
    status rows, e.g. India, often none, so a news-based call cannot pass the forecast gate)."""
    eligible = sorted({row["ticker"] for row in rows if row.get("status") in MAIN_EVIDENCE_STATUSES})
    count = sum(1 for row in rows if row.get("status") in MAIN_EVIDENCE_STATUSES)
    return MSG_MAIN_EVIDENCE_EVENTS.format(
        eligible=count,
        shown=len(rows),
        tickers=f" ({', '.join(eligible)})" if eligible else "",
        consequence="" if count else MSG_NO_MAIN_EVIDENCE,
    ).rstrip()


def call_status_lines(con, as_of) -> list[str]:
    """Report lines: each call of the as-of date with the status of every cited id as of its made_at."""
    calls = con.execute(CALLS_SQL, [as_of]).df()
    if calls.empty:
        return []
    statuses = EvidenceStatuses(con)
    out = ["Evidence status of the calls (each cited id as of the call's made_at; the first is the main evidence):", ""]
    for call in calls.itertuples():
        ids = list(call.evidence_ids) if call.evidence_ids is not None else []
        if not statuses.active(call.made_at):
            text = "no news status rows by made_at (before the feature): evidence unverified"
        else:
            text = (
                ", ".join(f"{evidence_id} {statuses.of(evidence_id, call.ticker, call.made_at)}" for evidence_id in ids)
                or "no evidence ids"
            )
        out.append(f"- {call.ticker} {call.horizon_days}d {call.direction}: {text}")
    return [*out, ""]
