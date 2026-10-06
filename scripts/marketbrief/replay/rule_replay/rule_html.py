"""The rule replay's self-contained HTML page: charts, tables and tiles."""
from __future__ import annotations

import math
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.constants.replay import CI_NOTE, MIN_MONTH_DAYS, RSI_HIGH, RSI_LOW, SCORE_NOTE
from marketbrief.constants.replay_page import CSS, JS
from marketbrief.replay.html_parts import esc, fmt_p, legend, scaled_text
from marketbrief.replay.rule_replay.aci_compare import aci_table, held_out_html


def svg_calibration(s: dict) -> str:
    W, H, L, R, T, B = 640, 360, 48, 16, 16, 40
    pw, ph = W - L - R, H - T - B
    X = lambda v: L + v * pw  # noqa: E731
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Stated vs actual coverage">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
        out.append(f'<text x="{X(v):.1f}" y="{H - B + 16}" text-anchor="middle">{int(v * 100)}%</text>')
    out.append(f'<text x="{L + pw / 2}" y="{H - 4}" text-anchor="middle">stated coverage (what the range promises)</text>')
    out.append(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="var(--muted)" stroke-dasharray="4 4"/>')
    for h, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        pts = s["horizons"].get(h, {}).get("calibration") or []
        if not pts:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{X(p['stated']):.1f},{Y(p['actual']):.1f}" for i, p in enumerate(pts))
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for p in pts:
            r = 6 if p["published"] else 4
            tipx = (f"{h}-day {'published ' if p['published'] else ''}{int(p['stated'] * 100)}% range: "
                    f"actual {scaled_text(p['actual'])}")
            out.append(f'<circle class="mark" cx="{X(p["stated"]):.1f}" cy="{Y(p["actual"]):.1f}" r="{r}" fill="{color}" '
                       f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>')
    out.append("</svg>")
    return "".join(out)


def svg_regime(s: dict) -> str:
    regs = REGIME_ORDER
    W, H, L, R, T, B = 640, 300, 48, 16, 16, 44
    pw, ph = W - L - R, H - T - B
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="80% coverage by regime">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    slot = pw / len(regs)
    bw = min(24, slot / 3)
    for i, name in enumerate(regs):
        cx = L + slot * (i + .5)
        days = s.get("regime_days", {}).get(name, 0)
        out.append(f'<text x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{cx:.1f}" y="{H - B + 30}" text-anchor="middle">{days} days</text>')
        for j, (h, color) in enumerate((("1", "var(--s1)"), ("5", "var(--s2)"))):
            r = s["horizons"].get(h, {}).get("by_regime", {}).get(name)
            if not r or not r.get("n"):
                continue
            v = r["cover80"]
            x = cx + (j - 1) * (bw + 2) + 1
            y0, y1 = Y(0), Y(v)
            hgt = max(y0 - y1, 0.5)
            rr = min(4, hgt)
            d = (f"M{x:.1f},{y0:.1f} L{x:.1f},{y1 + rr:.1f} Q{x:.1f},{y1:.1f} {x + rr:.1f},{y1:.1f} "
                 f"L{x + bw - rr:.1f},{y1:.1f} Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 + rr:.1f} L{x + bw:.1f},{y0:.1f} Z")
            tipx = f"{name}, {h}-day: 80% coverage {scaled_text(v)} over {r['n']:,} ranges ({r['days']} days)"
            out.append(f'<path class="mark" d="{d}" fill="{color}" data-tip="{esc(tipx)}"/>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(.8):.1f}" y2="{Y(.8):.1f}" stroke="var(--ink2)" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{L + 4}" y="{Y(.8) - 5:.1f}" text-anchor="start">promise 80%</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--axis)"/>')
    out.append("</svg>")
    return "".join(out)


def svg_time(s: dict) -> str:
    months = sorted({m for h in ("1", "5") for m, v in s["horizons"].get(h, {}).get("by_month", {}).items()
                     if v.get("days", 0) >= MIN_MONTH_DAYS})
    if not months:
        return ""
    W, H, L, R, T, B = 640, 300, 48, 30, 16, 36
    pw, ph = W - L - R, H - T - B
    vals = [v["cover80"] for h in ("1", "5") for v in s["horizons"].get(h, {}).get("by_month", {}).values()
            if v.get("days", 0) >= MIN_MONTH_DAYS]
    lo = max(0.0, math.floor(min(vals + [0.6]) * 10) / 10)
    X = lambda i: L + (i + .5) * pw / len(months)  # noqa: E731
    Y = lambda v: T + (1 - (v - lo) / (1 - lo)) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="80% coverage by month">']
    v = lo
    while v <= 1.0001:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{round(v * 100)}%</text>')
        v += 0.1
    step = max(1, len(months) // 8)
    for i, m in enumerate(months):
        if i % step == 0:
            out.append(f'<text x="{X(i):.1f}" y="{H - B + 16}" text-anchor="middle">{m}</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(.8):.1f}" y2="{Y(.8):.1f}" stroke="var(--ink2)" stroke-dasharray="4 4"/>')
    for h, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        bm = s["horizons"].get(h, {}).get("by_month", {})
        pts = [(i, bm[m]) for i, m in enumerate(months) if bm.get(m, {}).get("days", 0) >= MIN_MONTH_DAYS]
        if not pts:
            continue
        path = " ".join(f"{'M' if k == 0 else 'L'}{X(i):.1f},{Y(r['cover80']):.1f}" for k, (i, r) in enumerate(pts))
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for i, r in pts:
            tipx = f"{months[i]}, {h}-day: 80% coverage {scaled_text(r['cover80'])} ({r['n']:,} ranges)"
            out.append(f'<circle class="mark" cx="{X(i):.1f}" cy="{Y(r["cover80"]):.1f}" r="4" fill="{color}" '
                       f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>')
    out.append("</svg>")
    return "".join(out)


def range_table(groups: dict, label: str) -> str:
    rows = []
    for k, (a, b) in groups.items():
        cells = [esc(k)]
        for r in (a, b):
            if r and r.get("n"):
                cells += [f"{r['n']:,}", scaled_text(r["cover50"]), scaled_text(r["cover80"]),
                          f"{r['width80_pct']:.2f}%", f"{r['score80']:.2f}", f"{r.get('naive_score80', 0) or 0:.2f}"]
            else:
                cells += ["0", "", "", "", "", ""]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    head = (f"<tr><th>{esc(label)}</th>" + "".join(f"<th>{h} n</th><th>{h} 50%</th><th>{h} 80%</th><th>{h} 80% width</th>"
                                                   f"<th>{h} score</th><th>{h} naive score</th>" for h in ("1d", "5d")) + "</tr>")
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def html_report(cfg: dict, s: dict) -> str:
    hz = s["horizons"]
    h1, h5 = hz.get("1", {}).get("overall", {}), hz.get("5", {}).get("overall", {})
    au = {h: (s["baselines"].get(h) or {}).get("always_up", {}) for h in ("1", "5")}

    def tile(label, v, ci, note):
        span = "" if not ci or ci[0] is None else f"95% interval {scaled_text(ci[0])} to {scaled_text(ci[1])}"
        return (f'<div class="card tile"><div class="l">{esc(label)}</div><div class="v">{scaled_text(v)}</div>'
                f'<div class="n">{esc(note)}</div><div class="n">{span}</div></div>')

    tiles = "".join([
        tile("1-day 80% ranges that held", h1.get("cover80"), h1.get("cover80_ci"), f"promise 80% · {h1.get('n', 0):,} ranges"),
        tile("5-day 80% ranges that held", h5.get("cover80"), h5.get("cover80_ci"), f"promise 80% · {h5.get('n', 0):,} ranges"),
        tile("“Always up” right, 1 day ahead", au["1"].get("hit_rate"), au["1"].get("ci95"), "a coin flip is 50%"),
        tile("“Always up” right, 5 days ahead", au["5"].get("hit_rate"), au["5"].get("ci95"), "a coin flip is 50%")])
    top = "".join(f"<p class=\"answer\"><b>{esc(x.split('? ', 1)[0])}?</b> {esc(x.split('? ', 1)[1])}</p>"
                  if "? " in x else f"<p class=\"answer\">{esc(x)}</p>" for x in s.get("top", []))
    summary = "".join(f"<li>{esc(x)}</li>" for x in s["summary"])
    pair = lambda key: {k: (hz.get("1", {}).get(key, {}).get(k), hz.get("5", {}).get(key, {}).get(k))  # noqa: E731
                        for k in dict.fromkeys(list(hz.get("1", {}).get(key, {})) + list(hz.get("5", {}).get(key, {})))}
    brows = []
    for h in ("1", "5"):
        for name, b in (s["baselines"].get(h) or {}).items():
            d, (dlo, dhi) = b["diff_vs_always_up"], b["diff_ci95"]
            vs = "" if name == "always_up" or d is None else f"{100 * d:+.1f} pts"
            vs_ci = "" if name == "always_up" or dlo is None else f"{100 * dlo:+.1f} to {100 * dhi:+.1f}"
            brows.append(f"<tr><td>{esc(b['label'])}</td><td>{h}d</td><td>{b['calls']:,}</td><td>{scaled_text(b['hit_rate'])}</td>"
                         f"<td>{scaled_text(b['ci95'][0])} to {scaled_text(b['ci95'][1])}</td><td>{esc(fmt_p(b['p_vs_50']))}</td>"
                         f"<td>{vs}</td><td>{vs_ci}</td></tr>")
    sector = {t: m.get("sector") or "Other" for t, m in cfg["tickers"].items()}
    trows = []
    for t in sorted(cfg["tickers"]):
        a = hz.get("1", {}).get("by_ticker", {}).get(t, {})
        b = hz.get("5", {}).get("by_ticker", {}).get(t, {})
        if not a.get("n") and not b.get("n"):
            continue
        cell = lambda r, k: scaled_text(r.get(k)) if r.get("n") else ""  # noqa: E731
        num = lambda r, k: f"{r[k]:.2f}" if r.get("n") and r.get(k) is not None else ""  # noqa: E731
        trows.append(f'<tr data-sector="{esc(sector[t])}"><td>{esc(t)}</td><td>{esc(sector[t])}</td>'
                     f"<td>{a.get('n', 0):,}</td><td>{cell(a, 'cover50')}</td><td>{cell(a, 'cover80')}</td>"
                     f"<td>{num(a, 'score80')}</td><td>{num(a, 'naive_score80')}</td>"
                     f"<td>{cell(b, 'cover50')}</td><td>{cell(b, 'cover80')}</td><td>{num(b, 'score80')}</td>"
                     f"<td>{num(b, 'naive_score80')}</td></tr>")
    opts = "".join(f'<option value="{esc(x)}">{esc(x)}</option>' for x in sorted(set(sector.values())))
    lim = "".join(f"<li>{esc(x)}</li>" for x in s["limitations"])
    inputs = "; ".join(f"{h}d: " + (", ".join(k for k, v in u.items() if v) or "none") for h, u in s["settings"]["inputs"].items())
    dash = '<span><span class="dash"></span>perfect calibration</span>'
    tgt = '<span><span class="dash"></span>promise 80%</span>'
    score_note = f'<p class="note">{esc(SCORE_NOTE)}</p>'
    ic = cfg.get("index_cue") or {}
    replayed_cue = ic.get("symbol") and ic.get("beta", 1.0) == "fit" and any(
        u.get("beta_split") for u in s["settings"]["inputs"].values())
    cue_name = (cfg["symbols"].get(ic.get("symbol")) or {}).get("name") or ic.get("symbol")
    cue_txt = f", and the {esc(cue_name)} as an overnight cue" if replayed_cue else ""
    a = s["settings"].get("aci") or {}
    aci_block = "" if not s.get("aci_comparison") else (
        "<h2>Adaptive bands (ACI): before and after</h2><div class=\"card\">"
        f"<p>This page shows the ranges with Adaptive Conformal Inference on (gamma {a.get('gamma')}, at most "
        f"{a.get('max_shift')} from the target miss rate, after {a.get('min_history')} scored days, "
        f"{'one rate per regime' if a.get('by_regime') else 'one rate per horizon and band'}): each day the share "
        "of past ranges that missed moves the band's quantile level. The table compares the same rows with fixed bands "
        "(before) and ACI (after). Width and scores in % of the price, lower is better. These settings may have "
        "been chosen on this same window: in-sample unless the held-out check below agrees.</p>"
        f"{aci_table(s['aci_comparison'])}{held_out_html(s.get('aci_held_out'))}</div>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Historical Replay {esc(cfg['market'].upper())}</title>
<style>{CSS}</style></head><body><main>
<h1>Historical replay: {esc(cfg.get('name', cfg['market']))}</h1>
<p class="sub">Every past trading day from {esc(s['start'])} to {esc(s['end'])}, the price ranges were rebuilt using only what
was known before the next session opened (prices up to that day's close, scheduled events{cue_txt}), then checked
against the actual close. Rule-based parts only, no AI. Research only,
not investment advice.</p>
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">An 80% range promises to contain the later closing price 8 times in 10. {esc(CI_NOTE)}</p>
<h2>Do the ranges hold as often as they promise?</h2>
<div class="card">{legend(dash)}{svg_calibration(s)}
<p class="caption">Look for: points above the dashed line mean the ranges held more often than promised (too wide); below it,
too narrow. The large points are the published 50% and 80% ranges.</p></div>
<h2>Coverage by market mood (regime)</h2>
<div class="card">{legend(tgt)}{svg_regime(s)}
<p class="caption">Look for: bars well above the dashed 80% line are market moods (CALM, TRENDING, EVENT_HEAVY around
scheduled events, UNSTABLE in stress) where the ranges are wider than needed.</p></div>
<h2>Coverage over time</h2>
<div class="card">{legend(tgt)}{svg_time(s)}
<p class="caption">Look for: long runs below the 80% line, which would mean the ranges fell behind in some periods
(months with fewer than {MIN_MONTH_DAYS} days are left out).</p></div>
{aci_block}<h2>More detail</h2>
<details><summary>All findings, with every number</summary>
<p class="note">{esc(CI_NOTE)} pts = percentage points. {esc(SCORE_NOTE)}</p><ul class="summary">{summary}</ul></details>
<details><summary>Coverage by regime (table)</summary>{range_table(pair('by_regime'), 'Regime')}{score_note}</details>
<details><summary>Earnings, market events and years</summary>
<p>Coverage split by whether a company earnings report or a major market event fell inside the horizon, and by year.</p>
{range_table(pair('by_earnings'), 'Earnings')}
{range_table(pair('by_major_event'), 'Market event')}
{range_table(pair('by_year'), 'Year')}{score_note}</details>
<details><summary>Direction baselines (simple up/down rules, not the product's forecasts)</summary>
<p>Simple rules the AI forecaster must beat later. A call is right if the close h days later moved in the called direction
(no change counts as wrong). {esc(CI_NOTE)} "vs always-up" compares each rule with always-up on the same stocks and days,
in pts (percentage points).</p>
<div class="scroll"><table><thead><tr><th>Rule</th><th>Horizon</th><th>Calls</th><th>Hit rate</th><th>95% interval</th>
<th>p vs 50% (if independent)</th><th>vs always-up</th><th>95% interval</th></tr></thead><tbody>{"".join(brows)}</tbody></table></div>
<p class="note">The p-value is an exact binomial test that treats every call as independent; stocks move together, so it
overstates the evidence. Trust the 95% intervals: a rule only beats 50% (or always-up) if its interval stays above it.
Momentum: call the sign of the last 1 or 5 days' return. RSI mean reversion: RSI(14) below {RSI_LOW:g} calls up, above
{RSI_HIGH:g} calls down, otherwise no call (defined in replay.py; indicators.py computes RSI but has no signal).</p></details>
<details><summary>Per ticker</summary>
<p>Filter by sector: <select id="sector"><option value="all">All sectors</option>{opts}</select></p>
<div class="scroll"><table id="tickers"><thead><tr><th>Ticker</th><th>Sector</th><th>n (1d)</th><th>1d 50%</th><th>1d 80%</th>
<th>1d score</th><th>1d naive</th><th>5d 50%</th><th>5d 80%</th><th>5d score</th><th>5d naive</th></tr></thead>
<tbody>{"".join(trows)}</tbody></table></div>{score_note}</details>
<details><summary>Method and limits</summary>
<p>Each as-of day uses only bars up to its close and events as known pre-open the next session, built with the same code as
the live ranges (marketbrief/analytics/range_math.py, the range-input modules, backtest.py helpers, regime.py). Range inputs switched on
(config/ranges.yaml): {esc(inputs)}. Data: {esc(s['data']['first_bar'])} to {esc(s['data']['last_bar'])},
{s['data']['tickers']} tickers, {s['data']['earnings_events']} earnings and {s['data']['dividends']} dividend events.
Computed {esc(s['computed_at'])}, runtime {s['runtime_s']:.0f} s.</p><ul>{lim}</ul></details>
</main><div id="tip" class="tip"></div><script>{JS}</script></body></html>"""
