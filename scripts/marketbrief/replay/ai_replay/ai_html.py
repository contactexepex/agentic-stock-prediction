"""The AI replay's score page: charts, tiles and tables per leakage group."""
from __future__ import annotations

import html
from marketbrief.constants import replay
from marketbrief.constants import replay_page
from marketbrief.replay import html_parts
from marketbrief.constants.ai_replay import CONTAMINATED, FAIR
from marketbrief.replay.ai_replay.summaries import pct


def svg_hit_bars(s: dict) -> str:
    groups = [("1-day", s["by_horizon"]["1"]), ("5-day", s["by_horizon"]["5"]), ("All", s["overall"])]
    W, H, L, R, T, B = 640, 300, 48, 16, 16, 44
    pw, ph = W - L - R, H - T - B
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Hit rate: AI vs always-up">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    slot, bw = pw / len(groups), 28
    for i, (name, g) in enumerate(groups):
        cx = L + slot * (i + .5)
        out.append(f'<text x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{cx:.1f}" y="{H - B + 30}" text-anchor="middle">{g.get("n", 0)} calls</text>')
        if not g.get("n"):
            continue
        for j, (key, color, label) in enumerate((("ai", "var(--s1)", "AI"), ("au", "var(--s2)", "Always up"))):
            r = g if key == "ai" else g["always_up"]
            v = r["hit_rate"]
            x = cx + (j - 1) * (bw + 2) + 1
            y0, y1 = Y(0), Y(v)
            hgt = max(y0 - y1, 0.5)
            rr = min(4, hgt)
            d = (f"M{x:.1f},{y0:.1f} L{x:.1f},{y1 + rr:.1f} Q{x:.1f},{y1:.1f} {x + rr:.1f},{y1:.1f} "
                 f"L{x + bw - rr:.1f},{y1:.1f} Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 + rr:.1f} L{x + bw:.1f},{y0:.1f} Z")
            ci = r["ci95"]
            tip = f"{name}, {label}: right {pct(v)} of {r['n']} (95% interval {pct(ci[0])} to {pct(ci[1])})"
            out.append(f'<path class="mark" d="{d}" fill="{color}" data-tip="{html.escape(tip, quote=True)}"/>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(.5):.1f}" y2="{Y(.5):.1f}" stroke="var(--ink2)" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{L + 4}" y="{Y(.5) - 5:.1f}" text-anchor="start">coin flip</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--axis)"/></svg>')
    return "".join(out)


def svg_calibration(s: dict) -> str:
    pts = [b for b in s["by_band"] if b.get("n")]
    W, H, L, R, T, B = 640, 340, 48, 16, 16, 40
    pw, ph = W - L - R, H - T - B
    lo_x, hi_x = 0.45, 0.95
    X = lambda v: L + (v - lo_x) / (hi_x - lo_x) * pw  # noqa: E731
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Stated confidence vs actual hit rate">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    for v in (0.5, 0.6, 0.7, 0.8, 0.9):
        out.append(f'<text x="{X(v):.1f}" y="{H - B + 16}" text-anchor="middle">{int(v * 100)}%</text>')
    out.append(f'<text x="{L + pw / 2}" y="{H - 4}" text-anchor="middle">stated confidence (average in each band)</text>')
    out.append(f'<line x1="{X(lo_x):.1f}" y1="{Y(lo_x):.1f}" x2="{X(hi_x):.1f}" y2="{Y(hi_x):.1f}" '
               'stroke="var(--muted)" stroke-dasharray="4 4"/>')
    for b in pts:
        x, y = X(b["stated"]), Y(b["hit_rate"])
        lo, hi = b["ci95"]
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{Y(lo):.1f}" y2="{Y(hi):.1f}" stroke="var(--s1)" stroke-width="2"/>')
        tip = (f"Band {b['band']}: stated {pct(b['stated'])}, right {pct(b['hit_rate'])} of {b['n']} calls "
               f"(95% interval {pct(lo)} to {pct(hi)})")
        out.append(f'<circle class="mark" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="var(--s1)" stroke="var(--surface)" '
                   f'stroke-width="2" data-tip="{html.escape(tip, quote=True)}"/>')
        out.append(f'<text x="{x + 10:.1f}" y="{y + 4:.1f}" text-anchor="start">{b["n"]} calls</text>')
    out.append("</svg>")
    return "".join(out)


