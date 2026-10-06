"""The rule replay's self-contained HTML page: tiles, tables and the sections around the charts."""

from __future__ import annotations

from marketbrief.constants.replay import CI_NOTE, MIN_MONTH_DAYS, RSI_HIGH, RSI_LOW, SCORE_NOTE
from marketbrief.constants.replay_page import CSS, JS
from marketbrief.replay.html_parts import escape_html, p_value_text, legend, scaled_text
from marketbrief.replay.rule_replay.aci_compare import aci_table, held_out_html
from marketbrief.replay.rule_replay.rule_charts import svg_calibration, svg_regime, svg_time


def range_table(groups: dict, label: str) -> str:
    """A coverage table of grouped range summaries for 1 and 5 days."""
    rows = []
    for key, (one_day, five_day) in groups.items():
        cells = [escape_html(key)]
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
        f"<tr><th>{escape_html(label)}</th>"
        + "".join(
            f"<th>{horizon_label} n</th><th>{horizon_label} 50%</th><th>{horizon_label} 80%</th><th>{horizon_label} "
            f"80% width</th>"
            f"<th>{horizon_label} score</th><th>{horizon_label} naive score</th>"
            for horizon_label in ("1d", "5d")
        )
        + "</tr>"
    )
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def share_cell(stats: dict, field: str) -> str:
    """A share of the stats as a percent cell, empty when the group has no rows."""
    return scaled_text(stats.get(field)) if stats.get("n") else ""


def score_cell(stats: dict, field: str) -> str:
    """A score of the stats with two decimals, empty when missing."""
    return f"{stats[field]:.2f}" if stats.get("n") and stats.get(field) is not None else ""


