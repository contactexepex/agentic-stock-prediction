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


def band_of(confidence: float) -> str:
    return next(name for name, lower, upper in BANDS if lower <= confidence < upper)


def score_rows(cfg: dict, calls: list[dict], bars: dict) -> pd.DataFrame:
    """One row per call: base close at as_of_date, close `h` stored bars later, hit as
    score_predictions.py (a flat close is a miss), and the rule-baseline inputs known at as_of."""
    rows, cache = [], {}
    for call in calls:
        ticker, horizon, as_of = call["ticker"], int(call["horizon_days"]), pd.Timestamp(call["as_of_date"])
        frame = bars.get(ticker)
        row = {
            "id": call["id"],
            "date": as_of.date(),
            "ticker": ticker,
            "h": horizon,
            "direction": call["direction"],
            "confidence": float(call["confidence"]),
            "prompt_version": call.get("prompt_version"),
            "evidence_ids": call.get("evidence_ids"),
            "status": "no bars",
        }
        if frame is not None and len(frame):
            if ticker not in cache:
                close = frame["close"]
                cache[ticker] = (close, inputs.rsi_series(close))
            close, rsi = cache[ticker]
            position = int(close.index.searchsorted(as_of, side="right")) - 1
            if position >= 0:
                base = float(close.iloc[position])
                row.update(
                    {
                        "base_date": close.index[position].date(),
                        "base": base,
                        "ret1": base / float(close.iloc[position - 1]) - 1 if position >= 1 else np.nan,
                        "ret5": base / float(close.iloc[position - 5]) - 1 if position >= 5 else np.nan,
                        "rsi": float(rsi.iloc[position]) if not pd.isna(rsi.iloc[position]) else np.nan,
                        "status": "pending",
                    }
                )
                if position + horizon < len(close):
                    tgt = float(close.iloc[position + horizon])
                    called_up = call["direction"] == "up"
                    row.update(
                        {
                            "target_date": close.index[position + horizon].date(),
                            "target": tgt,
                            "ret": tgt / base - 1,
                            "fwd": math.log(tgt / base),
                            "hit": (tgt > base) if called_up else (tgt < base),
                            "status": "scored",
                        }
                    )
        rows.append(row)
    return pd.DataFrame(rows)


def hit_rate_stats(key: int, count: int) -> dict:
    lower, upper = replay_statistics.wilson(key, count)
    return {
        "n": count,
        "hits": key,
        "hit_rate": round_or_none(key / count) if count else None,
        "ci95": [round_or_none(lower), round_or_none(upper)],
        "p_vs_50": None if not count else float(f"{replay_statistics.binom_p_two_sided(key, count):.3g}"),
    }


def group_stats(group: pd.DataFrame) -> dict:
    """AI hit rate (Wilson 95% interval, exact binomial p vs 50%), stated confidence and Brier score,
    always-up and replay.py's rule baselines on the same ticker-days."""
    if group.empty:
        return {"n": 0}
    hit = group["hit"].astype(bool)
    out = hit_rate_stats(int(hit.sum()), len(group))
    out.update(
        {
            "mean_confidence": round_or_none(group["confidence"].mean()),
            "brier": round_or_none(((group["confidence"] - hit.astype(float)) ** 2).mean()),
        }
    )
    always_up_hits = group["fwd"] > 0
    out["always_up"] = hit_rate_stats(int(always_up_hits.sum()), len(group))
    diff = (hit.astype(float) - always_up_hits.astype(float)).to_numpy()
    blocks = pd.factorize(group["date"])[0]
    lower, upper = replay_statistics.clustered_ci(diff, blocks)
    out["diff_vs_always_up"] = {
        "pts": round_or_none(diff.mean()),
        "ci95": [round_or_none(lower), round_or_none(upper)],
        "note": "95% interval clustered by as-of date",
    }
    rules = {}
    sig = replay_statistics.signals(group.assign(ret1=group["ret1"], ret5=group["ret5"], rsi=group["rsi"]))
    up_moves, down = group["fwd"] > 0, group["fwd"] < 0
    for name, signal in sig.items():
        if name == "always_up":
            continue
        call = signal != 0
        rhit = ((signal > 0) & up_moves) | ((signal < 0) & down)
        rule_stats = hit_rate_stats(int(rhit[call].sum()), int(call.sum()))
        rule_stats["label"] = replay.SIGNAL_LABELS[name]
        rule_stats["ai_hit_rate_same_rows"] = round_or_none(hit[call].mean()) if call.any() else None
        rules[name] = rule_stats
    out["rules"] = rules
    return out
