"""The stored records behind the company pages (B12; docs/ws/b12.md), read once per market as of the build's cut-off
and sliced per company: lifecycle events, head-to-head picks, strategy predictions, settled paper trades, intraday
trade checks, AI reasons, results digests, the scoreboard and the split-adjusted bars. Every read keeps only what was
stored by the cut-off (no look-ahead) and only the collected companies' rows; nothing is recomputed that an engine
or a shared block already computes (B2's lab readers, the settled trades and scoreboard of rm_common, B11's
lifecycle-event rows, WS6's results macro, the dashboard's as-of bar rule). Times are ISO UTC `YYYY-MM-DDTHH:MM:SSZ`,
as in B11's and B4's records."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from marketbrief.constants.rm_company import BAR_LOOKBACK_DAYS, BAR_SESSIONS
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import reads as lab_reads
from marketbrief.presentation.dashboard import reads as dashboard_reads
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.company_records import lifecycle_rows
from marketbrief.warehouse.news_items import iso
from marketbrief.warehouse.rm_registry import BuildContext

# the dashboard's as-of bar rule (newest collection by the cut-off, closed days left out, the split records known
# by then applied) with `adjusted`: a split or bonus factor other than 1 was applied to the bar
ADJUSTED_SELECT = "AS volume, f.factor <> 1.0 AS adjusted\nFROM r JOIN f"
BARS_SQL = dashboard_reads.BARS_SQL.replace("AS volume\nFROM r JOIN f", ADJUSTED_SELECT)
assert ADJUSTED_SELECT in BARS_SQL, "the dashboard's BARS_SQL changed shape"
# each trade check's first stored row (view trade_check_rows), checked and computed by the cut-off
CHECKS_SQL = """SELECT * FROM trade_check_rows WHERE check_at <= $cutoff::TIMESTAMPTZ
                AND computed_at <= $cutoff::TIMESTAMPTZ ORDER BY ticker, check_at, trade_id, id"""
# each AI reason's first stored row, written by the cut-off
REASONS_SQL = """SELECT DISTINCT ON (id) * FROM trade_reasons_ai WHERE created_at <= $cutoff::TIMESTAMPTZ
                 ORDER BY id, created_at"""
DIGESTS_SQL = "SELECT * FROM results_digests_asof($cutoff::TIMESTAMPTZ) ORDER BY ticker, release_at, id"
DIGEST_JSON_COLUMNS = ("numbers", "consensus", "reaction", "bullets", "sources")


def by_ticker(rows: list[dict]) -> dict[str, list[dict]]:
    """ticker -> its rows, in the input order."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["ticker"], []).append(row)
    return grouped


def parsed(rows: list[dict], columns: tuple[str, ...]) -> list[dict]:
    """The rows with these JSON text columns parsed."""
    for row in rows:
        for column in columns:
            if isinstance(row.get(column), str):
                row[column] = json.loads(row[column])
    return rows


def zulu(rows: list[dict], *kinds: str) -> list[dict]:
    """Copies of the rows with the kinds' TIMESTAMPTZ columns as ISO UTC `...Z` text (shared rows stay unchanged)."""
    columns = {column for kind in kinds for column, kind_type in SCHEMAS[kind][1].items() if kind_type == "TIMESTAMPTZ"}
    return [{**row, **{column: iso(row[column]) for column in columns & row.keys()}} for row in rows]


def latest_checks(rows: list[dict]) -> list[dict]:
    """The rows of the newest check time (check_at) among the rows given."""
    newest = max((row["check_at"] for row in rows), default=None)
    return [row for row in rows if row["check_at"] == newest]


