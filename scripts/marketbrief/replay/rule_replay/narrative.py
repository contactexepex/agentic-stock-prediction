"""Plain-language summary of a replay: headline lines, top sentences and limitations."""

from __future__ import annotations

from marketbrief.analytics import range_switches
from marketbrief.constants.replay import LIMITATIONS, SIGNALS
from marketbrief.utils.numbers import share_percent_text


def pct(share, decimals: int = 0) -> str:
    """A share as a whole percent by default (`k` decimals when given); 'n/a' when missing."""
    return share_percent_text(share, decimals)


def headline(_cfg: dict, summary: dict) -> list[str]:
    """The summary lines of a replay: coverage, accuracy, regimes, tickers and baselines."""
    lines = []
    for horizon, horizon_summary in summary["horizons"].items():
        overall = horizon_summary["overall"]
        if not overall.get("n"):
            continue
        c80, c50 = overall["cover80"], overall["cover50"]
        verdict = (
            "about right"
            if abs(c80 - 0.8) <= 0.03
            else (
                "too narrow: the price fell outside more often than promised"
                if c80 < 0.8
                else "too wide: the price stayed inside more often than needed"
            )
        )
        interval = overall["cover80_ci"]
        lines.append(
            f"{horizon}-day ranges: the 80% band contained the actual close {pct(c80, 1)} of the time "
            f"(95% interval {pct(interval[0], 1)} to {pct(interval[1], 1)}; target 80%) and the 50% band "
            f"{pct(c50, 1)} (target 50%) over {overall['n']:,} ranges on {overall['days']} days: {verdict}."
        )
        if overall.get("naive_score80") is not None:
            better = overall["score80_same_rows"] < overall["naive_score80"]
            lines.append(
                f"{horizon}-day accuracy vs the naive range (last close +/- 20-day volatility): interval score "
                f"{overall['score80_same_rows']:.2f} vs {overall['naive_score80']:.2f} (lower is better), width "
                f"{overall['width80_pct']:.2f}% vs {overall['naive_width80_pct']:.2f}% of the price; the formula is "
                f"{'better' if better else 'not better'} than the naive range."
            )
        regs = {regime: value for regime, value in horizon_summary["by_regime"].items() if value.get("n", 0) >= 100}
        if regs:
            worst = min(regs.items(), key=lambda key_value: key_value[1]["cover80"])
            best = max(regs.items(), key=lambda key_value: key_value[1]["cover80"])
            lines.append(
                f"{horizon}-day by regime: 80% coverage ranges from {pct(worst[1]['cover80'], 1)} in {worst[0]} "
                f"to {pct(best[1]['cover80'], 1)} in {best[0]}."
            )
        earnings = horizon_summary["by_earnings"]["earnings in horizon"]
        if earnings.get("n"):
            lines.append(
                f"{horizon}-day with earnings inside the horizon: 80% coverage {pct(earnings['cover80'], 1)} "
                f"over {earnings['n']} ranges (no earnings: "
                f"{pct(horizon_summary['by_earnings']['no earnings'].get('cover80'), 1)})."
            )
        tick = {ticker: value for ticker, value in horizon_summary["by_ticker"].items() if value.get("n", 0) >= 50}
        low = sorted(tick.items(), key=lambda key_value: key_value[1]["cover80"])[:3]
        if low:
            lines.append(
                f"{horizon}-day lowest 80% coverage by ticker: "
                + ", ".join(f"{ticker} {pct(value['cover80'], 1)}" for ticker, value in low)
                + "."
            )
    for horizon, baseline in summary["baselines"].items():
        always_up = baseline.get("always_up")
        if not always_up:
            continue
        parts = []
        for name in SIGNALS[1:]:
            signal = baseline.get(name)
            if not signal or not signal["calls"]:
                continue
            difference, interval = signal["diff_vs_always_up"], signal["diff_ci95"]
            sig = interval[0] is not None and (interval[0] > 0 or interval[1] < 0)
            parts.append(
                f"{signal['label']} {pct(signal['hit_rate'], 1)} ({signal['calls']:,} calls, "
                f"{'+' if difference >= 0 else ''}{100 * difference:.1f} pts vs always-up on the same rows"
                f"{', clear' if sig else ', within noise'})"
            )
        lines.append(
            f"{horizon}-day direction baselines: always-up was right {pct(always_up['hit_rate'], 1)} of the time "
            f"(95% interval {pct(always_up['ci95'][0], 1)} to {pct(always_up['ci95'][1], 1)}); "
            + "; ".join(parts)
            + "."
        )
    return lines


def coverage_groups(horizon_summary: dict, min_n: int = 100) -> dict[str, dict]:
    """Named slices of one horizon (regimes, earnings or a major event in the horizon) with enough rows."""
    out = {f"{key} markets": regime_summary for key, regime_summary in horizon_summary.get("by_regime", {}).items()}
    out["earnings inside the horizon"] = horizon_summary.get("by_earnings", {}).get("earnings in horizon", {})
    out["a major market event inside the horizon"] = horizon_summary.get("by_major_event", {}).get(
        "major event in horizon", {}
    )
    return {
        key: regime_summary
        for key, regime_summary in out.items()
        if regime_summary.get("n", 0) >= min_n and regime_summary.get("cover80") is not None
    }


