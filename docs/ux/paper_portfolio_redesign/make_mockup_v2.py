"""Revised (v2) static mockup of the Paper portfolio page, on the app's design system (web/styles tokens + components,
design/system/icons.svg), from a real rm.portfolio build (India, 2026-10-12). Owner feedback of 2026-10-12 applied."""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

ROOT, src, out = sys.argv[1], sys.argv[2], sys.argv[3]
pages = json.load(open(src))
p = pages["_"]
acc = [t for k, v in pages.items() if k.startswith("trades:") for t in v["trades"] if t["state"] == "open"]
h2h = [t for t in p["all_trades"]["trades"] if t["scope"] == "head_to_head" and t["state"] == "open"]
names = {c["ticker"]: c["name"] for c in p["companies"]}
strat = {k: v["name"] for k, v in p["strategies"].items()}
FAMS = ("rule", "baseline", "ai")
FAM = {"rule": "Rule", "baseline": "Baseline", "ai": "AI"}
FAM_TIP = {
    "rule": "Rule strategies: fixed rules on the signal model and the news.",
    "baseline": "Baselines: simple yardsticks (always buy, follow yesterday, model without news) that the others must beat.",
    "ai": "AI traders: language models reading the news, prices or both.",
}
IST = timedelta(hours=5, minutes=30)
e = html.escape


def css(path):
    return open(os.path.join(ROOT, path)).read()


fonts = css("web/styles/fonts.css").replace('url("/fonts/', 'url("../../../web/public/fonts/')
sprite = css("design/system/icons.svg")
sprite = re.sub(r"<\?xml[^>]*>", "", sprite)


def icon(name, cls="ms"):
    return f'<svg class="{cls}" aria-hidden="true"><use href="#ms-{name}"/></svg>'


def day(iso):
    return date.fromisoformat(iso).strftime("%a %-d %b")


def local(iso):
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) + IST).strftime("%a %-d %b, %H:%M IST")


def inr(v, sign=False):
    if v is None:
        return "—"
    s = f"₹{abs(v):,.0f}"
    return (("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")) + s


def delta(v, pct=None):
    if v is None:
        return '<span class="muted">—</span>'
    d = "up" if v > 0 else "down" if v < 0 else "flat"
    tail = f' <small class="pc">{pct:+.1f}%</small>' if pct is not None else ""
    return f'<span class="mb-delta {d}">{inr(v, True)}</span>{tail}'


def state(t):
    if t["price_pending"] or t["unrealised_pnl"] is None:
        return "pending"
    # every paper trade today is bought on an "up" call; a "down" call (direction field, additive) flips the test
    return "with" if t["unrealised_pnl"] > 0 else "against"


def fam_tag(f):
    return f'<span class="fam {f}" data-tip="{e(FAM_TIP[f])}"><i class="sw"></i>{FAM[f]}</span>'


def tip_btn(text, label="Details"):
    return f'<button class="info" type="button" aria-label="{label}" data-tip="{e(text)}">{icon("info")}</button>'


def trade_tip(t):
    c = t.get("check") or {}
    parts = [
        f"{strat.get(t['strategy_id'], t['strategy_id'])} bought {int(t['quantity'] or 0)} shares at the open of {day(t['entry_date'])}; sells at the close of {day(t['exit_date'])}.",
        f"Expected price at the sale (8 in 10 times): {inr(t['lo80'])} to {inr(t['hi80'])}, middle guess {inr(t['target_price'])}.",
    ]
    if c:
        flag = " More than a usual day’s move below the buy price." if "against_prediction" in (c.get("flags") or []) else ""
        parts.append(f"Latest check {local(c['check_at'])}: {c['ret_since_entry_pct']:+.1f}% since the buy.{flag}")
    parts.append("Why bought: the strategy’s chance of going up (new field). Result so far is before fees.")
    return " ".join(parts)


