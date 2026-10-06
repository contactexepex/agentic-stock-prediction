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
    out = {"market": cfg["market"], "name": cfg.get("name"), "computed_at": utc_now(),
           "model_training_cutoff": str(cutoff),
           "rule": (f"fair = as-of date after {cutoff} (the model's training cutoff); contaminated = on or before "
                    "it. Scored separately, never pooled.")}
    for label in (FAIR, CONTAMINATED):
        g_days = [x for x in days if leakage_label(x["date"], cutoff) == label]
        g_calls = [c for c in calls if leakage_label(c["as_of_date"], cutoff) == label]
        out[label] = summarize_group(cfg, g_calls, g_days, bars, label)
    return out


def summarize_group(cfg: dict, calls: list[dict], days: list[dict], bars: dict, label: str) -> dict:
    df = score_rows(cfg, calls, bars)
    sc = df[df["status"] == "scored"] if len(df) else df
    out = {"test": label, "n_days": len(days), "dates": sorted(x["date"] for x in days), "n_calls": int(len(df)),
           "n_scored": int(len(sc)), "n_pending": int((df["status"] == "pending").sum()) if len(df) else 0,
           "n_no_bars": int((df["status"] == "no bars").sum()) if len(df) else 0,
           "prompt_versions": sorted({c.get("prompt_version") for c in calls if c.get("prompt_version")}),
           "fair_test": label == FAIR,
           "overall": group_stats(sc) if len(sc) else {"n": 0},
           "by_horizon": {str(h): group_stats(sc[sc["h"] == h]) if len(sc) else {"n": 0} for h in HORIZONS},
           "by_band": []}
    for name, lo, hi in BANDS:
        g = sc[(sc["confidence"] >= lo) & (sc["confidence"] < hi)] if len(sc) else sc
        r = hit_rate_stats(int(g["hit"].astype(bool).sum()), len(g)) if len(g) else {"n": 0}
        r.update({"band": name, "stated": round_or_none(g["confidence"].mean()) if len(g) else None})
        out["by_band"].append(r)
    # abstention: a call slot is an eligible ticker (not BLOCKED, no earnings within 1 day) x horizon x day
    called = {(c["as_of_date"], c["ticker"], int(c["horizon_days"])) for c in calls}
    ab = {}
    for h in HORIZONS:
        slots = sum(len(x["eligible"]) for x in days)
        n = sum(1 for x in days for t in x["eligible"] if (x["date"], t, h) in called)
        ab[f"{h}d"] = {"slots": slots, "calls": n, "abstention_rate": round_or_none(1 - n / slots) if slots else None}
    slots = sum(len(x["eligible"]) for x in days)
    anyc = sum(1 for x in days for t in x["eligible"] if any((x["date"], t, h) in called for h in HORIZONS))
    ab["any"] = {"slots": slots, "ticker_days_with_a_call": anyc,
                 "abstention_rate": round_or_none(1 - anyc / slots) if slots else None}
    ab["ineligible_ticker_days"] = sum(x["n_tickers"] - len(x["eligible"]) for x in days)
    out["abstention"] = ab
    per_day = []
    for x in sorted(days, key=lambda x: x["date"]):
        g = sc[sc["date"].astype(str) == x["date"]] if len(sc) else sc
        per_day.append({"date": x["date"], "test": label, "calls": x["n_calls"], "rejected": x["n_rejected"],
                        "citable_ids": x.get("citable_ids"), "scored": int(len(g)),
                        "hits": int(g["hit"].astype(bool).sum()) if len(g) else 0})
    out["per_day"] = per_day
    keep = ["id", "date", "ticker", "h", "direction", "confidence", "status", "base_date", "base", "target_date",
            "target", "ret", "hit", "evidence_ids"]
    out["calls"] = [{"test": label, **{k: (None if (isinstance(v, float) and not math.isfinite(v)) else v)
                                       for k, v in r.items()}}
                    for r in df.reindex(columns=keep).astype(object).where(df.reindex(columns=keep).notna(), None)
                    .to_dict("records")] if len(df) else []
    out["top"] = top_sentences(out)
    return out


def pct(x, k: int = 1) -> str:
    """A share as a percent with one decimal by default (`k` decimals when given); 'n/a' when missing."""
    return share_percent_text(x, k)


def top_sentences(s: dict) -> list[str]:
    o, ab = s["overall"], s["abstention"]["any"]
    if not o.get("n"):
        return ["Did the AI beat a coin flip? No call has been scored yet, so there is nothing to judge.",
                "Did it beat simple rules? Not measurable without scored calls.",
                f"Is its confidence honest? Not measurable yet; it abstained on {pct(ab['abstention_rate'])} of the "
                f"{ab['slots']} stock-days it could call."]
    lo, hi = o["ci95"]
    verdict = ("clearly better than a coin flip" if lo > 0.5 else "clearly worse than a coin flip" if hi < 0.5
               else "not distinguishable from a coin flip")
    s1 = (f"Did the AI beat a coin flip? Its {o['n']} scored calls were right {pct(o['hit_rate'])} of the time "
          f"(95% interval {pct(lo)} to {pct(hi)}), {verdict} (50%).")
    d = o["diff_vs_always_up"]
    dlo, dhi = d["ci95"]
    noise = ("within noise" if dlo is None or (dlo <= 0 <= dhi) else "a clear difference")
    rules = [f"{r['label']} {pct(r['hit_rate'])} on its {r['n']} calls (AI {pct(r['ai_hit_rate_same_rows'])} there)"
             for r in o["rules"].values() if r.get("n")]
    s2 = (f"Did it beat simple rules? On the same stocks and days always calling up was right "
          f"{pct(o['always_up']['hit_rate'])}, so the AI was {100 * d['pts']:+.1f} points vs always-up ({noise})"
          + ("; " + "; ".join(rules) if rules else "") + ".")
    gap = o["hit_rate"] - o["mean_confidence"]
    honest = ("about right" if abs(gap) <= 0.05 else "overconfident" if gap < 0 else "underconfident")
    s3 = (f"Is its confidence honest? It stated {pct(o['mean_confidence'])} on average and was right "
          f"{pct(o['hit_rate'])}, so it looks {honest} on this sample; it abstained on {pct(ab['abstention_rate'])} "
          f"of the {ab['slots']} stock-days it could call.")
    return [s1, s2, s3]
