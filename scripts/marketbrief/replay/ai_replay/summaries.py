"""Scores per leakage group (fair and contaminated, never pooled) and the top sentences."""

from __future__ import annotations

import math
from datetime import date
from marketbrief.core.clock import utc_now
from marketbrief.utils.numbers import round_or_none, share_percent_text
from marketbrief.constants.prediction_rules import HORIZONS
from marketbrief.constants.ai_replay import BANDS, CONTAMINATED, FAIR
from marketbrief.replay.ai_replay.cutoff import leakage_label, training_cutoff
from marketbrief.replay.ai_replay.score_stats import group_stats, hit_rate_stats, score_rows


def summarize(cfg: dict, calls: list[dict], days: list[dict], bars: dict, cutoff: date | None = None) -> dict:
    """Scores per leakage group (ForecastBench rule): `fair` = as-of dates after the model's training
    cutoff, `contaminated` = on or before it. Each group is scored on its own rows only; nothing is
    pooled across groups. The label comes from the current config cutoff, not from the stored rows."""
    cutoff = cutoff or training_cutoff()
    out = {
        "market": cfg["market"],
        "name": cfg.get("name"),
        "computed_at": utc_now(),
        "model_training_cutoff": str(cutoff),
        "rule": (
            f"fair = as-of date after {cutoff} (the model's training cutoff); contaminated = on or before "
            "it. Scored separately, never pooled."
        ),
    }
    for label in (FAIR, CONTAMINATED):
        g_days = [day for day in days if leakage_label(day["date"], cutoff) == label]
        g_calls = [call for call in calls if leakage_label(call["as_of_date"], cutoff) == label]
        out[label] = summarize_group(cfg, g_calls, g_days, bars, label)
    return out


def summarize_group(cfg: dict, calls: list[dict], days: list[dict], bars: dict, label: str) -> dict:
    frame = score_rows(cfg, calls, bars)
    scored = frame[frame["status"] == "scored"] if len(frame) else frame
    out = {
        "test": label,
        "n_days": len(days),
        "dates": sorted(day["date"] for day in days),
        "n_calls": int(len(frame)),
        "n_scored": int(len(scored)),
        "n_pending": int((frame["status"] == "pending").sum()) if len(frame) else 0,
        "n_no_bars": int((frame["status"] == "no bars").sum()) if len(frame) else 0,
        "prompt_versions": sorted({call.get("prompt_version") for call in calls if call.get("prompt_version")}),
        "fair_test": label == FAIR,
        "overall": group_stats(scored) if len(scored) else {"n": 0},
        "by_horizon": {
            str(horizon): group_stats(scored[scored["h"] == horizon]) if len(scored) else {"n": 0}
            for horizon in HORIZONS
        },
        "by_band": [],
    }
    for name, lower, upper in BANDS:
        band_rows = scored[(scored["confidence"] >= lower) & (scored["confidence"] < upper)] if len(scored) else scored
        band_stats = (
            hit_rate_stats(int(band_rows["hit"].astype(bool).sum()), len(band_rows)) if len(band_rows) else {"n": 0}
        )
        band_stats.update(
            {"band": name, "stated": round_or_none(band_rows["confidence"].mean()) if len(band_rows) else None}
        )
        out["by_band"].append(band_stats)
    # abstention: a call slot is an eligible ticker (not BLOCKED, no earnings within 1 day) x horizon x day
    called = {(call["as_of_date"], call["ticker"], int(call["horizon_days"])) for call in calls}
    abstention = {}
    for horizon in HORIZONS:
        slots = sum(len(day["eligible"]) for day in days)
        count = sum(1 for day in days for ticker in day["eligible"] if (day["date"], ticker, horizon) in called)
        abstention[f"{horizon}d"] = {
            "slots": slots,
            "calls": count,
            "abstention_rate": round_or_none(1 - count / slots) if slots else None,
        }
    slots = sum(len(day["eligible"]) for day in days)
    anyc = sum(
        1
        for day in days
        for ticker in day["eligible"]
        if any((day["date"], ticker, horizon) in called for horizon in HORIZONS)
    )
    abstention["any"] = {
        "slots": slots,
        "ticker_days_with_a_call": anyc,
        "abstention_rate": round_or_none(1 - anyc / slots) if slots else None,
    }
    abstention["ineligible_ticker_days"] = sum(day["n_tickers"] - len(day["eligible"]) for day in days)
    out["abstention"] = abstention
    per_day = []
    for day in sorted(days, key=lambda day: day["date"]):
        band_rows = scored[scored["date"].astype(str) == day["date"]] if len(scored) else scored
        per_day.append(
            {
                "date": day["date"],
                "test": label,
                "calls": day["n_calls"],
                "rejected": day["n_rejected"],
                "citable_ids": day.get("citable_ids"),
                "scored": int(len(band_rows)),
                "hits": int(band_rows["hit"].astype(bool).sum()) if len(band_rows) else 0,
            }
        )
    out["per_day"] = per_day
    keep = [
        "id",
        "date",
        "ticker",
        "h",
        "direction",
        "confidence",
        "status",
        "base_date",
        "base",
        "target_date",
        "target",
        "ret",
        "hit",
        "evidence_ids",
    ]
    out["calls"] = (
        [
            {
                "test": label,
                **{
                    column: (None if (isinstance(value, float) and not math.isfinite(value)) else value)
                    for column, value in band_stats.items()
                },
            }
            for band_stats in frame.reindex(columns=keep)
            .astype(object)
            .where(frame.reindex(columns=keep).notna(), None)
            .to_dict("records")
        ]
        if len(frame)
        else []
    )
    out["top"] = top_sentences(out)
    return out


