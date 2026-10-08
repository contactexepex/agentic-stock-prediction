"""The Track record page (B13; docs/ws/b13.md): rm.track_record, page_key `_`, served by
GET /api/v1/markets/{market}/track-record (contract 2.0; it replaces WS1's 1.0 payload of the same table).
Payload TrackRecordPage = design/mockups/08-track-record/data.json per market: the shared blocks of rm_common and
`track`, the dashboard's track record as of the cut-off (presentation/dashboard/track.track_record: calls per scoring
basis, ranges per horizon, replay, min_sample; model_info.backtest_view: the signal model's back-test; the skill
verdict), unchanged, with the market, its as-of date and `example_parts` (always empty here: every block is the
stored data).

`weekly` (beyond the mockup; the Track record's open data request) is accuracy over time: per scoring basis key
(scoring.basis_key, the same keys as `track.calls`, never pooled), per ISO week of the calls' target date (the
session that decided them), the calls scored by the cut-off with their hit rate, Wilson 95% interval, Brier score and
log loss, oldest week first."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics import call_basis, scoring
from marketbrief.constants.warehouse import MARKET_PAGE_KEY, RM_TRACK_RECORD
from marketbrief.presentation.dashboard.track import CALLS_SQL, share_with_interval
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder
from view_data import asof_source

WEEK_OF = "target_date"  # the session a call's outcome was decided on


def iso_week(day) -> str:
    """YYYY-Www of a date."""
    year, week, _ = pd.Timestamp(day).isocalendar()
    return f"{year}-W{week:02d}"


def week_block(week: str, calls: pd.DataFrame) -> dict:
    """One week of one basis: calls, hits, hit rate with its Wilson interval, Brier score and log loss."""
    scores = scoring.call_scores(calls[["confidence", "hit"]].dropna())
    return {
        "week": week,
        **share_with_interval(int(calls["hit"].astype(bool).sum()), len(calls)),
        "brier": scores.get("brier"),
        "log_loss": scores.get("log_loss"),
    }


def weekly_series(con, cutoff: str) -> list[dict]:
    """Per scoring basis key: its weeks (oldest first), from the calls scored by the cut-off (the same as-of source
    as track.calls_by_basis, so a call counts only once its outcome was stored)."""
    calls = con.execute(CALLS_SQL.format(src=asof_source(con, "track_record", cutoff))).df()
    if calls.empty:
        return []
    calls["basis_key"] = [
        scoring.basis_key(basis, label)
        for basis, label in zip(calls["label_basis"], calls["horizon_label"], strict=True)
    ]
    calls["week"] = [iso_week(day) for day in calls[WEEK_OF]]
    out = []
    for key, group in calls.groupby("basis_key", sort=True):
        out.append(
            {
                "basis": group["label_basis"].iloc[0],
                "key": key,
                "label": call_basis.label(key),
                "weeks": [week_block(week, rows) for week, rows in group.groupby("week", sort=True)],
            }
        )
    return out


def track_block(ctx: BuildContext) -> dict:
    """The dashboard's track record of the market as of the cut-off, with its market and as-of date."""
    data = ctx.dashboard
    return {
        "market": ctx.market,
        "as_of": data["as_of"],
        "skill": data["skill"],
        **data["track"],
        "backtest": data["backtest"],
        "example_parts": [],
    }


def track_record_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.track_record: the market's one Track record page."""
    return {
        MARKET_PAGE_KEY: {
            **rm_common.header(ctx),
            "status": rm_common.status_block(ctx),
            **rm_common.horizons(ctx),
            "go_live": rm_common.go_live(ctx),
            "track": track_block(ctx),
            "weekly": weekly_series(ctx.con, ctx.cutoff),
        }
    }


def market_mockup(mockup: dict, market: str, _page_key: str) -> dict:
    """The mockup's payload of a market."""
    return mockup["markets"][market]


BUILDERS = (PageBuilder(RM_TRACK_RECORD, "TrackRecordPage", track_record_pages, owner="B13"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/track-record",
        table=RM_TRACK_RECORD,
        mockup="design/mockups/08-track-record/data.json",
        mockup_payload=market_mockup,
        # the weekly hit-rate and Brier series per scoring basis (the page's open data request)
        extra_keys=("weekly",),
    ),
)
