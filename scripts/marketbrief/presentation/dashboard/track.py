"""Track-record numbers of the dashboard, from the scored outcomes stored by the cut-off. Calls are
summarised per scoring basis (close_to_close, open_to_close), never pooled, with the same helpers the
weekly review and the HTML report use (review summaries.call_summary, scoring.call_scores /
reliability / range_scores / wilson). Ranges per horizon with Wilson 95% intervals. The historical
replay is reported apart: it is rules only and not live."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics import call_basis, scoring
from marketbrief.pipeline.review.summaries import call_summary
from marketbrief.utils.numbers import json_safe_float
from view_data import MIN_SAMPLE, asof_source

CALLS_SQL = "SELECT * FROM {src} WHERE hit IS NOT NULL ORDER BY id, scored_at"
RANGES_SQL = (
    "SELECT horizon_days, lo50, hi50, lo80, hi80, actual_close, base_close, hit50, hit80 FROM {src} "
    "WHERE actual_close IS NOT NULL ORDER BY id"
)
REPLAY_FIELDS = (
    "start_date",
    "end_date",
    "computed_at",
    "n_days",
    "n_ranges",
    "cover50_1d",
    "cover80_1d",
    "cover50_5d",
    "cover80_5d",
    "score80_1d",
    "naive_score80_1d",
    "score80_5d",
    "naive_score80_5d",
    "always_up_1d",
    "always_up_5d",
    "report",
)


def share_with_interval(hits: int, n: int) -> dict:
    """hits of n, the share and its Wilson 95% interval."""
    low, high = scoring.wilson(hits, n)
    return {"n": n, "hits": hits, "share": hits / n if n else None, "wilson_lo": low, "wilson_hi": high}


def call_block(calls: pd.DataFrame) -> dict:
    """One basis (or one horizon of it): hit rate with its interval, the always-up baseline, proper scores
    and the reliability table."""
    summary = call_summary(calls)
    hits = int(calls["hit"].astype(bool).sum()) if len(calls) else 0
    scored = calls[["confidence", "hit"]].dropna() if len(calls) else pd.DataFrame(columns=["confidence", "hit"])
    return {
        **share_with_interval(hits, len(calls)),
        "always_up": summary.get("always_up"),
        "edge": summary.get("edge"),
        "mean_confidence": summary.get("mean_confidence"),
        "scores": scoring.call_scores(scored),
        "reliability": [
            {k: json_safe_float(v) if isinstance(v, float) else v for k, v in row.items()}
            for row in scoring.reliability(scored["confidence"], scored["hit"])
        ]
        if len(scored)
        else [],
    }


def calls_by_basis(con, cutoff) -> list[dict]:
    """Per scoring basis: all horizons, then 1-day and 5-day."""
    calls = con.execute(CALLS_SQL.format(src=asof_source(con, "track_record", cutoff))).df()
    out = []
    for basis, group in calls.groupby("label_basis", sort=True) if len(calls) else []:
        out.append(
            {
                "basis": basis,
                "label": call_basis.label(basis),
                "all": call_block(group),
                "by_horizon": {f"{int(h)}d": call_block(g) for h, g in group.groupby("horizon_days")},
            }
        )
    return out


def ranges_by_horizon(con, cutoff) -> list[dict]:
    """Per horizon: how often the close landed inside the 50% and 80% ranges, with Wilson intervals,
    plus the interval scores of scoring.range_scores."""
    rng = con.execute(RANGES_SQL.format(src=asof_source(con, "range_record", cutoff))).df()
    out = []
    for h, group in rng.groupby("horizon_days") if len(rng) else []:
        n = len(group)
        out.append(
            {
                "h": int(h),
                "inside50": share_with_interval(int(group["hit50"].astype(bool).sum()), n),
                "inside80": share_with_interval(int(group["hit80"].astype(bool).sum()), n),
                "scores": scoring.range_scores(group),
            }
        )
    return out


def replay_view(record: dict | None) -> dict | None:
    """The newest historical replay's headline numbers (rules only, not live)."""
    if record is None:
        return None
    out = {}
    for field in REPLAY_FIELDS:
        value = record.get(field)
        if field in ("start_date", "end_date", "computed_at"):
            out[field] = (
                None
                if value is None or pd.isna(value)
                else pd.Timestamp(value).isoformat()[: 10 if "date" in field else None]
            )
        elif isinstance(value, str) or value is None:
            out[field] = value
        else:
            out[field] = json_safe_float(value)
    return out


def track_record(con, cutoff, replay_record: dict | None) -> dict:
    """Live calls per basis, ranges per horizon and the replay, as stored by the cut-off."""
    return {
        "calls": calls_by_basis(con, cutoff),
        "ranges": ranges_by_horizon(con, cutoff),
        "replay": replay_view(replay_record),
        "min_sample": MIN_SAMPLE,
    }