def pts(x) -> str:
    return "" if x is None else f"{100 * x:+.1f} pts"


def signed_pct(x) -> str:
    return "" if x is None else f"{100 * x:+.2f}%"


def html_page(s: dict) -> str:
    """The score page: the fair group (as-of dates after the training cutoff) is the result; the
    contaminated group, if any, is a separate, labelled section scored on its own rows only."""
    esc = html_parts.esc
    f, c = s[FAIR], s[CONTAMINATED]
    cut = esc(s["model_training_cutoff"])
    banner = (f'<p class="note"><b>Fair test</b> = an as-of date after {cut}, the model\'s training cutoff '
              '(<code>model_training_cutoff</code> in config/settings.yaml; ForecastBench leakage rule). Dates on or '
              f'before it are <b>contaminated</b>: the model may have seen what happened. The two groups are scored '
              f'separately and never pooled: {f["n_days"]} fair and {c["n_days"]} contaminated days.</p>')
    if f["n_days"]:
        sub = (f'<p class="sub">On {f["n_days"]} past trading days after the model\'s training data '
               f'({esc(f["dates"][0])} to {esc(f["dates"][-1])}), the AI forecaster saw only what was known before the '
               'next session opened, and its up/down calls were checked against the actual closes. Research only, not '
               'investment advice.</p>')
        body = group_html(f)
    else:
        sub = ('<p class="sub">No fair-test day is recorded yet, so there is no fair result. Research only, not '
               'investment advice.</p>')
        body = ""
    if c["n_days"]:
        body += (f'<section class="contaminated"><h2>Contaminated dates (on or before {cut}): not a fair test</h2>'
                 f'<p class="note bad">CONTAMINATED: {c["n_days"]} as-of dates ({esc(c["dates"][0])} to '
                 f'{esc(c["dates"][-1])}) fall inside the model\'s training period, so it may have seen these prices. '
                 'They are scored on their own below, never pooled with the fair result.</p>'
                 f'{group_html(c)}</section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Replay {esc(s['market'].upper())}</title>
<style>{replay_page.CSS}</style></head><body><main>
<h1>AI forecaster replay: {esc(s.get('name') or s['market'])}</h1>
{sub}{banner}{body}
</main><div id="tip" class="tip"></div><script>{replay_page.JS}</script></body></html>"""


def group_html(g: dict) -> str:
    """One leakage group's results (fair or contaminated): answers, tiles, charts and detail tables."""
    esc = html_parts.esc
    lab = g["test"]
    o, hz, ab = g["overall"], g["by_horizon"], g["abstention"]

    def tile(label, r, note):
        v = r.get("hit_rate") if r else None
        ci = (r or {}).get("ci95") or [None, None]
        span = "" if ci[0] is None else f"95% interval {pct(ci[0])} to {pct(ci[1])}"
        return (f'<div class="card tile"><div class="l">{esc(label)}</div><div class="v">{pct(v)}</div>'
                f'<div class="n">{esc(note)}</div><div class="n">{span}</div></div>')

    tiles = "".join([
        tile("AI calls right, 5 days ahead", hz["5"], f"{hz['5'].get('n', 0)} scored calls · coin flip 50%"),
        tile("AI calls right, 1 day ahead", hz["1"], f"{hz['1'].get('n', 0)} scored calls · coin flip 50%"),
        tile("“Always up” right on the same calls", o.get("always_up") or {}, "same stocks, days and horizons"),
        f'<div class="card tile"><div class="l">Stock-days with no call</div>'
        f'<div class="v">{pct(ab["any"]["abstention_rate"])}</div><div class="n">abstained on '
        f'{ab["any"]["slots"] - ab["any"]["ticker_days_with_a_call"]} of {ab["any"]["slots"]} stock-days</div>'
        f'<div class="n">abstaining is allowed and often right</div></div>'])
    top = "".join(f"<p class=\"answer\"><b>{esc(x.split('? ', 1)[0])}?</b> {esc(x.split('? ', 1)[1])}</p>"
                  for x in g["top"])
    hrows = []
    for name, x in (("1-day", hz["1"]), ("5-day", hz["5"]), ("All", o)):
        if not x.get("n"):
            hrows.append(f"<tr><td>{name}</td><td>0</td>" + "<td></td>" * 6 + "</tr>")
            continue
        d = x["diff_vs_always_up"]
        hrows.append(f"<tr><td>{name}</td><td>{x['n']}</td><td>{pct(x['hit_rate'])}</td>"
                     f"<td>{pct(x['ci95'][0])} to {pct(x['ci95'][1])}</td><td>{esc(html_parts.fmt_p(x['p_vs_50']))}</td>"
                     f"<td>{pct(x['mean_confidence'])}</td><td>{pct(x['always_up']['hit_rate'])}</td>"
                     f"<td>{pts(d['pts'])}</td></tr>")
    rrows = []
    for name, x in (("1-day", hz["1"]), ("5-day", hz["5"]), ("All", o)):
        for r in (x.get("rules") or {}).values():
            if not r.get("n"):
                continue
            rrows.append(f"<tr><td>{esc(r['label'])}</td><td>{name}</td><td>{r['n']}</td><td>{pct(r['hit_rate'])}</td>"
                         f"<td>{pct(r['ci95'][0])} to {pct(r['ci95'][1])}</td><td>{pct(r['ai_hit_rate_same_rows'])}</td></tr>")
    brows = "".join(f"<tr><td>{b['band']}</td><td>{b.get('n', 0)}</td><td>{pct(b.get('stated'))}</td>"
                    f"<td>{pct(b.get('hit_rate'))}</td><td>"
                    f"{'' if not b.get('n') else pct(b['ci95'][0]) + ' to ' + pct(b['ci95'][1])}</td></tr>"
                    for b in g["by_band"])
    arows = "".join(f"<tr><td>{k}</td><td>{v['slots']}</td><td>{v.get('calls', v.get('ticker_days_with_a_call'))}</td>"
                    f"<td>{pct(v['abstention_rate'])}</td></tr>" for k, v in ab.items() if isinstance(v, dict))
    drows = "".join(f"<tr><td>{x['date']}</td><td>{lab}</td><td>{x['citable_ids']}</td><td>{x['calls']}</td><td>{x['rejected']}</td>"
                    f"<td>{x['scored']}</td><td>{x['hits']}</td></tr>" for x in g["per_day"])
    crows = "".join(f"<tr><td>{esc(str(c['date']))}</td><td>{esc(c['test'])}</td><td>{esc(c['ticker'])}</td><td>{c['h']}d</td><td>{esc(c['direction'])}</td>"
                    f"<td>{c['confidence']:.2f}</td><td>{esc(c['status'])}</td>"
                    f"<td>{signed_pct(c.get('ret'))}</td>"
                    f"<td>{'' if c.get('hit') is None else ('right' if c['hit'] else 'wrong')}</td>"
                    f"<td>{esc(', '.join(c.get('evidence_ids') or []))}</td></tr>" for c in g["calls"])
    legend = ('<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>AI forecaster</span>'
              '<span><span class="sw" style="background:var(--s2)"></span>Always up (same calls)</span>'
              '<span><span class="dash"></span>coin flip 50%</span></div>')
    tag = (f'<p class="note"><b>Group: {esc(lab)}</b> ({g["n_days"]} as-of days, {g["n_calls"]} calls); '
           'every number in this group uses only its own rows.</p>')
    return f"""{tag}
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">A call is right if the close 1 or 5 trading days later moved the called way (no change counts as wrong).
95% interval = the span the true hit rate most likely lies in; with few calls it is wide.</p>
<h2>Was the AI right more often than “always up”?</h2>
<div class="card">{legend}{svg_hit_bars(g)}
<p class="caption">Look for: blue bars above both the dashed 50% line and the orange bar beside them. Bars that differ by
less than their 95% intervals (hover a bar) are within noise.</p></div>
<h2>Does its confidence mean what it says?</h2>
<div class="card"><div class="legend"><span><span class="sw" style="background:var(--s1)"></span>AI calls by confidence band
(line = 95% interval)</span><span><span class="dash"></span>perfect calibration</span></div>{svg_calibration(g)}
<p class="caption">Look for: points on the dashed line. Below it, calls stated with that confidence were right less often
than promised (overconfident); above it, more often.</p></div>
<h2>More detail</h2>
<details><summary>Hit rates by horizon (table)</summary><div class="scroll"><table><thead><tr><th>Horizon</th><th>Calls</th>
<th>Hit rate</th><th>95% interval</th><th>p vs 50%</th><th>Stated</th><th>Always up</th><th>AI vs always up</th></tr></thead>
<tbody>{''.join(hrows)}</tbody></table></div>
<p class="note">95% interval: Wilson binomial interval; p: exact two-sided binomial test vs 50%. Both treat calls as
independent; calls on the same day move together, so they overstate the evidence. "AI vs always up" is in percentage
points on the same calls (its 95% interval, clustered by date, is in the JSON).</p></details>
<details><summary>Simple rules on the same stocks and days</summary><div class="scroll"><table><thead><tr><th>Rule</th>
<th>Horizon</th><th>Rule calls</th><th>Rule hit rate</th><th>95% interval</th><th>AI hit rate on those calls</th></tr></thead>
<tbody>{''.join(rrows) or '<tr><td>no scored calls</td><td></td><td></td><td></td><td></td><td></td></tr>'}</tbody></table></div>
<p class="note">Rules from replay.py, on the ticker-days where the AI made a call: momentum (sign of the last 1 or 5 days'
return) and RSI(14) mean reversion (below {replay.RSI_LOW:g} up, above {replay.RSI_HIGH:g} down, else no call).</p></details>
<details><summary>Confidence bands (calibration)</summary><div class="scroll"><table><thead><tr><th>Band</th><th>Calls</th>
<th>Stated</th><th>Right</th><th>95% interval</th></tr></thead><tbody>{brows}</tbody></table></div>
<p class="note">Brier score (lower is better; 0.25 = always saying 50%): {o.get('brier', 'n/a')}.</p></details>
<details><summary>Abstention</summary><div class="scroll"><table><thead><tr><th>Horizon</th><th>Stock-days</th><th>Calls</th>
<th>No call</th></tr></thead><tbody>{arows}</tbody></table></div>
<p class="note">Stock-days count only tickers the rules allow a call on (not BLOCKED, no earnings within 1 day).</p></details>
<details><summary>Per sample day</summary><div class="scroll"><table><thead><tr><th>As-of date</th><th>Test</th><th>Citable ids</th>
<th>Calls</th><th>Rejected</th><th>Scored</th><th>Right</th></tr></thead><tbody>{drows}</tbody></table></div></details>
<details><summary>Every call</summary><div class="scroll"><table><thead><tr><th>As-of</th><th>Test</th><th>Ticker</th><th>Horizon</th>
<th>Call</th><th>Confidence</th><th>Status</th><th>Return</th><th>Result</th><th>Evidence</th></tr></thead>
<tbody>{crows}</tbody></table></div></details>
<details><summary>Method and limits</summary><ul>
<li>Each day was prepared by <code>scripts/ai_replay.py prepare</code>: prices up to that day's close, and filings,
announcements and other records only if public before the routine's pre-open start on the next session.</li>
<li>No news before live collection began, so calls could cite only SEC filings (US) or NSE announcements (India).</li>
<li>Scored on the real stored closes, {g['n_pending']} calls still pending (target after the last stored bar).</li>
<li>Prompt versions: {esc(', '.join(g['prompt_versions']) or 'none')}.</li>
<li>A small sample: a dozen days per market cannot show a small edge; treat the result as a smoke test.</li></ul></details>"""