def trade_row(t):
    st = state(t)
    flagged = (t.get("check") or {}).get("flagged")
    mark = {"with": icon("check_circle" if False else "check", "ms ok"), "against": icon("warning" if flagged else "close", "ms bad"), "pending": icon("pending", "ms")}[st]
    so_far = '<span class="muted">no price yet</span>' if st == "pending" else delta(t["unrealised_pnl"], t["unrealised_pct"])
    return f"""<tr class="{st}{' flag' if flagged else ''}">
<td><b class="tk">{e(t['ticker'])}</b><small class="nm">{e(names.get(t['ticker'], t['ticker']))}</small></td>
<td>{fam_tag(t['family'])}<small class="nm">{e(strat.get(t['strategy_id'], t['strategy_id']))}</small></td>
<td class="num hide-s">{inr(t['entry_price'])}</td>
<td class="num hide-s">{inr(t['exit_or_last_price']) if st != 'pending' else '—'}</td>
<td class="num res">{mark}{so_far}</td>
<td class="i">{tip_btn(trade_tip(t))}</td></tr>"""


def sums(ts):
    vals = [t["unrealised_pnl"] for t in ts if state(t) != "pending"]
    return (
        sum(v for v in vals if v > 0) if any(v > 0 for v in vals) else None,
        sum(v for v in vals if v < 0) if any(v < 0 for v in vals) else None,
        sum(vals) if vals else None,
    )


def compare_table(ts, fams=FAMS):
    rows = []
    for f in fams:
        mine = [t for t in ts if t["family"] == f]
        w = sum(1 for t in mine if state(t) == "with")
        a = sum(1 for t in mine if state(t) == "against")
        prof, loss, net = sums(mine)
        if not mine:
            rows.append(f'<tr class="none"><td>{fam_tag(f)}</td><td class="num">0</td><td class="num muted" colspan="5">no open trade</td></tr>')
            continue
        rows.append(f"""<tr><td>{fam_tag(f)}</td><td class="num">{len(mine)}</td>
<td class="num"><span class="ok">{icon('check','ms ok')}{w}</span></td><td class="num"><span class="bad">{icon('close','ms bad')}{a}</span></td>
<td class="num hide-s">{delta(prof)}</td><td class="num hide-s">{delta(loss)}</td><td class="num"><b>{delta(net)}</b></td></tr>""")
    return f"""<div class="md-table-wrap"><table class="md-table cmp"><thead><tr><th>Who</th><th class="num">Open</th><th class="num" data-tip="Going as predicted: above the buy price">As predicted</th><th class="num" data-tip="Going against the prediction: at or below the buy price">Against</th><th class="num hide-s">Profit so far</th><th class="num hide-s">Loss so far</th><th class="num">Net so far</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""


def list_part(kind, ts, bid):
    title = {"with": ("check", "ok", "Going as predicted"), "against": ("close", "bad", "Going against the prediction"), "pending": ("pending", "", "No price yet")}[kind]
    if not ts:
        return ""
    if kind == "against":
        ts = sorted(ts, key=lambda t: (not (t.get("check") or {}).get("flagged"), t["unrealised_pnl"] or 0))
    elif kind == "with":
        ts = sorted(ts, key=lambda t: -(t["unrealised_pnl"] or 0))
    net = sums(ts)[2]
    shown, rest = ts[:3], ts[3:]
    more = ""
    if rest:
        more = f'<tbody class="more" id="{bid}-{kind}" hidden>{"".join(trade_row(t) for t in rest)}</tbody><tbody><tr class="moreline"><td colspan="6"><button class="md-btn text small" type="button" data-more="{bid}-{kind}">{icon("expand_more")}Show {len(rest)} more</button></td></tr></tbody>'
    return f"""<tbody><tr class="sub {kind}"><td colspan="6">{icon(title[0], 'ms ' + title[1])}<b>{title[2]}</b> <span class="cnt">{len(ts)}</span><span class="subnet">{delta(net)}</span></td></tr>{''.join(trade_row(t) for t in shown)}</tbody>{more}"""


def hold_block(k, ts, bid, fams=FAMS):
    exits = sorted({t["exit_date"] for t in ts})
    groups = {s: [t for t in ts if state(t) == s] for s in ("with", "against", "pending")}
    flagged = sum(1 for t in groups["against"] if (t.get("check") or {}).get("flagged"))
    net = sums(ts)[2]
    pend = f'<span class="md-chip small">{icon("pending")}{len(groups["pending"])} no price yet</span>' if groups["pending"] else ""
    return f"""<article class="md-card hold">
