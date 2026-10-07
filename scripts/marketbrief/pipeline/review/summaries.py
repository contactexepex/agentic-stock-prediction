"""Summaries of the week's live ranges and direction calls, with confidence bands."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from marketbrief.analytics import call_basis, range_math, scoring
from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.core.horizons import horizon_key
from marketbrief.pipeline.review.helpers import note_tags, numeric_series, rounded_mean


def load_ranges(con, cfg: dict, week_end: date) -> pd.DataFrame:
    """The scored ranges up to the week's end, with interval scores, widths, tags and sector."""
    frame = con.execute("SELECT * FROM range_record WHERE target_date <= ? ORDER BY target_date, id", [week_end]).df()
    if frame.empty:
        return frame
    frame["target_date"] = pd.to_datetime(frame["target_date"]).dt.date
    base, actual_close = frame["base_close"].astype(float), frame["actual_close"].astype(float)

    def interval_scores(lower, upper, band):
        """Interval scores in percent of the base close for lower and upper edges."""
        return [
            100 * range_math.interval_score(lower_edge, upper_edge, actual, band) / base_close
            if not (pd.isna(lower_edge) or pd.isna(upper_edge))
            else np.nan
            for lower_edge, upper_edge, actual, base_close in zip(
                numeric_series(lower), numeric_series(upper), actual_close, base
            )
        ]

    frame["is50_pct"] = interval_scores(frame["lo50"], frame["hi50"], 0.5)
    frame["naive_is50_pct"] = interval_scores(frame["naive_lo50"], frame["naive_hi50"], 0.5)
    frame["width50_pct"] = 100 * (frame["hi50"] - frame["lo50"]) / base
    frame["tags"] = [
        note_tags(notes) + (["ai_call"] if isinstance(direction, str) and direction in ("up", "down") else [])
        for notes, direction in zip(frame["notes"], frame["direction"])
    ]
    frame["sector"] = [cfg["tickers"].get(ticker, {}).get("sector") or "other" for ticker in frame["ticker"]]
    return frame


def range_summary(frame: pd.DataFrame) -> dict:
    """Coverage, width, score and naive baselines of a set of scored ranges."""
    if frame.empty:
        return {"n": 0}
    return {
        "n": int(len(frame)),
        "cover50": rounded_mean(frame["hit50"]),
        "cover80": rounded_mean(frame["hit80"]),
        "naive_cover50": rounded_mean(frame["naive_hit50"]),
        "naive_cover80": rounded_mean(frame["naive_hit80"]),
        "width50_pct": rounded_mean(frame["width50_pct"], 3),
        "width80_pct": rounded_mean(frame["width80_pct"], 3),
        "naive_width80_pct": rounded_mean(frame["naive_width80_pct"], 3),
        "score50_pct": rounded_mean(frame["is50_pct"], 3),
        "naive_score50_pct": rounded_mean(frame["naive_is50_pct"], 3),
        "score80_pct": rounded_mean(frame["is80_pct"], 3),
        "naive_score80_pct": rounded_mean(frame["naive_is80_pct"], 3),
    }


def by_horizon(frame: pd.DataFrame, summarizer, labels: bool = False) -> dict:
    """A summary of all rows and of each horizon's rows. labels (ranges): rows of a legacy horizon label (core/
    horizons.py; ranges stored before B10) are kept apart, under '<k>d legacy_cc', and left out of 'all'."""
    if labels and not frame.empty:
        current = frame[frame["horizon_label"] == LABEL_N_PLUS_K]
        out = {"all": summarizer(current)}
        for (label, horizon), group in frame.groupby(["horizon_label", "horizon_days"]):
            out[horizon_key(horizon, label)] = summarizer(group)
        return dict(sorted(out.items(), key=lambda item: (item[0] != "all", " " in item[0], item[0])))
    out = {"all": summarizer(frame)}
    for horizon, group in frame.groupby("horizon_days") if not frame.empty else []:
        out[f"{int(horizon)}d"] = summarizer(group)
    return out


def breakdown(frame: pd.DataFrame, col: str) -> dict:
    """A summary per value of a column (regime, sector, note tag) and horizon (legacy labels apart)."""
    if frame.empty:
        return {}
    exploded = frame.explode(col) if col == "tags" else frame
    return {
        f"{key} · {horizon_key(horizon, label)}": range_summary(group)
        for (key, label, horizon), group in exploded.groupby([col, "horizon_label", "horizon_days"])
    }


def per_basis(frame: pd.DataFrame, summarize) -> dict:
    """`summarize` per scoring basis of the calls, never pooled (call_basis.py): {'<key> · <basis>': value};
    `summarize(frame)` itself when there are no calls."""
    if frame.empty:
        return summarize(frame)
    keys = [scoring.basis_key(basis, label) for basis, label in zip(frame["label_basis"], frame["horizon_label"],
                                                                    strict=True)]
    return {
        f"{key} · {call_basis.label(basis)}": value
        for basis, group in frame.assign(_basis=keys).groupby("_basis", sort=True)
        for key, value in summarize(group).items()
    }


def load_calls(con, week_end: date) -> pd.DataFrame:
    """The scored direction calls up to the week's end."""
    frame = con.execute("SELECT * FROM track_record WHERE target_date <= ? ORDER BY target_date, id", [week_end]).df()
    if not frame.empty:
        frame["target_date"] = pd.to_datetime(frame["target_date"]).dt.date
    return frame


def call_summary(frame: pd.DataFrame) -> dict:
    """Hit rate, always-up baseline, edge and mean confidence of a set of calls."""
    if frame.empty:
        return {"n": 0}
    hit, up_moves = rounded_mean(frame["hit"]), rounded_mean(frame["actual_return"] > 0)
    return {
        "n": int(len(frame)),
        "hit_rate": hit,
        "always_up": up_moves,
        "edge": round(hit - up_moves, 4) if hit is not None and up_moves is not None else None,
        "mean_confidence": rounded_mean(frame["confidence"]),
    }


def band_label(lower: float, upper: float) -> str:
    """A confidence band as a label such as 60%-69%."""
    return f"{scoring.percent(lower)}-{scoring.percent(upper)}"


def confidence_bands(frame: pd.DataFrame, edges: list[float]) -> dict:
    """A call summary per confidence band, with the gap between hit rate and confidence."""
    out = {}
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
        last = index == len(edges) - 2
        group = (
            frame[
                (frame["confidence"] >= lower)
                & ((frame["confidence"] <= upper) if last else (frame["confidence"] < upper))
            ]
            if not frame.empty
            else frame
        )
        call_stats = call_summary(group)
        if call_stats["n"]:
            call_stats["gap"] = round(call_stats["hit_rate"] - call_stats["mean_confidence"], 4)
        out[band_label(lower, upper)] = call_stats
    return out
