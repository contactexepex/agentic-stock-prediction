"""The rule replay's self-contained HTML page: charts, tables and tiles."""

from __future__ import annotations

import math
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.constants.replay import CI_NOTE, MIN_MONTH_DAYS, RSI_HIGH, RSI_LOW, SCORE_NOTE
from marketbrief.constants.replay_page import CSS, JS
from marketbrief.replay.html_parts import esc, fmt_p, legend, scaled_text
from marketbrief.replay.rule_replay.aci_compare import aci_table, held_out_html


def svg_calibration(summary: dict) -> str:
    width, height, left, right, top, bottom = 640, 360, 48, 16, 16, 40
    plot_width, plot_height = width - left - right, height - top - bottom
    scale_x = lambda tick: left + tick * plot_width  # noqa: E731
    scale_y = lambda tick: top + (1 - tick) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Stated vs actual coverage">']
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1):
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(tick):.1f}" y2="{scale_y(tick):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(tick) + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
        out.append(
            f'<text x="{scale_x(tick):.1f}" y="{height - bottom + 16}" text-anchor="middle">{int(tick * 100)}%</text>'
        )
    out.append(
        f'<text x="{left + plot_width / 2}" y="{height - 4}" text-anchor="middle">stated coverage (what the range '
        f"promises)</text>"
    )
    out.append(
        f'<line x1="{scale_x(0)}" y1="{scale_y(0)}" x2="{scale_x(1)}" y2="{scale_y(1)}" stroke="var(--muted)" '
        f'stroke-dasharray="4 4"/>'
    )
    for horizon, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        pts = summary["horizons"].get(horizon, {}).get("calibration") or []
        if not pts:
            continue
        path = " ".join(
            f"{'M' if index == 0 else 'L'}{scale_x(point['stated']):.1f},{scale_y(point['actual']):.1f}"
            for index, point in enumerate(pts)
        )
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for point in pts:
            radius = 6 if point["published"] else 4
            tipx = (
                f"{horizon}-day {'published ' if point['published'] else ''}{int(point['stated'] * 100)}% "
                f"range: "
                f"actual {scaled_text(point['actual'])}"
            )
            out.append(
                f'<circle class="mark" cx="{scale_x(point["stated"]):.1f}" '
                f'cy="{scale_y(point["actual"]):.1f}" r="{radius}" fill="{color}" '
                f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>'
            )
    out.append("</svg>")
    return "".join(out)


def svg_regime(summary: dict) -> str:
    regs = REGIME_ORDER
    width, height, left, right, top, bottom = 640, 300, 48, 16, 16, 44
    plot_width, plot_height = width - left - right, height - top - bottom
    scale_y = lambda tick: top + (1 - tick) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="80% coverage by regime">']
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1):
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(tick):.1f}" y2="{scale_y(tick):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(tick) + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
    slot = plot_width / len(regs)
    bar_width = min(24, slot / 3)
    for index, name in enumerate(regs):
        center_x = left + slot * (index + 0.5)
        days = summary.get("regime_days", {}).get(name, 0)
        out.append(f'<text x="{center_x:.1f}" y="{height - bottom + 16}" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{center_x:.1f}" y="{height - bottom + 30}" text-anchor="middle">{days} days</text>')
        for inner_index, (horizon, color) in enumerate((("1", "var(--s1)"), ("5", "var(--s2)"))):
            regime_stats = summary["horizons"].get(horizon, {}).get("by_regime", {}).get(name)
            if not regime_stats or not regime_stats.get("n"):
                continue
            tick = regime_stats["cover80"]
            bar_left = center_x + (inner_index - 1) * (bar_width + 2) + 1
            bottom_y, top_y = scale_y(0), scale_y(tick)
            bar_height = max(bottom_y - top_y, 0.5)
            corner_radius = min(4, bar_height)
            bar_path = (
                f"M{bar_left:.1f},{bottom_y:.1f} L{bar_left:.1f},{top_y + corner_radius:.1f} Q{bar_left:.1f},{top_y:.1f} "
                f"{bar_left + corner_radius:.1f},{top_y:.1f} "
                f"L{bar_left + bar_width - corner_radius:.1f},{top_y:.1f} Q{bar_left + bar_width:.1f},{top_y:.1f} "
                f"{bar_left + bar_width:.1f},{top_y + corner_radius:.1f} L{bar_left + bar_width:.1f},{bottom_y:.1f} Z"
            )
            tipx = f"{name}, {horizon}-day: 80% coverage {scaled_text(tick)} over {regime_stats['n']:,} ranges ({regime_stats['days']} days)"
            out.append(f'<path class="mark" d="{bar_path}" fill="{color}" data-tip="{esc(tipx)}"/>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0.8):.1f}" y2="{scale_y(0.8):.1f}" '
        f'stroke="var(--ink2)" stroke-dasharray="4 4"/>'
    )
    out.append(f'<text x="{left + 4}" y="{scale_y(0.8) - 5:.1f}" text-anchor="start">promise 80%</text>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0):.1f}" y2="{scale_y(0):.1f}" stroke="var(--axis)"/>'
    )
    out.append("</svg>")
    return "".join(out)


def svg_time(summary: dict) -> str:
    months = sorted(
        {
            month
            for horizon in ("1", "5")
            for month, value in summary["horizons"].get(horizon, {}).get("by_month", {}).items()
            if value.get("days", 0) >= MIN_MONTH_DAYS
        }
    )
    if not months:
        return ""
    width, height, left, right, top, bottom = 640, 300, 48, 30, 16, 36
    plot_width, plot_height = width - left - right, height - top - bottom
    vals = [
        value["cover80"]
        for horizon in ("1", "5")
        for value in summary["horizons"].get(horizon, {}).get("by_month", {}).values()
        if value.get("days", 0) >= MIN_MONTH_DAYS
    ]
    lower = max(0.0, math.floor(min(vals + [0.6]) * 10) / 10)
    scale_x = lambda index: left + (index + 0.5) * plot_width / len(months)  # noqa: E731
    scale_y = lambda value: top + (1 - (value - lower) / (1 - lower)) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="80% coverage by month">']
    value = lower
    while value <= 1.0001:
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(value):.1f}" y2="{scale_y(value):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(value) + 4:.1f}" text-anchor="end">{round(value * 100)}%</text>')
        value += 0.1
    step = max(1, len(months) // 8)
    for index, month in enumerate(months):
        if index % step == 0:
            out.append(f'<text x="{scale_x(index):.1f}" y="{height - bottom + 16}" text-anchor="middle">{month}</text>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0.8):.1f}" y2="{scale_y(0.8):.1f}" '
        f'stroke="var(--ink2)" stroke-dasharray="4 4"/>'
    )
    for horizon, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        by_month = summary["horizons"].get(horizon, {}).get("by_month", {})
        pts = [
            (index, by_month[month])
            for index, month in enumerate(months)
            if by_month.get(month, {}).get("days", 0) >= MIN_MONTH_DAYS
        ]
        if not pts:
            continue
        path = " ".join(
            f"{'M' if point_index == 0 else 'L'}{scale_x(index):.1f},{scale_y(stats['cover80']):.1f}"
            for point_index, (index, stats) in enumerate(pts)
        )
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for index, stats in pts:
            tipx = (
                f"{months[index]}, {horizon}-day: 80% coverage {scaled_text(stats['cover80'])} ({stats['n']:,} ranges)"
            )
            out.append(
                f'<circle class="mark" cx="{scale_x(index):.1f}" cy="{scale_y(stats["cover80"]):.1f}" r="4" '
                f'fill="{color}" '
                f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>'
            )
    out.append("</svg>")
    return "".join(out)


def range_table(groups: dict, label: str) -> str:
    rows = []
    for key, (one_day, five_day) in groups.items():
        cells = [esc(key)]
        for stats in (one_day, five_day):
            if stats and stats.get("n"):
                cells += [
                    f"{stats['n']:,}",
                    scaled_text(stats["cover50"]),
                    scaled_text(stats["cover80"]),
                    f"{stats['width80_pct']:.2f}%",
                    f"{stats['score80']:.2f}",
                    f"{stats.get('naive_score80', 0) or 0:.2f}",
                ]
            else:
                cells += ["0", "", "", "", "", ""]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    head = (
        f"<tr><th>{esc(label)}</th>"
        + "".join(
            f"<th>{horizon_label} n</th><th>{horizon_label} 50%</th><th>{horizon_label} 80%</th><th>{horizon_label} "
            f"80% width</th>"
            f"<th>{horizon_label} score</th><th>{horizon_label} naive score</th>"
            for horizon_label in ("1d", "5d")
        )
        + "</tr>"
    )
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def html_report(cfg: dict, stats: dict) -> str:
    by_horizon = stats["horizons"]
    one_day, five_day = by_horizon.get("1", {}).get("overall", {}), by_horizon.get("5", {}).get("overall", {})
    always_up = {horizon: (stats["baselines"].get(horizon) or {}).get("always_up", {}) for horizon in ("1", "5")}

    def tile(label, value, confidence_interval, note):
        span = (
            ""
            if not confidence_interval or confidence_interval[0] is None
            else f"95% interval {scaled_text(confidence_interval[0])} to {scaled_text(confidence_interval[1])}"
        )
        return (
            f'<div class="card tile"><div class="l">{esc(label)}</div><div class="v">{scaled_text(value)}</div>'
            f'<div class="n">{esc(note)}</div><div class="n">{span}</div></div>'
        )

    tiles = "".join(
        [
            tile(
                "1-day 80% ranges that held",
                one_day.get("cover80"),
                one_day.get("cover80_ci"),
                f"promise 80% · {one_day.get('n', 0):,} ranges",
            ),
            tile(
                "5-day 80% ranges that held",
                five_day.get("cover80"),
                five_day.get("cover80_ci"),
                f"promise 80% · {five_day.get('n', 0):,} ranges",
            ),
            tile(
                "“Always up” right, 1 day ahead",
                always_up["1"].get("hit_rate"),
                always_up["1"].get("ci95"),
                "a coin flip is 50%",
            ),
            tile(
                "“Always up” right, 5 days ahead",
                always_up["5"].get("hit_rate"),
                always_up["5"].get("ci95"),
                "a coin flip is 50%",
            ),
        ]
    )
    top = "".join(
        f'<p class="answer"><b>{esc(item.split("? ", 1)[0])}?</b> {esc(item.split("? ", 1)[1])}</p>'
        if "? " in item
        else f'<p class="answer">{esc(item)}</p>'
        for item in stats.get("top", [])
    )
    summary = "".join(f"<li>{esc(item)}</li>" for item in stats["summary"])
    pair = lambda key: {
        group_name: (
            by_horizon.get("1", {}).get(key, {}).get(group_name),
            by_horizon.get("5", {}).get(key, {}).get(group_name),
        )  # noqa: E731
        for group_name in dict.fromkeys(
            list(by_horizon.get("1", {}).get(key, {})) + list(by_horizon.get("5", {}).get(key, {}))
        )
    }
    brows = []
    for horizon in ("1", "5"):
        for name, baseline in (stats["baselines"].get(horizon) or {}).items():
            difference, (dlo, dhi) = baseline["diff_vs_always_up"], baseline["diff_ci95"]
            difference_text = "" if name == "always_up" or difference is None else f"{100 * difference:+.1f} pts"
            vs_ci = "" if name == "always_up" or dlo is None else f"{100 * dlo:+.1f} to {100 * dhi:+.1f}"
            brows.append(
                f"<tr><td>{esc(baseline['label'])}</td><td>{horizon}d</td><td>{baseline['calls']:,}</td><td>{scaled_text(baseline['hit_rate'])}</td>"
                f"<td>{scaled_text(baseline['ci95'][0])} to "
                f"{scaled_text(baseline['ci95'][1])}</td><td>{esc(fmt_p(baseline['p_vs_50']))}</td>"
                f"<td>{difference_text}</td><td>{vs_ci}</td></tr>"
            )
    sector = {ticker: ticker_config.get("sector") or "Other" for ticker, ticker_config in cfg["tickers"].items()}
    trows = []
    for ticker in sorted(cfg["tickers"]):
        one_day_stats = by_horizon.get("1", {}).get("by_ticker", {}).get(ticker, {})
        five_day_stats = by_horizon.get("5", {}).get("by_ticker", {}).get(ticker, {})
        if not one_day_stats.get("n") and not five_day_stats.get("n"):
            continue
        cell = lambda row, field: scaled_text(row.get(field)) if row.get("n") else ""  # noqa: E731
        num = lambda row, field: f"{row[field]:.2f}" if row.get("n") and row.get(field) is not None else ""  # noqa: E731
        trows.append(
            f'<tr data-sector="{esc(sector[ticker])}"><td>{esc(ticker)}</td><td>{esc(sector[ticker])}</td>'
            f"<td>{one_day_stats.get('n', 0):,}</td><td>{cell(one_day_stats, 'cover50')}</td><td>{cell(one_day_stats, 'cover80')}</td>"
            f"<td>{num(one_day_stats, 'score80')}</td><td>{num(one_day_stats, 'naive_score80')}</td>"
            f"<td>{cell(five_day_stats, 'cover50')}</td><td>{cell(five_day_stats, 'cover80')}</td><td>{num(five_day_stats, 'score80')}</td>"
            f"<td>{num(five_day_stats, 'naive_score80')}</td></tr>"
        )
    opts = "".join(f'<option value="{esc(item)}">{esc(item)}</option>' for item in sorted(set(sector.values())))
    lim = "".join(f"<li>{esc(item)}</li>" for item in stats["limitations"])
    inputs = "; ".join(
        f"{horizon}d: " + (", ".join(input_name for input_name, value in enabled_inputs.items() if value) or "none")
        for horizon, enabled_inputs in stats["settings"]["inputs"].items()
    )
    dash = '<span><span class="dash"></span>perfect calibration</span>'
    tgt = '<span><span class="dash"></span>promise 80%</span>'
    score_note = f'<p class="note">{esc(SCORE_NOTE)}</p>'
    index_cue = cfg.get("index_cue") or {}
    replayed_cue = (
        index_cue.get("symbol")
        and index_cue.get("beta", 1.0) == "fit"
        and any(enabled_inputs.get("beta_split") for enabled_inputs in stats["settings"]["inputs"].values())
    )
    cue_name = (cfg["symbols"].get(index_cue.get("symbol")) or {}).get("name") or index_cue.get("symbol")
    cue_txt = f", and the {esc(cue_name)} as an overnight cue" if replayed_cue else ""
    aci_settings = stats["settings"].get("aci") or {}
    aci_block = (
        ""
        if not stats.get("aci_comparison")
        else (
            '<h2>Adaptive bands (ACI): before and after</h2><div class="card">'
            f"<p>This page shows the ranges with Adaptive Conformal Inference on (gamma {aci_settings.get('gamma')}, at most "
            f"{aci_settings.get('max_shift')} from the target miss rate, after {aci_settings.get('min_history')} scored days, "
            f"{'one rate per regime' if aci_settings.get('by_regime') else 'one rate per horizon and band'}): each day the "
            f"share "
            "of past ranges that missed moves the band's quantile level. The table compares the same rows with fixed "
            "bands "
            "(before) and ACI (after). Width and scores in % of the price, lower is better. These settings may have "
            "been chosen on this same window: in-sample unless the held-out check below agrees.</p>"
            f"{aci_table(stats['aci_comparison'])}{held_out_html(stats.get('aci_held_out'))}</div>"
        )
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Historical Replay \
{esc(cfg["market"].upper())}</title>
<style>{CSS}</style></head><body><main>
<h1>Historical replay: {esc(cfg.get("name", cfg["market"]))}</h1>
<p class="sub">Every past trading day from {esc(stats["start"])} to {esc(stats["end"])}, the price ranges were rebuilt \
using only what
was known before the next session opened (prices up to that day's close, scheduled events{cue_txt}), then checked
against the actual close. Rule-based parts only, no AI. Research only,
not investment advice.</p>
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">An 80% range promises to contain the later closing price 8 times in 10. {esc(CI_NOTE)}</p>
<h2>Do the ranges hold as often as they promise?</h2>
<div class="card">{legend(dash)}{svg_calibration(stats)}
<p class="caption">Look for: points above the dashed line mean the ranges held more often than promised (too wide); \
below it,
too narrow. The large points are the published 50% and 80% ranges.</p></div>
<h2>Coverage by market mood (regime)</h2>
<div class="card">{legend(tgt)}{svg_regime(stats)}
<p class="caption">Look for: bars well above the dashed 80% line are market moods (CALM, TRENDING, EVENT_HEAVY around
scheduled events, UNSTABLE in stress) where the ranges are wider than needed.</p></div>
<h2>Coverage over time</h2>
<div class="card">{legend(tgt)}{svg_time(stats)}
<p class="caption">Look for: long runs below the 80% line, which would mean the ranges fell behind in some periods
(months with fewer than {MIN_MONTH_DAYS} days are left out).</p></div>
{aci_block}<h2>More detail</h2>
<details><summary>All findings, with every number</summary>
<p class="note">{esc(CI_NOTE)} pts = percentage points. {esc(SCORE_NOTE)}</p><ul \
class="summary">{summary}</ul></details>
<details><summary>Coverage by regime (table)</summary>{range_table(pair("by_regime"), "Regime")}{score_note}</details>
<details><summary>Earnings, market events and years</summary>
<p>Coverage split by whether a company earnings report or a major market event fell inside the horizon, and by year.</p>
{range_table(pair("by_earnings"), "Earnings")}
{range_table(pair("by_major_event"), "Market event")}
{range_table(pair("by_year"), "Year")}{score_note}</details>
<details><summary>Direction baselines (simple up/down rules, not the product's forecasts)</summary>
<p>Simple rules the AI forecaster must beat later. A call is right if the close h days later moved in the called \
direction
(no change counts as wrong). {esc(CI_NOTE)} "vs always-up" compares each rule with always-up on the same stocks and \
days,
in pts (percentage points).</p>
<div class="scroll"><table><thead><tr><th>Rule</th><th>Horizon</th><th>Calls</th><th>Hit rate</th><th>95% interval</th>
<th>p vs 50% (if independent)</th><th>vs always-up</th><th>95% \
interval</th></tr></thead><tbody>{"".join(brows)}</tbody></table></div>
<p class="note">The p-value is an exact binomial test that treats every call as independent; stocks move together, so it
overstates the evidence. Trust the 95% intervals: a rule only beats 50% (or always-up) if its interval stays above it.
Momentum: call the sign of the last 1 or 5 days' return. RSI mean reversion: RSI(14) below {RSI_LOW:g} calls up, above
{RSI_HIGH:g} calls down, otherwise no call (defined in replay.py; indicators.py computes RSI but has no \
signal).</p></details>
<details><summary>Per ticker</summary>
<p>Filter by sector: <select id="sector"><option value="all">All sectors</option>{opts}</select></p>
<div class="scroll"><table id="tickers"><thead><tr><th>Ticker</th><th>Sector</th><th>n (1d)</th><th>1d 50%</th><th>1d \
80%</th>
<th>1d score</th><th>1d naive</th><th>5d 50%</th><th>5d 80%</th><th>5d score</th><th>5d naive</th></tr></thead>
<tbody>{"".join(trows)}</tbody></table></div>{score_note}</details>
<details><summary>Method and limits</summary>
<p>Each as-of day uses only bars up to its close and events as known pre-open the next session, built with the same \
code as
the live ranges (marketbrief/analytics/range_math.py, the range-input modules, backtest.py helpers, regime.py). Range \
inputs switched on
(config/ranges.yaml): {esc(inputs)}. Data: {esc(stats["data"]["first_bar"])} to {esc(stats["data"]["last_bar"])},
{stats["data"]["tickers"]} tickers, {stats["data"]["earnings_events"]} earnings and {stats["data"]["dividends"]} \
dividend events.
Computed {esc(stats["computed_at"])}, runtime {stats["runtime_s"]:.0f} s.</p><ul>{lim}</ul></details>
</main><div id="tip" class="tip"></div><script>{JS}</script></body></html>"""
