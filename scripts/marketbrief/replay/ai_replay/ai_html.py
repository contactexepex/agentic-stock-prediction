"""The AI replay's score page: charts, tiles and tables per leakage group."""

from __future__ import annotations

import html
from marketbrief.constants import replay
from marketbrief.constants import replay_page
from marketbrief.replay import html_parts
from marketbrief.constants.ai_replay import CONTAMINATED, FAIR
from marketbrief.replay.ai_replay.summaries import pct


def svg_hit_bars(summary: dict) -> str:
    """Bar chart of the hit rate of the AI and of always-up by horizon."""
    groups = [("1-day", summary["by_horizon"]["1"]), ("5-day", summary["by_horizon"]["5"]), ("All", summary["overall"])]
    width, height, left, right, top, bottom = 640, 300, 48, 16, 16, 44
    plot_width, plot_height = width - left - right, height - top - bottom
    scale_y = lambda tick: top + (1 - tick) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Hit rate: AI vs always-up">']
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1):
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(tick):.1f}" y2="{scale_y(tick):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(tick) + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
    slot, bar_width = plot_width / len(groups), 28
    for index, (name, group) in enumerate(groups):
        center_x = left + slot * (index + 0.5)
        out.append(f'<text x="{center_x:.1f}" y="{height - bottom + 16}" text-anchor="middle">{name}</text>')
        out.append(
            f'<text x="{center_x:.1f}" y="{height - bottom + 30}" text-anchor="middle">{group.get("n", 0)} calls</text>'
        )
        if not group.get("n"):
            continue
        for inner_index, (key, color, label) in enumerate(
            (("ai", "var(--s1)", "AI"), ("au", "var(--s2)", "Always up"))
        ):
            series_stats = group if key == "ai" else group["always_up"]
            tick = series_stats["hit_rate"]
            bar_left = center_x + (inner_index - 1) * (bar_width + 2) + 1
            bottom_y, top_y = scale_y(0), scale_y(tick)
            bar_height = max(bottom_y - top_y, 0.5)
            corner_radius = min(4, bar_height)
            bar_path = (
                f"M{bar_left:.1f},{bottom_y:.1f} L{bar_left:.1f},{top_y + corner_radius:.1f} "
                f"Q{bar_left:.1f},{top_y:.1f} "
                f"{bar_left + corner_radius:.1f},{top_y:.1f} "
                f"L{bar_left + bar_width - corner_radius:.1f},{top_y:.1f} Q{bar_left + bar_width:.1f},{top_y:.1f} "
                f"{bar_left + bar_width:.1f},{top_y + corner_radius:.1f} L{bar_left + bar_width:.1f},{bottom_y:.1f} Z"
            )
            confidence_interval = series_stats["ci95"]
            tip = (
                f"{name}, {label}: right {pct(tick)} of {series_stats['n']} (95% interval "
                f"{pct(confidence_interval[0])} to "
                f"{pct(confidence_interval[1])})"
            )
            out.append(f'<path class="mark" d="{bar_path}" fill="{color}" data-tip="{html.escape(tip, quote=True)}"/>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0.5):.1f}" y2="{scale_y(0.5):.1f}" '
        f'stroke="var(--ink2)" stroke-dasharray="4 4"/>'
    )
    out.append(f'<text x="{left + 4}" y="{scale_y(0.5) - 5:.1f}" text-anchor="start">coin flip</text>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0):.1f}" y2="{scale_y(0):.1f}" '
        f'stroke="var(--axis)"/></svg>'
    )
    return "".join(out)


def svg_calibration(summary: dict) -> str:
    """Chart of stated confidence against the actual hit rate per band."""
    scored_bands = [band for band in summary["by_band"] if band.get("n")]
    width, height, left, right, top, bottom = 640, 340, 48, 16, 16, 40
    plot_width, plot_height = width - left - right, height - top - bottom
    lo_x, hi_x = 0.45, 0.95
    scale_x = lambda tick: left + (tick - lo_x) / (hi_x - lo_x) * plot_width  # noqa: E731
    scale_y = lambda tick: top + (1 - tick) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Stated confidence vs actual hit rate">']
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1):
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(tick):.1f}" y2="{scale_y(tick):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(tick) + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
    for tick in (0.5, 0.6, 0.7, 0.8, 0.9):
        out.append(
            f'<text x="{scale_x(tick):.1f}" y="{height - bottom + 16}" text-anchor="middle">{int(tick * 100)}%</text>'
        )
    out.append(
        f'<text x="{left + plot_width / 2}" y="{height - 4}" text-anchor="middle">stated confidence (average in each '
        f"band)</text>"
    )
    out.append(
        f'<line x1="{scale_x(lo_x):.1f}" y1="{scale_y(lo_x):.1f}" x2="{scale_x(hi_x):.1f}" y2="{scale_y(hi_x):.1f}" '
        'stroke="var(--muted)" stroke-dasharray="4 4"/>'
    )
    for band in scored_bands:
        x_position, y_position = scale_x(band["stated"]), scale_y(band["hit_rate"])
        lower, upper = band["ci95"]
        out.append(
            f'<line x1="{x_position:.1f}" x2="{x_position:.1f}" y1="{scale_y(lower):.1f}" y2="{scale_y(upper):.1f}" '
            f'stroke="var(--s1)" stroke-width="2"/>'
        )
        tip = (
            f"Band {band['band']}: stated {pct(band['stated'])}, right {pct(band['hit_rate'])} of {band['n']} calls "
            f"(95% interval {pct(lower)} to {pct(upper)})"
        )
        out.append(
            f'<circle class="mark" cx="{x_position:.1f}" cy="{y_position:.1f}" r="6" fill="var(--s1)" '
            f'stroke="var(--surface)" '
            f'stroke-width="2" data-tip="{html.escape(tip, quote=True)}"/>'
        )
        out.append(
            f'<text x="{x_position + 10:.1f}" y="{y_position + 4:.1f}" text-anchor="start">{band["n"]} calls</text>'
        )
    out.append("</svg>")
    return "".join(out)


def points_text(value) -> str:
    """A share as signed percentage points."""
    return "" if value is None else f"{100 * value:+.1f} pts"


def signed_pct(value) -> str:
    """A share as a signed percent with two decimals."""
    return "" if value is None else f"{100 * value:+.2f}%"


def html_page(summary: dict) -> str:
    """The score page: the fair group (as-of dates after the training cutoff) is the result; the
    contaminated group, if any, is a separate, labelled section scored on its own rows only."""
    escape_html = html_parts.escape_html
    fair, contaminated = summary[FAIR], summary[CONTAMINATED]
    cut = escape_html(summary["model_training_cutoff"])
    banner = (
        f'<p class="note"><b>Fair test</b> = an as-of date after {cut}, the model\'s training cutoff '
        "(<code>model_training_cutoff</code> in config/settings.yaml; ForecastBench leakage rule). Dates on or "
        f"before it are <b>contaminated</b>: the model may have seen what happened. The two groups are scored "
        f"separately and never pooled: {fair['n_days']} fair and {contaminated['n_days']} contaminated days.</p>"
    )
    if fair["n_days"]:
        sub = (
            f'<p class="sub">On {fair["n_days"]} past trading days after the model\'s training data '
            f"({escape_html(fair['dates'][0])} to {escape_html(fair['dates'][-1])}), the AI forecaster saw only what "
            f"was known "
            f"before the "
            "next session opened, and its up/down calls were checked against the actual closes. Research only, not "
            "investment advice.</p>"
        )
        body = group_html(fair)
    else:
        sub = (
            '<p class="sub">No fair-test day is recorded yet, so there is no fair result. Research only, not '
            "investment advice.</p>"
        )
        body = ""
    if contaminated["n_days"]:
        body += (
            f'<section class="contaminated"><h2>Contaminated dates (on or before {cut}): not a fair test</h2>'
            f'<p class="note bad">CONTAMINATED: {contaminated["n_days"]} as-of dates '
            f"({escape_html(contaminated['dates'][0])} to "
            f"{escape_html(contaminated['dates'][-1])}) fall inside the model's training period, so it may have seen "
            f"these "
            f"prices. "
            "They are scored on their own below, never pooled with the fair result.</p>"
            f"{group_html(contaminated)}</section>"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Replay \
{escape_html(summary["market"].upper())}</title>
<style>{replay_page.CSS}</style></head><body><main>
<h1>AI forecaster replay: {escape_html(summary.get("name") or summary["market"])}</h1>
{sub}{banner}{body}
</main><div id="tip" class="tip"></div><script>{replay_page.JS}</script></body></html>"""


def group_html(group: dict) -> str:
    """One leakage group's results (fair or contaminated): answers, tiles, charts and detail tables."""
    escape_html = html_parts.escape_html
    lab = group["test"]
    overall, by_horizon, abstention = group["overall"], group["by_horizon"], group["abstention"]

    def tile(label, stats, note):
        """A tile with a hit rate, its note and its 95% interval."""
        hit_rate = stats.get("hit_rate") if stats else None
        confidence_interval = (stats or {}).get("ci95") or [None, None]
        span = (
            ""
            if confidence_interval[0] is None
            else f"95% interval {pct(confidence_interval[0])} to {pct(confidence_interval[1])}"
        )
        return (
            f'<div class="card tile"><div class="l">{escape_html(label)}</div><div class="v">{pct(hit_rate)}</div>'
            f'<div class="n">{escape_html(note)}</div><div class="n">{span}</div></div>'
        )

    tiles = "".join(
        [
            tile(
                "AI calls right, 5 days ahead",
                by_horizon["5"],
                f"{by_horizon['5'].get('n', 0)} scored calls · coin flip 50%",
            ),
            tile(
                "AI calls right, 1 day ahead",
                by_horizon["1"],
                f"{by_horizon['1'].get('n', 0)} scored calls · coin flip 50%",
            ),
            tile(
                "“Always up” right on the same calls", overall.get("always_up") or {}, "same stocks, days and horizons"
            ),
            f'<div class="card tile"><div class="l">Stock-days with no call</div>'
            f'<div class="v">{pct(abstention["any"]["abstention_rate"])}</div><div class="n">abstained on '
            f"{abstention['any']['slots'] - abstention['any']['ticker_days_with_a_call']} of "
            f"{abstention['any']['slots']} stock-days</div>"
            f'<div class="n">abstaining is allowed and often right</div></div>',
        ]
    )
    top = "".join(
        f'<p class="answer"><b>{escape_html(sentence.split("? ", 1)[0])}?</b> '
        f'{escape_html(sentence.split("? ", 1)[1])}</p>'
        for sentence in group["top"]
    )
    hrows = []
    for name, horizon_stats in (("1-day", by_horizon["1"]), ("5-day", by_horizon["5"]), ("All", overall)):
        if not horizon_stats.get("n"):
            hrows.append(f"<tr><td>{name}</td><td>0</td>" + "<td></td>" * 6 + "</tr>")
            continue
        difference = horizon_stats["diff_vs_always_up"]
        hrows.append(
            f"<tr><td>{name}</td><td>{horizon_stats['n']}</td><td>{pct(horizon_stats['hit_rate'])}</td>"
            f"<td>{pct(horizon_stats['ci95'][0])} to "
            f"{pct(horizon_stats['ci95'][1])}</td><td>{escape_html(html_parts.p_value_text(horizon_stats['p_vs_50']))}</td>"
            f"<td>{pct(horizon_stats['mean_confidence'])}</td><td>{pct(horizon_stats['always_up']['hit_rate'])}</td>"
            f"<td>{points_text(difference['pts'])}</td></tr>"
        )
    rrows = []
    for name, horizon_stats in (("1-day", by_horizon["1"]), ("5-day", by_horizon["5"]), ("All", overall)):
        for stats in (horizon_stats.get("rules") or {}).values():
            if not stats.get("n"):
                continue
            rrows.append(
                f"<tr><td>{escape_html(stats['label'])}</td><td>{name}</td><td>{stats['n']}</td><td>{pct(stats['hit_rate'])}</td>"
                f"<td>{pct(stats['ci95'][0])} to "
                f"{pct(stats['ci95'][1])}</td><td>{pct(stats['ai_hit_rate_same_rows'])}</td></tr>"
            )
    brows = "".join(
        f"<tr><td>{band['band']}</td><td>{band.get('n', 0)}</td><td>{pct(band.get('stated'))}</td>"
        f"<td>{pct(band.get('hit_rate'))}</td><td>"
        f"{'' if not band.get('n') else pct(band['ci95'][0]) + ' to ' + pct(band['ci95'][1])}</td></tr>"
        for band in group["by_band"]
    )
    arows = "".join(
        f"<tr><td>{key}</td><td>{slot_stats['slots']}</td>"
        f"<td>{slot_stats.get('calls', slot_stats.get('ticker_days_with_a_call'))}</td>"
        f"<td>{pct(slot_stats['abstention_rate'])}</td></tr>"
        for key, slot_stats in abstention.items()
        if isinstance(slot_stats, dict)
    )
    drows = "".join(
        f"<tr><td>{day_row['date']}</td><td>{lab}</td><td>{day_row['citable_ids']}</td><td>{day_row['calls']}</td><td>{day_row['rejected']}</td>"
        f"<td>{day_row['scored']}</td><td>{day_row['hits']}</td></tr>"
        for day_row in group["per_day"]
    )
    crows = "".join(
        f"<tr><td>{escape_html(str(call['date']))}</td><td>{escape_html(call['test'])}</td><td>{escape_html(call['ticker'])}</td><td>{call['h']}d</td><td>{escape_html(call['direction'])}</td>"
        f"<td>{call['confidence']:.2f}</td><td>{escape_html(call['status'])}</td>"
        f"<td>{signed_pct(call.get('ret'))}</td>"
        f"<td>{'' if call.get('hit') is None else ('right' if call['hit'] else 'wrong')}</td>"
        f"<td>{escape_html(', '.join(call.get('evidence_ids') or []))}</td></tr>"
        for call in group["calls"]
    )
    legend = (
        '<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>AI forecaster</span>'
        '<span><span class="sw" style="background:var(--s2)"></span>Always up (same calls)</span>'
        '<span><span class="dash"></span>coin flip 50%</span></div>'
    )
    tag = (
        f'<p class="note"><b>Group: {escape_html(lab)}</b> ({group["n_days"]} as-of days, {group["n_calls"]} calls); '
        "every number in this group uses only its own rows.</p>"
    )
    return f"""{tag}
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">A call is right if the close 1 or 5 trading days later moved the called way (no change counts as wrong).
95% interval = the span the true hit rate most likely lies in; with few calls it is wide.</p>
<h2>Was the AI right more often than “always up”?</h2>
<div class="card">{legend}{svg_hit_bars(group)}
<p class="caption">Look for: blue bars above both the dashed 50% line and the orange bar beside them. Bars that differ \
by
less than their 95% intervals (hover a bar) are within noise.</p></div>
<h2>Does its confidence mean what it says?</h2>
<div class="card"><div class="legend"><span><span class="sw" style="background:var(--s1)"></span>AI calls by \
confidence band
(line = 95% interval)</span><span><span class="dash"></span>perfect calibration</span></div>{svg_calibration(group)}
<p class="caption">Look for: points on the dashed line. Below it, calls stated with that confidence were right less \
often
than promised (overconfident); above it, more often.</p></div>
<h2>More detail</h2>
<details><summary>Hit rates by horizon (table)</summary><div \
class="scroll"><table><thead><tr><th>Horizon</th><th>Calls</th>
<th>Hit rate</th><th>95% interval</th><th>p vs 50%</th><th>Stated</th><th>Always up</th><th>AI vs always \
up</th></tr></thead>
<tbody>{"".join(hrows)}</tbody></table></div>
<p class="note">95% interval: Wilson binomial interval; p: exact two-sided binomial test vs 50%. Both treat calls as
independent; calls on the same day move together, so they overstate the evidence. "AI vs always up" is in percentage
points on the same calls (its 95% interval, clustered by date, is in the JSON).</p></details>
<details><summary>Simple rules on the same stocks and days</summary><div class="scroll"><table><thead><tr><th>Rule</th>
<th>Horizon</th><th>Rule calls</th><th>Rule hit rate</th><th>95% interval</th><th>AI hit rate on those \
calls</th></tr></thead>
<tbody>{
        "".join(rrows) or "<tr><td>no scored calls</td><td></td><td></td><td></td><td></td><td></td></tr>"
    }</tbody></table></div>
<p class="note">Rules from replay.py, on the ticker-days where the AI made a call: momentum (sign of the last 1 or 5 \
days'
return) and RSI(14) mean reversion (below {replay.RSI_LOW:g} up, above {replay.RSI_HIGH:g} down, else no \
call).</p></details>
<details><summary>Confidence bands (calibration)</summary><div \
class="scroll"><table><thead><tr><th>Band</th><th>Calls</th>
<th>Stated</th><th>Right</th><th>95% interval</th></tr></thead><tbody>{brows}</tbody></table></div>
<p class="note">Brier score (lower is better; 0.25 = always saying 50%): {overall.get("brier", "n/a")}.</p></details>
<details><summary>Abstention</summary><div \
class="scroll"><table><thead><tr><th>Horizon</th><th>Stock-days</th><th>Calls</th>
<th>No call</th></tr></thead><tbody>{arows}</tbody></table></div>
<p class="note">Stock-days count only tickers the rules allow a call on (not BLOCKED, no earnings within 1 \
day).</p></details>
<details><summary>Per sample day</summary><div class="scroll"><table><thead><tr><th>As-of \
date</th><th>Test</th><th>Citable ids</th>
<th>Calls</th><th>Rejected</th><th>Scored</th><th>Right</th></tr></thead><tbody>{drows}</tbody></table></div></details>
<details><summary>Every call</summary><div \
class="scroll"><table><thead><tr><th>As-of</th><th>Test</th><th>Ticker</th><th>Horizon</th>
<th>Call</th><th>Confidence</th><th>Status</th><th>Return</th><th>Result</th><th>Evidence</th></tr></thead>
<tbody>{crows}</tbody></table></div></details>
<details><summary>Method and limits</summary><ul>
<li>Each day was prepared by <code>scripts/ai_replay.py prepare</code>: prices up to that day's close, and filings,
announcements and other records only if public before the routine's pre-open start on the next session.</li>
<li>No news before live collection began, so calls could cite only SEC filings (US) or NSE announcements (India).</li>
<li>Scored on the real stored closes, {group["n_pending"]} calls still pending (target after the last stored bar).</li>
<li>Prompt versions: {escape_html(", ".join(group["prompt_versions"]) or "none")}.</li>
<li>A small sample: a dozen days per market cannot show a small edge; treat the result as a smoke \
test.</li></ul></details>"""