<header class="hh"><div><h3>{k}-day hold</h3><div class="hs">{icon('schedule')}sells at the close of {' · '.join(day(x) for x in exits)}</div></div>
<div class="hn"><span class="big">{len(ts)}</span><span class="lbl">open</span></div><div class="hn"><span class="big">{delta(net)}</span><span class="lbl">so far, before fees</span></div></header>
<div class="chips"><span class="md-chip small okc">{icon('check')}{len(groups['with'])} as predicted</span><span class="md-chip small badc">{icon('close')}{len(groups['against'])} against{f' · {flagged} {icon("warning")}far' if flagged else ''}</span>{pend}</div>
{compare_table(ts, fams)}
<div class="md-table-wrap"><table class="md-table trades"><thead><tr><th>Company</th><th>Who</th><th class="num hide-s">Bought at</th><th class="num hide-s">Now</th><th class="num">So far</th><th></th></tr></thead>
{list_part('with', groups['with'], bid)}{list_part('against', groups['against'], bid)}{list_part('pending', groups['pending'], bid)}</table></div>
</article>"""


def holds(ts, prefix, fams=FAMS):
    ks = sorted({t["horizon_days"] for t in ts})
    return "".join(hold_block(k, [t for t in ts if t["horizon_days"] == k], f"{prefix}{k}", fams) for k in ks)


at = p["all_trades"]
summ = {(r["scope"], r["family"], r["period"]): r for r in at["summary"]}


def overview_rows(scope, fams):
    rows = []
    for f in fams:
        r = summ[(scope, f, "to_date")]
        fin = r["closed"]
        net = delta(r["net_pnl_market"]) if fin else '<span class="muted">—</span>'
        rows.append(f"""<tr><td>{fam_tag(f)}</td><td class="num">{r['open']}</td><td class="num">{fin}</td>
<td class="num">{icon('check','ms ok')}{r['wins']}</td><td class="num">{icon('close','ms bad')}{r['losses']}</td>
<td class="num">{net}</td><td class="num hide-s">{delta(r['unrealised_pnl'])}</td></tr>""")
    return "".join(rows)


def overview_table(scope, fams):
    return f"""<table class="md-table cmp ov"><thead><tr><th>Who</th><th class="num">Open</th><th class="num">Finished</th><th class="num">Won</th><th class="num">Lost</th><th class="num" data-tip="Finished trades, after market fees">Net after fees</th><th class="num hide-s" data-tip="Open trades, before fees">Open so far</th></tr></thead><tbody>{overview_rows(scope, fams)}</tbody></table>"""


# Section 2 illustration: today's 1-day holds as if they had sold at the latest price, minus a sample fee. Not stored.
REASONS = {
    "market": "Mostly the whole market: Nifty 50 moved {m:+.1f}% over the hold.",
    "sector": "Mostly its sector: {s} moved {sp:+.1f}%.",
    "company": "Mostly company-specific: {c:+.1f}% beyond the market and sector.",
}


def finished_rows():
    ones = [t for t in acc if t["horizon_days"] == 1 and state(t) != "pending"]
    ones = sorted(ones, key=lambda t: -abs(t["unrealised_pnl"]))[:6]
    rows = []
    for i, t in enumerate(ones):
        fee = round((t["entry_price"] * t["quantity"]) * 0.0024)
        net = t["unrealised_pnl"] - fee
        won = net > 0
        kind = ("company", "market", "sector")[i % 3]
        why = REASONS[kind].format(m=t["unrealised_pct"] * 0.4, s="its sector", sp=t["unrealised_pct"] * 0.3, c=t["unrealised_pct"] * 0.6)
        tipt = f"{'Went as predicted' if won else 'Went against the prediction'}. {why} Sold at {inr(t['exit_or_last_price'])}, bought at {inr(t['entry_price'])}. After market fees {inr(net, True)}; after your fees about {inr(net - 400, True)}."
        rows.append(f"""<tr class="{'with' if won else 'against'}"><td><b class="tk">{e(t['ticker'])}</b><small class="nm">{e(names[t['ticker']])}</small></td>
