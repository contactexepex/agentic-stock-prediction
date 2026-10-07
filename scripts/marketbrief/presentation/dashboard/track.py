"""Track-record numbers of the dashboard, from the scored outcomes stored by the cut-off. Calls are
summarised per scoring basis (close_to_close, open_to_close, and open_to_close legacy_5d_d4 for the old D+4
window: scoring.basis_key), never pooled, with the same helpers the weekly review and the HTML report use
(review summaries.call_summary, scoring.call_scores / reliability / range_scores / wilson). Ranges per horizon
and horizon label (core.horizons.horizon_key: an old window is never pooled with N+k) with Wilson 95% intervals.
The historical replay is reported apart: it is rules only and not live."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics import call_basis, scoring
from marketbrief.constants.horizon_names import NAME_LEGACY_CALLS, NAME_LEGACY_RANGE, NAME_REPLAY
from marketbrief.core.horizons import horizon_key, horizons
from marketbrief.pipeline.review.summaries import call_summary
from marketbrief.presentation.horizon_names import by_horizon, horizon_name
from marketbrief.utils.numbers import json_safe_float
from view_data import MIN_SAMPLE, asof_source

CALLS_SQL = "SELECT * FROM {src} WHERE hit IS NOT NULL ORDER BY id, scored_at"
RANGES_SQL = (
    "SELECT horizon_days, horizon_label, lo50, hi50, lo80, hi80, actual_close, base_close, hit50, hit80 FROM {src} "
    "WHERE actual_close IS NOT NULL ORDER BY id"
)
REPLAY_FIELDS = ("start_date", "end_date", "computed_at", "n_days", "n_ranges", "report")
# per horizon h of the replay record (core/schema_base.py replays): <metric>_<h>d
REPLAY_HORIZON_METRICS = ("cover50", "cover80", "score80", "naive_score80", "always_up")


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
    """Per scoring basis key (scoring.basis_key; the old D+4 open-to-close calls apart): all horizons, then each
    horizon and label (keys core.horizons.horizon_key, e.g. "1d" for N+1, "1d legacy_cc"), shortest first."""
    calls = con.execute(CALLS_SQL.format(src=asof_source(con, "track_record", cutoff))).df()
    out = []
    if len(calls):
        calls["basis_key"] = [
            scoring.basis_key(basis, label)
            for basis, label in zip(calls["label_basis"], calls["horizon_label"], strict=True)
        ]
    for key, group in calls.groupby("basis_key", sort=True) if len(calls) else []:
        per_horizon = {}
        for (h, label), rows in by_horizon(group):
            name = horizon_name(h, label, legacy=NAME_LEGACY_CALLS)
            per_horizon[horizon_key(h, label)] = {**call_block(rows), "h": h, "horizon_label": label, "name": name}
        out.append(
            {
                "basis": group["label_basis"].iloc[0],
                "key": key,
                "label": call_basis.label(key),
                "all": call_block(group),
                "by_horizon": per_horizon,
            }
        )
    return out


def ranges_by_horizon(con, cutoff) -> list[dict]:
    """Per horizon and horizon label (an old window never pooled with N+k): how often the close landed inside the
    50% and 80% ranges, with Wilson intervals, plus the interval scores of scoring.range_scores."""
    rng = con.execute(RANGES_SQL.format(src=asof_source(con, "range_record", cutoff))).df()
    out = []
    for (h, label), group in by_horizon(rng):
        n = len(group)
        out.append(
            {
                "h": int(h),
                "key": horizon_key(h, label),
                "horizon_label": label,
                "name": horizon_name(h, label, legacy=NAME_LEGACY_RANGE),
                "inside50": share_with_interval(int(group["hit50"].astype(bool).sum()), n),
                "inside80": share_with_interval(int(group["hit80"].astype(bool).sum()), n),
                "scores": scoring.range_scores(group),
            }
        )
    return out


def replay_view(record: dict | None) -> dict | None:
    """The newest historical replay's headline numbers (rules only, not live): the fields of every configured
    horizon the record carries (`horizons`, each with its `<metric>_<h>d` fields and a name in `names`)."""
    if record is None:
        return None
    replayed = [h for h in horizons() if any(record.get(f"{m}_{h}d") is not None for m in REPLAY_HORIZON_METRICS)]
    fields = REPLAY_FIELDS + tuple(f"{m}_{h}d" for h in replayed for m in REPLAY_HORIZON_METRICS)
    out = {"horizons": replayed, "names": {str(h): NAME_REPLAY.format(h=h) for h in replayed}}
    for field in fields:
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