@dataclass
class CompanySources:
    """One market's stored records as of the cut-off, grouped per ticker."""
    market: str
    as_of: str | None
    session_date: str | None
    lifecycle: dict[str, list[dict]] = field(default_factory=dict)
    picks: dict[str, list[dict]] = field(default_factory=dict)
    predictions: dict[str, list[dict]] = field(default_factory=dict)
    settled: dict[str, list[dict]] = field(default_factory=dict)
    checks: dict[str, list[dict]] = field(default_factory=dict)
    market_checks: list[dict] = field(default_factory=list)
    reasons: dict[str, list[dict]] = field(default_factory=dict)
    digests: dict[str, list[dict]] = field(default_factory=dict)
    scoreboard: list[dict] = field(default_factory=list)
    bars: dict[str, list[dict]] = field(default_factory=dict)


def bar_rows(con, as_of: str, cutoff: datetime) -> dict[str, list[dict]]:
    """ticker -> its last BAR_SESSIONS split-adjusted bars up to the as-of date, oldest first."""
    start = date.fromisoformat(as_of) - timedelta(days=BAR_LOOKBACK_DAYS)
    frame = dashboard_reads.frame(con, BARS_SQL, {"as_of": as_of, "start": start, "cutoff": cutoff.isoformat()})
    grouped: dict[str, list[dict]] = {}
    for row in lab_reads.records(frame):
        grouped.setdefault(row["ticker"], []).append({
            "date": str(row["date"])[:10], "open": row["open"], "high": row["high"], "low": row["low"],
            "close": row["close"], "volume": row["volume"], "adjusted": bool(row["adjusted"])})
    return {ticker: rows[-BAR_SESSIONS:] for ticker, rows in grouped.items()}


def read_sources(ctx: BuildContext, as_of: str | None, session_date: str | None) -> CompanySources:
    """Every record the company pages need, as of the build's cut-off, of the collected companies only (a deleted
    company is never shown). `as_of` is the market's as-of date and `session_date` the session being predicted (the
    shared header's and status block's), both YYYY-MM-DD or None. Settled trades and the scoreboard are the shared
    blocks' (rm_common.settled_trades, lab_summary), so every page shows the same rows."""
    con, cutoff, collected = ctx.con, ctx.cutoff_time, ctx.collected
    mine = lambda rows: [row for row in rows if row["ticker"] in collected]  # noqa: E731
    sources = CompanySources(market=ctx.market, as_of=as_of, session_date=session_date)
    events = lifecycle_rows(con, cutoff, set(collected))
    sources.lifecycle = by_ticker(sorted(events, key=lambda row: (row["recorded_at"], row["id"])))
    params = {"cutoff": cutoff.isoformat()}
    checks = zulu(mine(lab_reads.records(con.execute(CHECKS_SQL, params).df(), "trade_checks")), "trade_checks",
                  "trade_check_details")
    sources.checks = {ticker: latest_checks(rows) for ticker, rows in by_ticker(checks).items()}
    sources.market_checks = latest_checks(checks)
    reasons = mine(lab_reads.records(con.execute(REASONS_SQL, params).df(), "trade_reasons_ai"))
    sources.reasons = by_ticker(zulu(reasons, "trade_reasons_ai"))
    digests = mine(lab_reads.records(con.execute(DIGESTS_SQL, params).df(), "results_digests"))
    sources.digests = by_ticker(zulu(parsed(digests, DIGEST_JSON_COLUMNS), "results_digests"))
    sources.settled = by_ticker(zulu(rm_common.settled_trades(ctx), "paper_trades_settled"))
    sources.scoreboard = rm_common.lab_summary(ctx)["scoreboard"]
    if as_of:
        picks = [row for row in mine(lab_reads.picks(con, cutoff)) if row["session_date"] == session_date]
        sources.picks = by_ticker(zulu(picks, "head_to_head_picks"))
        predictions = [row for row in mine(lab_reads.predictions(con, cutoff)) if row["as_of_date"] == as_of]
        sources.predictions = by_ticker(zulu(predictions, "strategy_predictions"))
        sources.bars = {ticker: rows for ticker, rows in bar_rows(con, as_of, cutoff).items() if ticker in collected}
    return sources
