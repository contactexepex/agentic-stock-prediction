"""Scored rows of the recorded calls and their hit-rate statistics against the baselines."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from marketbrief.constants import replay
from marketbrief.replay.rule_replay import inputs
from marketbrief.replay.rule_replay import replay_statistics
from marketbrief.utils.numbers import round_or_none
from marketbrief.constants.ai_replay import BANDS


def band_of(c: float) -> str:
    return next(name for name, lo, hi in BANDS if lo <= c < hi)


def score_rows(cfg: dict, calls: list[dict], bars: dict) -> pd.DataFrame:
    """One row per call: base close at as_of_date, close `h` stored bars later, hit as
    score_predictions.py (a flat close is a miss), and the rule-baseline inputs known at as_of."""
    rows, cache = [], {}
    for c in calls:
        t, h, d = c["ticker"], int(c["horizon_days"]), pd.Timestamp(c["as_of_date"])
        df = bars.get(t)
        row = {"id": c["id"], "date": d.date(), "ticker": t, "h": h, "direction": c["direction"],
               "confidence": float(c["confidence"]), "prompt_version": c.get("prompt_version"),
               "evidence_ids": c.get("evidence_ids"), "status": "no bars"}
        if df is not None and len(df):
            if t not in cache:
                close = df["close"]
                cache[t] = (close, inputs.rsi_series(close))
            close, rsi = cache[t]
            i = int(close.index.searchsorted(d, side="right")) - 1
            if i >= 0:
                base = float(close.iloc[i])
                row.update({"base_date": close.index[i].date(), "base": base,
                            "ret1": base / float(close.iloc[i - 1]) - 1 if i >= 1 else np.nan,
                            "ret5": base / float(close.iloc[i - 5]) - 1 if i >= 5 else np.nan,
                            "rsi": float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else np.nan,
                            "status": "pending"})
                if i + h < len(close):
                    tgt = float(close.iloc[i + h])
                    up = c["direction"] == "up"
                    row.update({"target_date": close.index[i + h].date(), "target": tgt, "ret": tgt / base - 1,
                                "fwd": math.log(tgt / base), "hit": (tgt > base) if up else (tgt < base),
                                "status": "scored"})
        rows.append(row)
    return pd.DataFrame(rows)


def hit_rate_stats(k: int, n: int) -> dict:
    lo, hi = replay_statistics.wilson(k, n)
    return {"n": n, "hits": k, "hit_rate": round_or_none(k / n) if n else None,
    "ci95": [round_or_none(lo), round_or_none(hi)],
            "p_vs_50": None if not n else float(f"{replay_statistics.binom_p_two_sided(k, n):.3g}")}


def group_stats(g: pd.DataFrame) -> dict:
    """AI hit rate (Wilson 95% interval, exact binomial p vs 50%), stated confidence and Brier score,
    always-up and replay.py's rule baselines on the same ticker-days."""
    if g.empty:
        return {"n": 0}
    hit = g["hit"].astype(bool)
    out = hit_rate_stats(int(hit.sum()), len(g))
    out.update({"mean_confidence": round_or_none(g["confidence"].mean()),
                "brier": round_or_none(((g["confidence"] - hit.astype(float)) ** 2).mean())})
    au = (g["fwd"] > 0)
    out["always_up"] = hit_rate_stats(int(au.sum()), len(g))
    diff = (hit.astype(float) - au.astype(float)).to_numpy()
    blocks = pd.factorize(g["date"])[0]
    lo, hi = replay_statistics.clustered_ci(diff, blocks)
    out["diff_vs_always_up"] = {"pts": round_or_none(diff.mean()), "ci95": [round_or_none(lo), round_or_none(hi)],
                                "note": "95% interval clustered by as-of date"}
    rules = {}
    sig = replay_statistics.signals(g.assign(ret1=g["ret1"], ret5=g["ret5"], rsi=g["rsi"]))
    up, down = g["fwd"] > 0, g["fwd"] < 0
    for name, s in sig.items():
        if name == "always_up":
            continue
        call = s != 0
        rhit = ((s > 0) & up) | ((s < 0) & down)
        r = hit_rate_stats(int(rhit[call].sum()), int(call.sum()))
        r["label"] = replay.SIGNAL_LABELS[name]
        r["ai_hit_rate_same_rows"] = round_or_none(hit[call].mean()) if call.any() else None
        rules[name] = r
    out["rules"] = rules
    return out
