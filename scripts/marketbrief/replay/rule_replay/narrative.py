"""Plain-language summary of a replay: headline lines, top sentences and limitations."""
from __future__ import annotations

from marketbrief.analytics import range_switches
from marketbrief.utils.numbers import share_percent_text
from marketbrief.constants.replay import LIMITATIONS, SIGNALS


def pct(x, k: int = 0) -> str:
    """A share as a whole percent by default (`k` decimals when given); 'n/a' when missing."""
    return share_percent_text(x, k)


def headline(cfg: dict, s: dict) -> list[str]:
    lines = []
    for h, hs in s["horizons"].items():
        o = hs["overall"]
        if not o.get("n"):
            continue
        c80, c50 = o["cover80"], o["cover50"]
        verdict = ("about right" if abs(c80 - 0.8) <= 0.03 else
                   ("too narrow: the price fell outside more often than promised" if c80 < 0.8 else
                    "too wide: the price stayed inside more often than needed"))
        ci = o["cover80_ci"]
        lines.append(f"{h}-day ranges: the 80% band contained the actual close {pct(c80, 1)} of the time "
                     f"(95% interval {pct(ci[0], 1)} to {pct(ci[1], 1)}; target 80%) and the 50% band "
                     f"{pct(c50, 1)} (target 50%) over {o['n']:,} ranges on {o['days']} days: {verdict}.")
        if o.get("naive_score80") is not None:
            better = o["score80_same_rows"] < o["naive_score80"]
            lines.append(f"{h}-day accuracy vs the naive range (last close +/- 20-day volatility): interval score "
                         f"{o['score80_same_rows']:.2f} vs {o['naive_score80']:.2f} (lower is better), width "
                         f"{o['width80_pct']:.2f}% vs {o['naive_width80_pct']:.2f}% of the price; the formula is "
                         f"{'better' if better else 'not better'} than the naive range.")
        regs = {k: v for k, v in hs["by_regime"].items() if v.get("n", 0) >= 100}
        if regs:
            worst = min(regs.items(), key=lambda kv: kv[1]["cover80"])
            best = max(regs.items(), key=lambda kv: kv[1]["cover80"])
            lines.append(f"{h}-day by regime: 80% coverage ranges from {pct(worst[1]['cover80'], 1)} in {worst[0]} "
                         f"to {pct(best[1]['cover80'], 1)} in {best[0]}.")
        e = hs["by_earnings"]["earnings in horizon"]
        if e.get("n"):
            lines.append(f"{h}-day with earnings inside the horizon: 80% coverage {pct(e['cover80'], 1)} "
                         f"over {e['n']} ranges (no earnings: {pct(hs['by_earnings']['no earnings'].get('cover80'), 1)}).")
        tick = {k: v for k, v in hs["by_ticker"].items() if v.get("n", 0) >= 50}
        low = sorted(tick.items(), key=lambda kv: kv[1]["cover80"])[:3]
        if low:
            lines.append(f"{h}-day lowest 80% coverage by ticker: "
                         + ", ".join(f"{t} {pct(v['cover80'], 1)}" for t, v in low) + ".")
    for h, b in s["baselines"].items():
        au = b.get("always_up")
        if not au:
            continue
        parts = []
        for name in SIGNALS[1:]:
            x = b.get(name)
            if not x or not x["calls"]:
                continue
            d, ci = x["diff_vs_always_up"], x["diff_ci95"]
            sig = ci[0] is not None and (ci[0] > 0 or ci[1] < 0)
            parts.append(f"{x['label']} {pct(x['hit_rate'], 1)} ({x['calls']:,} calls, "
                         f"{'+' if d >= 0 else ''}{100 * d:.1f} pts vs always-up on the same rows"
                         f"{', clear' if sig else ', within noise'})")
        lines.append(f"{h}-day direction baselines: always-up was right {pct(au['hit_rate'], 1)} of the time "
                     f"(95% interval {pct(au['ci95'][0], 1)} to {pct(au['ci95'][1], 1)}); " + "; ".join(parts) + ".")
    return lines


def coverage_groups(hs: dict, min_n: int = 100) -> dict[str, dict]:
    """Named slices of one horizon (regimes, earnings or a major event in the horizon) with enough rows."""
    out = {f"{k} markets": v for k, v in hs.get("by_regime", {}).items()}
    out["earnings inside the horizon"] = hs.get("by_earnings", {}).get("earnings in horizon", {})
    out["a major market event inside the horizon"] = hs.get("by_major_event", {}).get("major event in horizon", {})
    return {k: v for k, v in out.items() if v.get("n", 0) >= min_n and v.get("cover80") is not None}


