"""Plain-language summary of a replay: headline lines, top sentences and limitations."""

from __future__ import annotations

from marketbrief.analytics import range_switches
from marketbrief.constants.replay import LIMITATIONS, SIGNALS
from marketbrief.replay.html_parts import horizon_keys
from marketbrief.utils.numbers import share_percent_text


def pct(share, decimals: int = 0) -> str:
    """A share as a whole percent by default (`k` decimals when given); 'n/a' when missing."""
    return share_percent_text(share, decimals)


def headline(_cfg: dict, summary: dict) -> list[str]:
    """The summary lines of a replay per horizon N+k: coverage, accuracy, regimes, tickers and baselines."""
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
            f"N+{horizon} ranges: the 80% band contained the exit close {pct(c80, 1)} of the time "
            f"(95% interval {pct(interval[0], 1)} to {pct(interval[1], 1)}; target 80%) and the 50% band "
            f"{pct(c50, 1)} (target 50%) over {overall['n']:,} ranges on {overall['days']} days: {verdict}."
        )
        if overall.get("naive_score80") is not None:
            better = overall["score80_same_rows"] < overall["naive_score80"]
            lines.append(
                f"N+{horizon} accuracy vs the naive range (last close +/- 20-day volatility): interval score "
                f"{overall['score80_same_rows']:.2f} vs {overall['naive_score80']:.2f} (lower is better), width "
                f"{overall['width80_pct']:.2f}% vs {overall['naive_width80_pct']:.2f}% of the price; the formula is "
                f"{'better' if better else 'not better'} than the naive range."
            )
        regs = {regime: value for regime, value in horizon_summary["by_regime"].items() if value.get("n", 0) >= 100}
        if regs:
            worst = min(regs.items(), key=lambda key_value: key_value[1]["cover80"])
            best = max(regs.items(), key=lambda key_value: key_value[1]["cover80"])
            lines.append(
                f"N+{horizon} by regime: 80% coverage ranges from {pct(worst[1]['cover80'], 1)} in {worst[0]} "
                f"to {pct(best[1]['cover80'], 1)} in {best[0]}."
            )
        earnings = horizon_summary["by_earnings"]["earnings in horizon"]
        if earnings.get("n"):
            lines.append(
                f"N+{horizon} with earnings inside the horizon: 80% coverage {pct(earnings['cover80'], 1)} "
                f"over {earnings['n']} ranges (no earnings: "
                f"{pct(horizon_summary['by_earnings']['no earnings'].get('cover80'), 1)})."
            )
        tick = {ticker: value for ticker, value in horizon_summary["by_ticker"].items() if value.get("n", 0) >= 50}
        low = sorted(tick.items(), key=lambda key_value: key_value[1]["cover80"])[:3]
        if low:
            lines.append(
                f"N+{horizon} lowest 80% coverage by ticker: "
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
            is_clear = interval[0] is not None and (interval[0] > 0 or interval[1] < 0)
            parts.append(
                f"{signal['label']} {pct(signal['hit_rate'], 1)} ({signal['calls']:,} calls, "
                f"{'+' if difference >= 0 else ''}{100 * difference:.1f} pts vs always-up on the same rows"
                f"{', clear' if is_clear else ', within noise'})"
            )
        lines.append(
            f"N+{horizon} direction baselines: always-up was right {pct(always_up['hit_rate'], 1)} of the time "
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


def span(values: list[tuple[str, float]]) -> str:
    """The spread of one rate over the horizons, short: '84.5% (N+1) to 86.3% (N+3)'; one value: '84.5% at N+1'."""
    if len(values) == 1:
        return f"{pct(values[0][1], 1)} at N+{values[0][0]}"
    low, high = min(values, key=lambda item: item[1]), max(values, key=lambda item: item[1])
    if pct(low[1], 1) == pct(high[1], 1):
        return f"{pct(low[1], 1)} at every horizon (N+{values[0][0]} to N+{values[-1][0]})"
    return f"{pct(low[1], 1)} (N+{low[0]}) to {pct(high[1], 1)} (N+{high[0]})"


def top_sentences(summary: dict) -> list[str]:
    """At most three short sentences for the top of the page, one per question (exact figures, one decimal),
    over every horizon N+k the replay scored (the lowest and highest horizon named)."""
    by_horizon, out = summary["horizons"], []
    scored = [horizon for horizon in horizon_keys(by_horizon) if by_horizon[horizon].get("overall", {}).get("n")]
    overall = {horizon: by_horizon[horizon]["overall"] for horizon in scored}
    if scored:
        coverage = [overall[horizon]["cover80"] for horizon in scored]
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
            "Do the ranges keep their promise? The 80% ranges contained the exit close "
            + span([(horizon, overall[horizon]["cover80"]) for horizon in scored])
            + " of the time, and the 50% ranges "
            + span([(horizon, overall[horizon]["cover50"]) for horizon in scored])
            + f", so overall they are {verdict}."
        )
    slices = [
        (horizon, name, stats)
        for horizon in scored
        for name, stats in coverage_groups(by_horizon.get(horizon, {})).items()
    ]
    if slices:
        highest = max(slices, key=lambda item: item[2]["cover80"])
        lowest = min(slices, key=lambda item: item[2]["cover80"])
        prep = lambda name: "in" if name.endswith("markets") else "with"  # noqa: E731
        upper_text = (
            f"N+{highest[0]} ranges were {'widest' if highest[2]['cover80'] > 0.8 else 'closest to 80%'} "
            f"{prep(highest[1])} {highest[1]} ({pct(highest[2]['cover80'], 1)} held)"
        )
        lower_text = (
            f"N+{lowest[0]} ranges were {'too narrow' if lowest[2]['cover80'] < 0.8 else 'closest to 80%'} "
            f"{prep(lowest[1])} {lowest[1]} ({pct(lowest[2]['cover80'], 1)})"
        )
        out.append(f"Where are they too wide or too narrow? {upper_text}; {lower_text}.")
    baselines = summary.get("baselines", {})
    called = [horizon for horizon in horizon_keys(baselines) if (baselines.get(horizon) or {}).get("always_up")]
    if called:
        better, worse, noise = [], 0, 0
        for horizon in called:
            for name in SIGNALS[1:]:
                item = (baselines.get(horizon) or {}).get(name)
                if not item or not item["calls"] or item["diff_ci95"][0] is None:
                    continue
                if item["diff_ci95"][0] > 0:
                    better.append(
                        f"{item['label']} N+{horizon} (+{100 * item['diff_vs_always_up']:.1f} percentage points)"
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
        rates = span([(horizon, baselines[horizon]["always_up"]["hit_rate"]) for horizon in called])
        out.append(
            f'Do simple up/down rules work? Always calling "up" was right {rates} of the time (a coin flip is 50%), '
            f"and {tail}."
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
                f"Index cue (beta split, on for {', '.join(f'N+{horizon}' for horizon in enabled_horizons)}): "
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
            "Ranges are scored on the close k + 1 stored bars after the as-of bar (the exit of N+k). On "
            + ", ".join(f"{rows} N+{horizon}" for horizon, rows in mism.items())
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