def top_sentences(summary: dict) -> list[str]:
    """At most three short sentences for the top of the page, one per question (exact figures, one decimal)."""
    by_horizon, out = summary["horizons"], []
    overall = {horizon: by_horizon.get(horizon, {}).get("overall", {}) for horizon in ("1", "5")}
    if overall["1"].get("n") and overall["5"].get("n"):
        coverage = [overall["1"]["cover80"], overall["5"]["cover80"]]
        verdict = (
            "about right"
            if all(abs(item - 0.8) <= 0.03 for item in coverage)
            else "too wide (they held more often than promised)"
            if all(item > 0.8 for item in coverage)
            else "too narrow (they held less often than promised)"
            if all(item < 0.8 for item in coverage)
            else "mixed"
        )
        out.append(
            f"Do the ranges keep their promise? The 80% ranges contained the later close {pct(coverage[0], 1)} of the "
            f"time 1 day ahead and {pct(coverage[1], 1)} 5 days ahead, and the 50% ranges "
            f"{pct(overall['1']['cover50'], 1)} "
            f"and {pct(overall['5']['cover50'], 1)}, so overall they are {verdict}."
        )
    parts = []
    for horizon in ("1", "5"):
        slices = coverage_groups(by_horizon.get(horizon, {}))
        if not slices:
            continue
        highest = max(slices.items(), key=lambda key_value: key_value[1]["cover80"])
        lowest = min(slices.items(), key=lambda key_value: key_value[1]["cover80"])
        prep = lambda name: "in" if name.endswith("markets") else "with"  # noqa: E731
        hi_txt = (
            f"{'widest' if highest[1]['cover80'] > 0.8 else 'closest to 80%'} {prep(highest[0])} {highest[0]} "
            f"({pct(highest[1]['cover80'], 1)} held)"
        )
        lo_txt = (
            f"{'too narrow' if lowest[1]['cover80'] < 0.8 else 'closest to 80%'} {prep(lowest[0])} {lowest[0]} "
            f"({pct(lowest[1]['cover80'], 1)})"
        )
        parts.append(f"{horizon}-day ranges were {hi_txt} and {lo_txt}")
    if parts:
        out.append("Where are they too wide or too narrow? " + "; ".join(parts) + ".")
    baselines = summary.get("baselines", {})
    always_up = {horizon: (baselines.get(horizon) or {}).get("always_up") for horizon in ("1", "5")}
    if always_up["1"] and always_up["5"]:
        better, worse, noise = [], 0, 0
        for horizon in ("1", "5"):
            for name in SIGNALS[1:]:
                item = (baselines.get(horizon) or {}).get(name)
                if not item or not item["calls"] or item["diff_ci95"][0] is None:
                    continue
                if item["diff_ci95"][0] > 0:
                    better.append(
                        f"{item['label']} {horizon}-day (+{100 * item['diff_vs_always_up']:.1f} percentage points)"
                    )
                elif item["diff_ci95"][1] < 0:
                    worse += 1
                else:
                    noise += 1
        count = worse + noise + len(better)
        were = "was" if worse == 1 else "were"
        tail = (
            f"of the momentum and RSI rules only {', '.join(better)} beat it clearly ({worse} of {count} tests {were} "
            "clearly worse)"
            if better
            else f"none of the momentum and RSI rules beat it clearly ({worse} of {count} tests {were} clearly "
            f"worse, the rest "
            "within noise)"
        )
        out.append(
            f'Do simple up/down rules work? Always calling "up" was right {pct(always_up["1"]["hit_rate"], 1)} of the '
            f"time 1 day ahead and {pct(always_up['5']['hit_rate'], 1)} 5 days ahead (a coin flip is 50%), and {tail}."
        )
    return out


def limitations(cfg: dict, ranges_config: dict, summary: dict) -> list[str]:
    """What the replay cannot reproduce, plus warnings for switched-on inputs."""
    market, out = cfg["market"], list(LIMITATIONS)
    index_cue = cfg.get("index_cue") or {}
    if index_cue.get("symbol") and range_switches.enabled(ranges_config, "beta_split", market):
        enabled_horizons = [
            horizon
            for horizon in ranges_config["horizons"]
            if range_switches.enabled(ranges_config, "beta_split", market, horizon)
        ]
        if index_cue.get("beta", 1.0) == "fit":
            out.append(
                f"Index cue (beta split, on for {', '.join(f'{horizon}d' for horizon in enabled_horizons)}): "
                f"{index_cue['symbol']}'s last session "
                "return before the next session x the beta fitted on bars up to d, as the live pre-open quote gives it."
            )
        else:
            out.append(
                f"Index cue {index_cue['symbol']} (quoted before the open) has no stored history: the beta split has "
                f"no "
                "index cue in the replay."
            )
    mism = {
        horizon: value.get("calendar_mismatch", 0)
        for horizon, value in summary["horizons"].items()
        if value.get("calendar_mismatch")
    }
    if mism:
        out.append(
            "Ranges are scored on the close h stored bars later. On "
            + ", ".join(f"{rows} {horizon}d" for horizon, rows in mism.items())
            + " rows that bar is not the exchange-calendar target date a live range names (bars on special "
            "sessions such as India's Muhurat trading, or a session without a bar)."
        )
    if (ranges_config.get("relation_widen") or {}).get("enabled") or float(
        ranges_config.get("activist_13d_factor", 1.0)
    ) != 1.0:
        out.append("WARNING: relationship or smart-money widening is switched on but cannot be replayed.")
    if range_switches.enabled(ranges_config, "implied_vol", market):
        out.append("WARNING: implied_vol is switched on but cannot be replayed; replayed ranges omit it.")
    return out