<td>{fam_tag(t['family'])}<small class="nm">{e(strat[t['strategy_id']])}</small></td><td class="hide-s">1-day</td>
<td>{('<span class="mb-label success">' + icon('check') + 'Won</span>') if won else ('<span class="mb-label danger">' + icon('close') + 'Lost</span>')}</td>
<td class="num">{delta(net)}</td><td class="i">{tip_btn(tipt, 'Why')}</td></tr>""")
    return "".join(rows), ones


fin_rows, fin_src = finished_rows()


def fin_compare(src):
    out = []
    for f in FAMS:
        mine = [t for t in src if t["family"] == f]
        if not mine:
            out.append(f'<div class="side none">{fam_tag(f)}<div class="v muted">nothing finished</div></div>')
            continue
        nets = [t["unrealised_pnl"] - round(t["entry_price"] * t["quantity"] * 0.0024) for t in mine]
        w = sum(1 for n in nets if n > 0)
        out.append(f'<div class="side">{fam_tag(f)}<div class="v">{icon("check","ms ok")}{w} won · {icon("close","ms bad")}{len(nets)-w} lost</div><div class="v">{delta(sum(nets))}</div></div>')
    return "".join(out)


H = {(r["family"]): r for r in at["summary"] if r["scope"] == "head_to_head" and r["period"] == "to_date"}


def side_box(f):
    r = H[f]
    return f"""<div class="side big"><div class="sh">{fam_tag(f)}<span class="muted">side</span></div>