def pct(share, key: int = 1) -> str:
    """A share as a percent with one decimal by default (`k` decimals when given); 'n/a' when missing."""
    return share_percent_text(share, key)


def top_sentences(summary: dict) -> list[str]:
    overall, abstention = summary["overall"], summary["abstention"]["any"]
    if not overall.get("n"):
        return [
            "Did the AI beat a coin flip? No call has been scored yet, so there is nothing to judge.",
            "Did it beat simple rules? Not measurable without scored calls.",
            f"Is its confidence honest? Not measurable yet; it abstained on {pct(abstention['abstention_rate'])} of "
            f"the "
            f"{abstention['slots']} stock-days it could call.",
        ]
    lower, upper = overall["ci95"]
    verdict = (
        "clearly better than a coin flip"
        if lower > 0.5
        else "clearly worse than a coin flip"
        if upper < 0.5
        else "not distinguishable from a coin flip"
    )
    summary_one_day = (
        f"Did the AI beat a coin flip? Its {overall['n']} scored calls were right {pct(overall['hit_rate'])} of the "
        f"time "
        f"(95% interval {pct(lower)} to {pct(upper)}), {verdict} (50%)."
    )
    difference = overall["diff_vs_always_up"]
    dlo, dhi = difference["ci95"]
    noise = "within noise" if dlo is None or (dlo <= 0 <= dhi) else "a clear difference"
    rules = [
        f"{row['label']} {pct(row['hit_rate'])} on its {row['n']} calls (AI {pct(row['ai_hit_rate_same_rows'])} there)"
        for row in overall["rules"].values()
        if row.get("n")
    ]
    summary_two = (
        f"Did it beat simple rules? On the same stocks and days always calling up was right "
        f"{pct(overall['always_up']['hit_rate'])}, so the AI was {100 * difference['pts']:+.1f} points vs always-up "
        f"({noise})" + ("; " + "; ".join(rules) if rules else "") + "."
    )
    gap = overall["hit_rate"] - overall["mean_confidence"]
    honest = "about right" if abs(gap) <= 0.05 else "overconfident" if gap < 0 else "underconfident"
    summary_three = (
        f"Is its confidence honest? It stated {pct(overall['mean_confidence'])} on average and was right "
        f"{pct(overall['hit_rate'])}, so it looks {honest} on this sample; it abstained on "
        f"{pct(abstention['abstention_rate'])} "
        f"of the {abstention['slots']} stock-days it could call."
    )
    return [summary_one_day, summary_two, summary_three]