def html_report(cfg: dict, stats: dict) -> str:
    """The replay's self-contained HTML page."""
    by_horizon = stats["horizons"]
    one_day, five_day = by_horizon.get("1", {}).get("overall", {}), by_horizon.get("5", {}).get("overall", {})
    always_up = {horizon: (stats["baselines"].get(horizon) or {}).get("always_up", {}) for horizon in ("1", "5")}

    def tile(label, value, confidence_interval, note):
        """A tile with a value, its 95% interval and a note."""
        span = (
            ""
            if not confidence_interval or confidence_interval[0] is None
            else f"95% interval {scaled_text(confidence_interval[0])} to {scaled_text(confidence_interval[1])}"
        )
        return (
            f'<div class="card tile"><div class="l">{escape_html(label)}</div><div class="v">{scaled_text(value)}</div>'
            f'<div class="n">{escape_html(note)}</div><div class="n">{span}</div></div>'
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
        f'<p class="answer"><b>{escape_html(item.split("? ", 1)[0])}?</b> {escape_html(item.split("? ", 1)[1])}</p>'
        if "? " in item
        else f'<p class="answer">{escape_html(item)}</p>'
        for item in stats.get("top", [])
    )
    summary = "".join(f"<li>{escape_html(item)}</li>" for item in stats["summary"])

    def pair(key):
        """The 1-day and 5-day summaries of each group of a section."""
        one_day_groups, five_day_groups = by_horizon.get("1", {}).get(key, {}), by_horizon.get("5", {}).get(key, {})
        return {
            group_name: (one_day_groups.get(group_name), five_day_groups.get(group_name))
            for group_name in dict.fromkeys(list(one_day_groups) + list(five_day_groups))
        }

    brows = []
    for horizon in ("1", "5"):
        for name, baseline in (stats["baselines"].get(horizon) or {}).items():
            difference, (dlo, dhi) = baseline["diff_vs_always_up"], baseline["diff_ci95"]
            difference_text = "" if name == "always_up" or difference is None else f"{100 * difference:+.1f} pts"
            vs_ci = "" if name == "always_up" or dlo is None else f"{100 * dlo:+.1f} to {100 * dhi:+.1f}"
            brows.append(
                f"<tr><td>{escape_html(baseline['label'])}</td><td>{horizon}d</td><td>{baseline['calls']:,}</td><td>{scaled_text(baseline['hit_rate'])}</td>"
                f"<td>{scaled_text(baseline['ci95'][0])} to "
                f"{scaled_text(baseline['ci95'][1])}</td><td>{escape_html(p_value_text(baseline['p_vs_50']))}</td>"
                f"<td>{difference_text}</td><td>{vs_ci}</td></tr>"
            )
    sector = {ticker: ticker_config.get("sector") or "Other" for ticker, ticker_config in cfg["tickers"].items()}
    trows = []
    for ticker in sorted(cfg["tickers"]):
        one_day_stats = by_horizon.get("1", {}).get("by_ticker", {}).get(ticker, {})
        five_day_stats = by_horizon.get("5", {}).get("by_ticker", {}).get(ticker, {})
        if not one_day_stats.get("n") and not five_day_stats.get("n"):
            continue
        trows.append(
            f'<tr data-sector="{escape_html(sector[ticker])}"><td>{escape_html(ticker)}</td>'
            f"<td>{escape_html(sector[ticker])}</td>"
            f"<td>{one_day_stats.get('n', 0):,}</td>"
            f"<td>{share_cell(one_day_stats, 'cover50')}</td><td>{share_cell(one_day_stats, 'cover80')}</td>"
            f"<td>{score_cell(one_day_stats, 'score80')}</td><td>{score_cell(one_day_stats, 'naive_score80')}</td>"
            f"<td>{share_cell(five_day_stats, 'cover50')}</td><td>{share_cell(five_day_stats, 'cover80')}</td>"
            f"<td>{score_cell(five_day_stats, 'score80')}</td>"
            f"<td>{score_cell(five_day_stats, 'naive_score80')}</td></tr>"
        )
    opts = "".join(
        f'<option value="{escape_html(item)}">{escape_html(item)}</option>' for item in sorted(set(sector.values()))
    )
    lim = "".join(f"<li>{escape_html(item)}</li>" for item in stats["limitations"])
    inputs = "; ".join(
        f"{horizon}d: " + (", ".join(input_name for input_name, value in enabled_inputs.items() if value) or "none")
        for horizon, enabled_inputs in stats["settings"]["inputs"].items()
    )
    dash = '<span><span class="dash"></span>perfect calibration</span>'
    tgt = '<span><span class="dash"></span>promise 80%</span>'
    score_note = f'<p class="note">{escape_html(SCORE_NOTE)}</p>'
    index_cue = cfg.get("index_cue") or {}
    replayed_cue = (
        index_cue.get("symbol")
        and index_cue.get("beta", 1.0) == "fit"
        and any(enabled_inputs.get("beta_split") for enabled_inputs in stats["settings"]["inputs"].values())
    )
    cue_name = (cfg["symbols"].get(index_cue.get("symbol")) or {}).get("name") or index_cue.get("symbol")
    cue_txt = f", and the {escape_html(cue_name)} as an overnight cue" if replayed_cue else ""
    aci_settings = stats["settings"].get("aci") or {}
    aci_block = (
        ""
        if not stats.get("aci_comparison")
        else (
            '<h2>Adaptive bands (ACI): before and after</h2><div class="card">'
            f"<p>This page shows the ranges with Adaptive Conformal Inference on (gamma {aci_settings.get('gamma')}, "
            f"at most "
            f"{aci_settings.get('max_shift')} from the target miss rate, after {aci_settings.get('min_history')} "
            f"scored days, "
            f"{'one rate per regime' if aci_settings.get('by_regime') else 'one rate per horizon and band'}): each "
            f"day the "
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
{escape_html(cfg["market"].upper())}</title>
<style>{CSS}</style></head><body><main>
<h1>Historical replay: {escape_html(cfg.get("name", cfg["market"]))}</h1>
<p class="sub">Every past trading day from {escape_html(stats["start"])} to {escape_html(stats["end"])}, the price \
ranges were rebuilt \
using only what
was known before the next session opened (prices up to that day's close, scheduled events{cue_txt}), then checked
against the actual close. Rule-based parts only, no AI. Research only,
not investment advice.</p>
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">An 80% range promises to contain the later closing price 8 times in 10. {escape_html(CI_NOTE)}</p>
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
<p class="note">{escape_html(CI_NOTE)} pts = percentage points. {escape_html(SCORE_NOTE)}</p><ul \
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
(no change counts as wrong). {escape_html(CI_NOTE)} "vs always-up" compares each rule with always-up on the same \
stocks and \
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
(config/ranges.yaml): {escape_html(inputs)}. Data: {escape_html(stats["data"]["first_bar"])} to \
{escape_html(stats["data"]["last_bar"])},
{stats["data"]["tickers"]} tickers, {stats["data"]["earnings_events"]} earnings and {stats["data"]["dividends"]} \
dividend events.
Computed {escape_html(stats["computed_at"])}, runtime {stats["runtime_s"]:.0f} s.</p><ul>{lim}</ul></details>
</main><div id="tip" class="tip"></div><script>{JS}</script></body></html>"""
