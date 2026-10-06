"""Summaries of the week's live ranges and direction calls, with confidence bands."""
from __future__ import annotations

from datetime import date
import numpy as np
import pandas as pd
from marketbrief.analytics import range_math
from marketbrief.analytics import scoring
from marketbrief.pipeline.review.helpers import note_tags, numeric_series, rounded_mean


def load_ranges(con, cfg: dict, week_end: date) -> pd.DataFrame:
    df = con.execute("SELECT * FROM range_record WHERE target_date <= ? ORDER BY target_date, id", [week_end]).df()
    if df.empty:
        return df
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    base, y = df["base_close"].astype(float), df["actual_close"].astype(float)

    def iscore(lo, hi, band):
        return [100 * range_math.interval_score(a, b, v, band) / bc if not (pd.isna(a) or pd.isna(b)) else np.nan
                for a, b, v, bc in zip(numeric_series(lo), numeric_series(hi), y, base)]
    df["is50_pct"] = iscore(df["lo50"], df["hi50"], 0.5)
    df["naive_is50_pct"] = iscore(df["naive_lo50"], df["naive_hi50"], 0.5)
    df["width50_pct"] = 100 * (df["hi50"] - df["lo50"]) / base
    df["tags"] = [note_tags(n) + (["ai_call"] if isinstance(d, str) and d in ("up", "down") else [])
                  for n, d in zip(df["notes"], df["direction"])]
    df["sector"] = [cfg["tickers"].get(t, {}).get("sector") or "other" for t in df["ticker"]]
    return df


def range_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    return {"n": int(len(df)),
            "cover50": rounded_mean(df["hit50"]), "cover80": rounded_mean(df["hit80"]),
            "naive_cover50": rounded_mean(df["naive_hit50"]), "naive_cover80": rounded_mean(df["naive_hit80"]),
            "width50_pct": rounded_mean(df["width50_pct"], 3), "width80_pct": rounded_mean(df["width80_pct"], 3),
            "naive_width80_pct": rounded_mean(df["naive_width80_pct"], 3),
            "score50_pct": rounded_mean(df["is50_pct"], 3), "naive_score50_pct": rounded_mean(df["naive_is50_pct"], 3),
            "score80_pct": rounded_mean(df["is80_pct"], 3), "naive_score80_pct": rounded_mean(df["naive_is80_pct"], 3)}


def by_horizon(df: pd.DataFrame, fn) -> dict:
    out = {"all": fn(df)}
    for h, g in (df.groupby("horizon_days") if not df.empty else []):
        out[f"{int(h)}d"] = fn(g)
    return out


def breakdown(df: pd.DataFrame, col: str) -> dict:
    if df.empty:
        return {}
    d = df.explode(col) if col == "tags" else df
    return {f"{k} · {int(h)}d": range_summary(g) for (k, h), g in d.groupby([col, "horizon_days"])}


def load_calls(con, week_end: date) -> pd.DataFrame:
    df = con.execute("SELECT * FROM track_record WHERE target_date <= ? ORDER BY target_date, id", [week_end]).df()
    if not df.empty:
        df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df


def call_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    hit, up = rounded_mean(df["hit"]), rounded_mean(df["actual_return"] > 0)
    return {"n": int(len(df)), "hit_rate": hit, "always_up": up,
            "edge": round(hit - up, 4) if hit is not None and up is not None else None,
            "mean_confidence": rounded_mean(df["confidence"])}


def band_label(lo: float, hi: float) -> str:
    return f"{scoring.percent(lo)}-{scoring.percent(hi)}"


def confidence_bands(df: pd.DataFrame, edges: list[float]) -> dict:
    out = {}
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        last = i == len(edges) - 2
        g = df[(df["confidence"] >= lo) & ((df["confidence"] <= hi) if last else (df["confidence"] < hi))] \
            if not df.empty else df
        s = call_summary(g)
        if s["n"]:
            s["gap"] = round(s["hit_rate"] - s["mean_confidence"], 4)
        out[band_label(lo, hi)] = s
    return out