<div class="kv"><span>Open</span><b>{r['open']}</b></div><div class="kv"><span>Finished</span><b>{r['closed']}</b></div>
<div class="kv"><span>Won · lost</span><b>{icon('check','ms ok')}{r['wins']} · {icon('close','ms bad')}{r['losses']}</b></div>
<div class="kv"><span>Net after fees</span><b>{delta(r['net_pnl_market']) if r['closed'] else '<span class="muted">—</span>'}</b></div>
<div class="kv"><span>Open so far</span><b>{delta(r['unrealised_pnl'])}</b></div></div>"""


M = summ[("mine", "mine", "to_date")]
A = summ[("all", "all", "to_date")]
paper = f'<span class="mb-label paper" data-tip="Every figure is Paper until a strategy passes the go-live test. A paper trade is a record, never an order; nothing here is advice.">{icon("science")}Paper</span>'

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper portfolio mockup v2</title>
<style>{fonts}
{css('web/styles/tokens.css')}
{css('web/styles/components.css')}
/* page-only styles of the mockup */ .mb-delta{{white-space:nowrap}}
body{{background:var(--md-sys-color-surface-container-low);margin:0}}
main{{max-width:1120px;margin:0 auto;padding:16px}}
.ann{{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-tertiary-container);background:var(--md-sys-color-tertiary-container);border-radius:12px;padding:8px 12px;margin:0 0 12px}}
.ann b{{font-weight:600}}
h1{{font:var(--md-sys-typescale-headline-small);margin:4px 0 6px}}
.head-chips{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}}
h2.sec{{font:var(--md-sys-typescale-title-large);margin:28px 0 10px;display:flex;align-items:center;gap:8px}}
h2.sec .ms{{width:22px;height:22px;color:var(--md-sys-color-primary)}}
.grid{{display:grid;gap:16px;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)}}
@media (max-width:900px){{.grid{{grid-template-columns:minmax(0,1fr)}}}}
.md-card h3{{font:var(--md-sys-typescale-title-medium);margin:0}}
.cap{{font:var(--md-sys-typescale-label-medium);color:var(--md-sys-color-on-surface-variant);text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px;display:flex;align-items:center;gap:6px}}
.ms{{width:18px;height:18px;vertical-align:-4px;fill:currentColor}}
.ms.ok,.ok{{color:var(--mb-color-up)}} .ms.bad,.bad{{color:var(--mb-color-down)}}
td .ms.ok,td .ms.bad{{margin-right:3px}}
.num{{text-align:right;white-space:nowrap}} .muted{{color:var(--md-sys-color-on-surface-variant)}}
.fam{{display:inline-flex;align-items:center;gap:6px;font:600 12.5px/18px var(--md-ref-typeface-plain)}}
.fam .sw{{width:10px;height:10px;border-radius:3px;display:inline-block}}
.fam.rule .sw{{background:var(--mb-chart-1)}} .fam.baseline .sw{{background:var(--mb-chart-2)}} .fam.ai .sw{{background:var(--mb-chart-3)}}
.tk{{display:block;font-weight:600}} .nm{{display:block;font-size:11.5px;color:var(--md-sys-color-on-surface-variant);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}}
.pc{{color:var(--md-sys-color-on-surface-variant);font-size:11.5px;margin-left:4px}}
.md-table.cmp td,.md-table.cmp th{{padding:8px 10px}} .md-table.cmp tr.none td{{color:var(--md-sys-color-on-surface-variant)}}
.sides{{display:grid;grid-template-columns:1fr 1fr;gap:10px}} .side{{background:var(--md-sys-color-surface-container);border-radius:12px;padding:10px 12px}}
.side .sh{{display:flex;justify-content:space-between;margin-bottom:6px}} .kv{{display:flex;justify-content:space-between;font:var(--md-sys-typescale-body-medium);padding:2px 0}}
.kv span{{color:var(--md-sys-color-on-surface-variant)}}
.fin-sides{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:0 0 12px}} .fin-sides .v{{font:var(--md-sys-typescale-body-medium);margin-top:4px}}
.own{{display:flex;gap:20px;align-items:center;flex-wrap:wrap}} .own .big{{font:var(--md-sys-typescale-title-large)}}
.hold{{margin-top:14px}} .hh{{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap;margin-bottom:10px}} .hh>div:first-child{{flex:1;min-width:180px}}
.hs{{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant);margin-top:2px}} .hs .ms{{width:15px;height:15px;margin-right:3px}}
.hn{{display:flex;flex-direction:column;align-items:flex-end}} .hn .big{{font:var(--md-sys-typescale-title-large)}} .hn .lbl{{font:var(--md-sys-typescale-label-small);color:var(--md-sys-color-on-surface-variant)}}
.chips{{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}} .md-chip.okc{{color:var(--mb-color-on-up-container);background:var(--mb-color-up-container);border-color:transparent}}
.md-chip.badc{{color:var(--mb-color-on-down-container);background:var(--mb-color-down-container);border-color:transparent}} .md-chip .ms{{color:inherit}}
.md-table.trades{{margin-top:12px}} tr.sub td{{background:transparent;padding-top:14px;font:var(--md-sys-typescale-title-small);border-bottom:1px solid var(--md-sys-color-outline-variant)}}
tr.sub.with td{{color:var(--mb-color-up)}} tr.sub.against td{{color:var(--mb-color-down)}} tr.sub .ms{{margin-right:6px}} .cnt{{font:var(--md-sys-typescale-label-medium);background:var(--md-sys-color-surface-container-high);color:var(--md-sys-color-on-surface-variant);border-radius:99px;padding:1px 8px;margin-left:6px}}
.subnet{{float:right}} tr.flag td{{background:var(--mb-color-down-container)}} .res{{white-space:nowrap}} td.i{{width:34px;padding-left:0;padding-right:4px}}
.info{{border:0;background:none;color:var(--md-sys-color-on-surface-variant);cursor:pointer;border-radius:99px;width:30px;height:30px;display:grid;place-items:center}} .info:hover,.info:focus-visible{{background:var(--md-sys-color-surface-container-high);color:var(--md-sys-color-primary)}}
tr.moreline td{{border-bottom:0;padding:4px 6px}} .md-btn.small{{height:32px}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant);margin-top:24px}}
#pop{{position:fixed;z-index:50;max-width:320px;display:none}} .ill{{font:var(--md-sys-typescale-label-small);color:var(--mb-color-on-warn-container);background:var(--mb-color-warn-container);border-radius:6px;padding:2px 8px;margin-left:auto}}
@media (max-width:640px){{.hide-s{{display:none}} main{{padding:16px}} .md-card{{padding:16px}} .sides{{grid-template-columns:1fr 1fr}} .fin-sides{{grid-template-columns:1fr}} .nm{{max-width:84px}} .pc{{display:none}} .hh{{gap:12px}} .hh>div:first-child{{min-width:100%}} .hn{{align-items:flex-start}} td.i{{width:28px}} .info{{width:26px;height:26px}} .mb-label{{padding:2px 5px}} .hn .big{{font:var(--md-sys-typescale-title-medium)}} .md-table td,.md-table th{{padding:8px 5px}} .md-table th{{white-space:normal;font-size:10px;letter-spacing:.03em}} .fam{{font-size:12px;gap:4px}} .md-table.cmp td,.md-table.cmp th{{padding:7px 5px}}}}
</style></head><body>
{sprite}
<main>
<p class="ann"><b>Mockup v2 for the owner (UX3).</b> Real India data, Mon 12 Oct 2026, 18:31 IST, built on the app’s own design tokens, components and icons. Tinted notes like this are not on the page. Tap any {icon('info')} or underlined header for its popover.</p>
<h1>Paper portfolio</h1>
<div class="head-chips">{paper}<span class="md-chip small">{icon('schedule')}prices Mon 12 Oct, 14:05 IST</span><span class="md-chip small">{icon('public')}India (NSE)</span></div>

<h2 class="sec">{icon('query_stats')}How are the paper trades doing?</h2>
<p class="ann">Owner points 1 and 3: every box is split by side, side by side, nothing behind a toggle. The views are never added together.</p>
<div class="grid">
 <section class="md-card"><div class="cap">Every strategy’s trades {tip_btn('Each qualifying prediction is one paper trade of the company’s amount (₹1,00,000). Won = made money after market fees.')}</div>{overview_table('all', FAMS)}</section>
 <div style="display:grid;gap:16px">
  <section class="md-card"><div class="cap">Rule vs AI picks {tip_btn('Each day the strongest rule strategy and the strongest AI trader each pick their trade per company. Same predictions as the box on the left, so never added to it.')}</div><div class="sides">{side_box('rule')}{side_box('ai')}</div></section>
  <section class="md-card"><div class="cap">Your own trades {tip_btn('Your manual paper trades, after your own broker’s fees.')}</div><div class="own"><span><span class="big">{M['open']}</span> open</span><span><span class="big">{M['closed']}</span> finished</span><button class="md-btn tonal small" type="button">{icon('receipt_long')}Add own paper trade</button></div></section>
 </div>
</div>

<h2 class="sec">{icon('history')}What finished recently?</h2>
<p class="ann">Owner point 4. Real data has nothing finished yet (the first sales are at the close of Tue 13 Oct), so the empty state shows first. Below it, an <b>illustration</b> with sample numbers so the layout can be judged: today’s 1-day holds as if sold at the latest price, minus a sample fee. Not stored results.</p>
<section class="md-card">
 <div class="chips" role="group" aria-label="Sold on"><button class="md-chip filter small" aria-pressed="true">Today · 0</button><button class="md-chip filter small" aria-pressed="false">Fri 9 Oct · 0</button><button class="md-chip filter small" aria-pressed="false">Thu 8 Oct · 0</button></div>
 <p class="muted" style="margin:4px 0 16px">{icon('schedule')} Nothing finished yet. First sales: close of Tue 13 Oct; results after the after-close run, about 17:45 IST.</p>
 <div class="cap">Sample layout <span class="ill">illustration · sample numbers</span></div>
 <div class="fin-sides">{fin_compare(fin_src)}</div>
 <div class="md-table-wrap"><table class="md-table trades"><thead><tr><th>Company</th><th>Who</th><th class="hide-s">Hold</th><th>Result</th><th class="num">Net after fees</th><th></th></tr></thead><tbody>{fin_rows}</tbody></table></div>
</section>

<h2 class="sec">{icon('trending_up')}Still open: every strategy’s trades</h2>
<p class="ann">Owner point 2: one always-visible block per hold length that has trades (1–5 days), stacked. Each block: totals, ✓/✗ chips, the Rule · Baseline · AI comparison (count, as predicted, against, profit so far, loss so far, net), then the trades split into “going as predicted” and “going against” (3 rows each, then “show more”). Details sit in the {icon('info')} popover.</p>
{holds(acc, 'a')}

<h2 class="sec">{icon('layers')}Still open: Rule vs AI picks</h2>
<p class="ann">The same blocks for the head-to-head picks, Rule side vs AI side only (baselines never pick). Kept apart from the section above.</p>
{holds(h2h, 'h', ('rule', 'ai'))}

<h2 class="sec">{icon('account_balance_wallet')}Your own paper trades</h2>
<section class="md-card"><p class="muted" style="margin:0">{icon('schedule')} None recorded in India yet. One you add shows here after the next run imports it.</p><div style="margin-top:12px"><button class="md-btn filled" type="button">{icon('receipt_long')}Add own paper trade</button></div></section>

<div class="legend"><span>{fam_tag('rule')}</span><span>{fam_tag('baseline')}</span><span>{fam_tag('ai')}</span><span>{icon('check','ms ok')} going as predicted / won</span><span>{icon('close','ms bad')} going against / lost</span><span>{icon('warning','ms bad')} far against at the latest check</span><span>{paper}</span></div>
</main>
<div id="pop" class="md-tooltip-rich" role="tooltip"></div>
<script>
const pop=document.getElementById('pop');let pinned=null;
function show(el){{pop.textContent=el.dataset.tip;pop.style.display='block';const r=el.getBoundingClientRect();const w=Math.min(320,innerWidth-32);pop.style.maxWidth=w+'px';let x=Math.min(Math.max(16,r.right-w),innerWidth-w-16);let y=r.bottom+6;pop.style.left=x+'px';pop.style.top=y+'px';const h=pop.offsetHeight;if(y+h>innerHeight-8)pop.style.top=(r.top-h-6)+'px'}}
function hide(){{pop.style.display='none';pinned=null}}
document.addEventListener('mouseover',ev=>{{const el=ev.target.closest('[data-tip]');if(el&&!pinned)show(el)}});
document.addEventListener('mouseout',ev=>{{if(!pinned&&ev.target.closest('[data-tip]'))hide()}});
document.addEventListener('click',ev=>{{const m=ev.target.closest('[data-more]');if(m){{document.getElementById(m.dataset.more).hidden=false;m.closest('tbody').remove();return}}const el=ev.target.closest('[data-tip]');if(el){{pinned=el;show(el)}}else hide()}});
document.addEventListener('keydown',ev=>{{if(ev.key==='Escape')hide()}});
</script></body></html>"""
open(out, "w").write(page)
print("wrote", out, len(page))
