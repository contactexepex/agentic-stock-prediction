"""Context around a results release: EPS against the last Yahoo consensus point stored BEFORE the release (context
only; earnings_estimates_asof) and the price reaction so far (analytics/earnings_reaction.affected_sessions: the
sessions whose close-to-close move holds the reaction, counted only once each session's bar is final)."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics.earnings_reaction import affected_sessions
from marketbrief.core.calendar import last_complete_session, prev_session
from marketbrief.core.market_config import benchmark_key
from marketbrief.results.constants import (
    CONSENSUS_BEFORE,
    CONSENSUS_NONE,
    CONTEXT_ONLY,
    SURPRISE_VS_FILED,
    SURPRISE_VS_YAHOO,
)
from marketbrief.results.detection import Release
from marketbrief.results.numbers import clean

ESTIMATE_SQL = """
SELECT id, report_date, report_at, eps_estimate, reported_eps, collected_at FROM earnings_estimates_asof(?::TIMESTAMPTZ)
WHERE ticker = ? AND abs(date_diff('day', report_date, ?::DATE)) <= ? AND {column} IS NOT NULL
ORDER BY abs(date_diff('day', report_date, ?::DATE)), collected_at DESC, id LIMIT 1"""
CLOSES_SQL = "SELECT date, close FROM bars WHERE ticker = ? AND list_contains(?, date) ORDER BY date"


def estimate_row(con, ticker: str, day, as_of: pd.Timestamp, gap: int, column: str) -> dict | None:
    """The stored Yahoo row known at `as_of` for the report nearest `day` (within `gap` days) with `column` set."""
    rows = con.execute(ESTIMATE_SQL.format(column=column), [as_of.isoformat(), ticker, str(day), gap, str(day)]).df()
    return None if rows.empty else rows.iloc[0].to_dict()


def consensus(con, release: Release, now: pd.Timestamp, filed_eps: float | None, conf: dict) -> dict:
    """EPS against the newest consensus collected strictly before release_at. The reported EPS is Yahoo's (same
    basis as its consensus) as stored by now, else the filed diluted EPS (basis may differ: labelled)."""
    gap = int(conf.get("max_report_gap_days", 7))
    before = release.release_at - pd.Timedelta(seconds=1)
    estimate = estimate_row(con, release.ticker, release.release_date, before, gap, "eps_estimate")
    out = {
        "note": CONTEXT_ONLY,
        "status": CONSENSUS_NONE,
        "consensus_eps": None,
        "consensus_collected_at": None,
        "reported_eps": None,
        "surprise_pct": None,
        "surprise_basis": None,
    }
    if estimate is None:
        return out
    out.update(
        {
            "status": CONSENSUS_BEFORE,
            "consensus_eps": clean(estimate["eps_estimate"]),
            "consensus_collected_at": pd.Timestamp(estimate["collected_at"]).tz_convert("UTC").isoformat(),
            "report_date": str(pd.Timestamp(estimate["report_date"]).date()),
        }
    )
    reported = estimate_row(con, release.ticker, release.release_date, now, gap, "reported_eps")
    if reported is not None and reported["id"] == estimate["id"]:
        out["reported_eps"], out["surprise_basis"] = clean(reported["reported_eps"]), SURPRISE_VS_YAHOO
    elif filed_eps is not None:
        out["reported_eps"], out["surprise_basis"] = filed_eps, SURPRISE_VS_FILED
    base = out["consensus_eps"]
    if out["reported_eps"] is not None and base:
        out["surprise_pct"] = round((out["reported_eps"] - base) / abs(base) * 100, 2)
    return out


def closes(con, ticker: str, days: list) -> dict:
    """Close per date of the given dates (adjusted bars)."""
    return {pd.Timestamp(day).date(): float(close) for day, close in con.execute(CLOSES_SQL, [ticker, days]).fetchall()}


def move(con, ticker: str, base_day, window: list, done: list) -> tuple[float | None, object]:
    """(move in % from the base close to the latest final close in the window, its date)."""
    found = closes(con, ticker, [base_day, *window])
    last = next((day for day in reversed(done) if day in found), None)
    if base_day not in found or last is None:
        return None, None
    return round((found[last] / found[base_day] - 1) * 100, 2), last


def reaction(con, cfg: dict, release: Release, now: pd.Timestamp) -> dict:
    """Close-to-close move of the ticker and the benchmark over the earnings window so far."""
    window = affected_sessions(cfg, release.release_date, release.timing)
    base_day = prev_session(cfg, window[0], include=False)
    final = last_complete_session(cfg, now.to_pydatetime())
    done = [day for day in window if day <= final]
    out = {
        "window": [str(day) for day in window],
        "base_date": str(base_day),
        "sessions_done": len(done),
        "sessions_total": len(window),
        "complete": len(done) == len(window),
        "as_of": now.isoformat(),
        "move_pct": None,
        "last_date": None,
        "benchmark": benchmark_key(cfg),
        "benchmark_move_pct": None,
        "excess_pct": None,
    }
    if not done:
        return out
    out["move_pct"], last = move(con, release.ticker, base_day, window, done)
    out["last_date"] = None if last is None else str(last)
    if out["benchmark"] and last is not None:
        bench, bench_last = move(con, out["benchmark"], base_day, window, [day for day in done if day <= last])
        if bench is not None and bench_last == last:
            out["benchmark_move_pct"] = bench
            out["excess_pct"] = round(out["move_pct"] - bench, 2)
    return out