def top_sentences(s: dict) -> list[str]:
    """At most three short sentences for the top of the page, one per question (exact figures, one decimal)."""
    hz, out = s["horizons"], []
    o = {h: hz.get(h, {}).get("overall", {}) for h in ("1", "5")}
    if o["1"].get("n") and o["5"].get("n"):
        c = [o["1"]["cover80"], o["5"]["cover80"]]
        verdict = ("about right" if all(abs(x - 0.8) <= 0.03 for x in c) else
                   "too wide (they held more often than promised)" if all(x > 0.8 for x in c) else
                   "too narrow (they held less often than promised)" if all(x < 0.8 for x in c) else "mixed")
        out.append(f"Do the ranges keep their promise? The 80% ranges contained the later close {pct(c[0], 1)} of the "
                   f"time 1 day ahead and {pct(c[1], 1)} 5 days ahead, and the 50% ranges {pct(o['1']['cover50'], 1)} "
                   f"and {pct(o['5']['cover50'], 1)}, so overall they are {verdict}.")
    parts = []
    for h in ("1", "5"):
        g = coverage_groups(hz.get(h, {}))
        if not g:
            continue
        hi = max(g.items(), key=lambda kv: kv[1]["cover80"])
        lo = min(g.items(), key=lambda kv: kv[1]["cover80"])
        prep = lambda name: "in" if name.endswith("markets") else "with"  # noqa: E731
        hi_txt = (f"{'widest' if hi[1]['cover80'] > 0.8 else 'closest to 80%'} {prep(hi[0])} {hi[0]} "
                  f"({pct(hi[1]['cover80'], 1)} held)")
        lo_txt = (f"{'too narrow' if lo[1]['cover80'] < 0.8 else 'closest to 80%'} {prep(lo[0])} {lo[0]} "
                  f"({pct(lo[1]['cover80'], 1)})")
        parts.append(f"{h}-day ranges were {hi_txt} and {lo_txt}")
    if parts:
        out.append("Where are they too wide or too narrow? " + "; ".join(parts) + ".")
    b = s.get("baselines", {})
    au = {h: (b.get(h) or {}).get("always_up") for h in ("1", "5")}
    if au["1"] and au["5"]:
        better, worse, noise = [], 0, 0
        for h in ("1", "5"):
            for name in SIGNALS[1:]:
                x = (b.get(h) or {}).get(name)
                if not x or not x["calls"] or x["diff_ci95"][0] is None:
                    continue
                if x["diff_ci95"][0] > 0:
                    better.append(f"{x['label']} {h}-day (+{100 * x['diff_vs_always_up']:.1f} percentage points)")
                elif x["diff_ci95"][1] < 0:
                    worse += 1
                else:
                    noise += 1
        n = worse + noise + len(better)
        were = "was" if worse == 1 else "were"
        tail = (f"of the momentum and RSI rules only {', '.join(better)} beat it clearly ({worse} of {n} tests {were} "
                "clearly worse)" if better else
                f"none of the momentum and RSI rules beat it clearly ({worse} of {n} tests {were} clearly worse, the rest "
                "within noise)")
        out.append(f"Do simple up/down rules work? Always calling \"up\" was right {pct(au['1']['hit_rate'], 1)} of the "
                   f"time 1 day ahead and {pct(au['5']['hit_rate'], 1)} 5 days ahead (a coin flip is 50%), and {tail}.")
    return out


def limitations(cfg: dict, rc: dict, s: dict) -> list[str]:
    market, out = cfg["market"], list(LIMITATIONS)
    ic = cfg.get("index_cue") or {}
    if ic.get("symbol") and range_switches.enabled(rc, "beta_split", market):
        on = [h for h in rc["horizons"] if range_switches.enabled(rc, "beta_split", market, h)]
        if ic.get("beta", 1.0) == "fit":
            out.append(f"Index cue (beta split, on for {', '.join(f'{h}d' for h in on)}): {ic['symbol']}'s last session "
                       "return before the next session x the beta fitted on bars up to d, as the live pre-open quote gives it.")
        else:
            out.append(f"Index cue {ic['symbol']} (quoted before the open) has no stored history: the beta split has no "
                       "index cue in the replay.")
    mism = {h: v.get("calendar_mismatch", 0) for h, v in s["horizons"].items() if v.get("calendar_mismatch")}
    if mism:
        out.append("Ranges are scored on the close h stored bars later. On " + ", ".join(f"{n} {h}d" for h, n in mism.items())
                   + " rows that bar is not the exchange-calendar target date a live range names (bars on special "
                   "sessions such as India's Muhurat trading, or a session without a bar).")
    if (rc.get("relation_widen") or {}).get("enabled") or float(rc.get("activist_13d_factor", 1.0)) != 1.0:
        out.append("WARNING: relationship or smart-money widening is switched on but cannot be replayed.")
    if range_switches.enabled(rc, "implied_vol", market):
        out.append("WARNING: implied_vol is switched on but cannot be replayed; replayed ranges omit it.")
    return out
