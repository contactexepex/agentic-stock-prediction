"""Scored rows of the recorded calls and their hit-rate statistics against the baselines."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from marketbrief.constants import replay
from marketbrief.constants.ai_replay import BANDS
from marketbrief.constants.horizons import LABEL_LEGACY_CC, LABEL_N_PLUS_K
from marketbrief.core.horizons import exit_offset
from marketbrief.replay.rule_replay import inputs, replay_statistics
from marketbrief.utils.numbers import round_or_none


def band_of(confidence: float) -> str:
    """The confidence band name of a confidence."""
    return next(name for name, lower, upper in BANDS if lower <= confidence < upper)


def window_of(call: dict, since: pd.Timestamp | None) -> tuple[str, int]:
    """(horizon label, stored bars after the as-of bar whose close resolves the call). A call recorded before
    `since` (config/settings.yaml call_scoring.n_plus_k_from) keeps the window it was scored on before B10, the
    as-of close to the close h bars later (legacy_cc, issue #96); later ones are N+h (core/horizons.exit_offset)."""
    horizon, recorded = int(call["horizon_days"]), call.get("recorded_at")
    if since is not None and recorded and pd.Timestamp(recorded) < since:
        return LABEL_LEGACY_CC, horizon
    return LABEL_N_PLUS_K, exit_offset(horizon)


def score_rows(_cfg: dict, calls: list[dict], bars: dict, since: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per call: base close at as_of_date, the exit close of its window (`window_of`: N+h = h + 1 stored
    bars later, the close of the h-th session after D, the first session after as_of; legacy_cc = h bars later),
    hit as score_predictions.py (a flat close is a miss), and the rule-baseline inputs known at as_of."""
    rows, cache = [], {}
    for call in calls:
        ticker, horizon, as_of = call["ticker"], int(call["horizon_days"]), pd.Timestamp(call["as_of_date"])
        label, offset = window_of(call, since)
        frame = bars.get(ticker)
        row = {
            "id": call["id"],
            "date": as_of.date(),
            "ticker": ticker,
            "h": horizon,
            "horizon_label": label,
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
                exit_position = position + offset
                if exit_position < len(close):
                    target_close = float(close.iloc[exit_position])
                    called_up = call["direction"] == "up"
                    row.update(
                        {
                            "target_date": close.index[exit_position].date(),
                            "target": target_close,
                            "ret": target_close / base - 1,
                            "fwd": math.log(target_close / base),
                            "hit": (target_close > base) if called_up else (target_close < base),
                            "status": "scored",
                        }
                    )
        rows.append(row)
    return pd.DataFrame(rows)


def hit_rate_stats(hits: int, count: int) -> dict:
    """Hit rate with its Wilson 95% interval and the binomial p-value against 50%."""
    lower, upper = replay_statistics.wilson(hits, count)
    return {
        "n": count,
        "hits": hits,
        "hit_rate": round_or_none(hits / count) if count else None,
        "ci95": [round_or_none(lower), round_or_none(upper)],
        "p_vs_50": None if not count else replay_statistics.binom_p_two_sided(hits, count),  # rounded for display
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
    signals = replay_statistics.signals(group.assign(ret1=group["ret1"], ret5=group["ret5"], rsi=group["rsi"]))
    up_moves, down = group["fwd"] > 0, group["fwd"] < 0
    for name, signal in signals.items():
        if name == "always_up":
            continue
        has_call = signal != 0
        rhit = ((signal > 0) & up_moves) | ((signal < 0) & down)
        rule_stats = hit_rate_stats(int(rhit[has_call].sum()), int(has_call.sum()))
        rule_stats["label"] = replay.SIGNAL_LABELS[name]
        rule_stats["ai_hit_rate_same_rows"] = round_or_none(hit[has_call].mean()) if has_call.any() else None
        rules[name] = rule_stats
    out["rules"] = rules
    return out
