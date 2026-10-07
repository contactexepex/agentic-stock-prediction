"""Deterministic attribution candidates of a flagged ticker: the benchmark and sector moves over the same
window, the index cue, and the news, exchange announcements and events known by the check. Each candidate has
an id the explainer may cite (stored ids for news, announcements and events; bench:/sector:/cue: + symbol)."""

from __future__ import annotations

from marketbrief.intraday import inputs
from marketbrief.intraday.constants import (
    CAND_ANNOUNCEMENT,
    CAND_BENCHMARK,
    CAND_CUE,
    CAND_EVENT,
    CAND_NEWS,
    CAND_PREFIX,
    CAND_SECTOR,
)
from marketbrief.intraday.measures import rounded


def market_candidates(row: dict, market_moves: dict) -> list[dict]:
    """Benchmark, sector and cue candidates of a row (only those with a measured move)."""
    out = []
    bench = market_moves.get("benchmark")
    if bench and row.get("bench_ret") is not None:
        out.append({"id": CAND_PREFIX[CAND_BENCHMARK] + bench, "kind": CAND_BENCHMARK, "symbol": bench,
                    "ret": row["bench_ret"], "beta": row.get("beta"), "residual": row.get("residual")})
    if row.get("sector_ret") is not None and row.get("sector_key"):
        out.append({"id": CAND_PREFIX[CAND_SECTOR] + row["sector_key"], "kind": CAND_SECTOR,
                    "symbol": row["sector_key"], "source": row.get("sector_source"), "ret": row["sector_ret"],
                    "residual": row.get("sector_residual")})
    cue = market_moves.get("cue")
    if cue:
        out.append({"id": CAND_PREFIX[CAND_CUE] + cue["symbol"], "kind": CAND_CUE, "symbol": cue["symbol"],
                    "ret": cue["ret"], "ts": cue["ts"], "range_notes": row.get("cue_notes") or []})
    return out


def item_candidates(con, ticker: str, window: tuple, session_date, limit: int) -> list[dict]:
    """News and announcements first seen in the window, and today's events (all known by the check)."""
    since, check_at = window
    out = [
        {"id": item["id"], "kind": CAND_NEWS, "title": item["title"], "source": item["source"],
         "first_seen_at": _iso(item["first_seen_at"]), "status": item["status"],
         "materiality": item.get("materiality"), "sentiment": rounded(item.get("sentiment"), 3)}
        for item in inputs.news_since(con, ticker, since, check_at, limit)
    ]
    out += [
        {"id": item["id"], "kind": CAND_ANNOUNCEMENT, "subject": item["subject"], "category": item["category"],
         "first_seen_at": _iso(item["first_seen_at"])}
        for item in inputs.announcements_since(con, ticker, since, check_at, limit)
    ]
    out += [
        {"id": item["id"], "kind": CAND_EVENT, "type": item["type"], "name": item["name"],
         "timing": item.get("timing"), "amount": item.get("amount")}
        for item in inputs.events_today(con, ticker, session_date, check_at)
    ]
    return out


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()
