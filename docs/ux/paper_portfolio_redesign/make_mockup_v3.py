"""Paper portfolio redesign, mockup v3 (UX3): the page and one "full story" page, on the app's design system
(web/styles tokens + components, design/system/tokens-dark.css, design/system/icons.svg), from real stored data.

    python make_mockup_v3.py <repo> <rm.portfolio pages json> <why json> <out dir>

<rm.portfolio pages json>: rm_portfolio.portfolio_pages() as of the build (India, Mon 12 Oct 2026, 18:31 IST).
<why json>: per ticker the latest intraday check's market / sector / own move, the latest deviation-explainer note,
and each prediction's chance of a rise and AI reason (DuckDB reads of intraday_checks, intraday_explanations and
strategy_predictions). The finished-trades rows are an illustration with sample numbers (nothing has finished yet)."""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

ROOT, SRC, WHY, OUT = sys.argv[1:5]
pages = json.load(open(SRC))
why = json.load(open(WHY))
p = pages["_"]
acc = [t for k, v in pages.items() if k.startswith("trades:") for t in v["trades"] if t["state"] == "open"]
h2h = [t for t in p["all_trades"]["trades"] if t["scope"] == "head_to_head" and t["state"] == "open"]
names = {c["ticker"]: c["name"] for c in p["companies"]}
strat = {k: v["name"] for k, v in p["strategies"].items()}
thr = {k: v["threshold"] for k, v in p["strategies"].items()}
FAMS = ("rule", "baseline", "ai")
SIDE = {"rule": "Rule strategies", "baseline": "Simple benchmarks", "ai": "AI traders"}
SIDE_SHORT = {"rule": "Rule", "baseline": "Benchmark", "ai": "AI"}
SIDE_TIP = {
    "rule": "Fixed rules on the signal model’s chance of a rise and the checked news. They buy only when the chance is at least 55%.",
    "baseline": "Simple yardsticks the others must beat: “Always buy”, “Follow yesterday” and “Model without news”. If a clever strategy can’t beat these, it has no edge.",
    "ai": "Four AI traders reading the news, the prices, or both. Each says how likely a rise is and why, or stays out.",
}
IST = timedelta(hours=5, minutes=30)
e = html.escape


def read(path):
    return open(os.path.join(ROOT, path)).read()


def icon(name, cls="ms"):
    return f'<svg class="{cls}" aria-hidden="true"><use href="#ms-{name}"/></svg>'


def day(iso):
    return date.fromisoformat(iso).strftime("%a %-d %b")


def ist(iso):
    return (datetime.fromisoformat(iso.replace("Z", "+00:00").replace(" ", "T")) + IST).strftime("%H:%M IST")


def grp(n):
    """Indian digit grouping: 2,13,564."""
    s = f"{int(round(abs(n)))}"
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def inr(v, sign=False):
    if v is None:
        return "—"
    s = "₹" + grp(v)
    if sign:
        return ("+" if v > 0 else "−" if v < 0 else "") + s
    return ("−" if v < 0 else "") + s


def money(v, pct=None, big=False):
    """A signed money result: colour plus an arrow icon, never colour alone."""
    if v is None:
        return '<span class="muted">—</span>'
    d = "up" if v > 0 else "down" if v < 0 else "flat"
    ic = {"up": "arrow_upward", "down": "arrow_downward", "flat": "remove"}[d]
    tail = f'<span class="pc">{pct:+.1f}%</span>' if pct is not None else ""
    return f'<span class="mny {d}{" big" if big else ""}">{icon(ic)}{inr(v, True)}</span>{tail}'


def state(t):
    if t["price_pending"] or t["unrealised_pnl"] is None:
        return "pending"
    return "with" if t["unrealised_pnl"] > 0 else "against"  # every trade today is on an "up" call; "down" flips


def side_tag(f, short=False):
    return f'<span class="side-tag {f}" data-tip="{e(SIDE_TIP[f])}"><i></i>{SIDE_SHORT[f] if short else SIDE[f]}</span>'


def info(text, label="Details"):
    return f'<button class="info" type="button" aria-label="{label}" data-tip="{e(text)}">{icon("info")}</button>'


def wl_bar(w, a, pend=0):
    n = w + a + pend
    if not n:
        return '<div class="wl empty"></div>'
    return (f'<div class="wl" role="img" aria-label="{w} going as predicted, {a} going against">'
            f'<span class="w" style="flex:{w}"></span><span class="a" style="flex:{a}"></span>'
            f'{f"<span class=p style=flex:{pend}></span>" if pend else ""}</div>')


def range_dot(t):
    lo, hi = t["lo80"], t["hi80"]
    if lo is None or hi is None or hi <= lo:
        return ""
    pos = lambda x: min(100, max(0, (x - lo) / (hi - lo) * 100))
    now = t["exit_or_last_price"] or t["entry_price"]
    inside = lo <= now <= hi
    tip = f"Expected price at the sale, 8 in 10 times: {inr(lo)} to {inr(hi)}. Bought {inr(t['entry_price'])}, now {inr(now)}."
    return (f'<span class="rng" data-tip="{e(tip)}"><span class="trk"><span class="b50" style="left:{pos(t["lo50"]):.0f}%;right:{100 - pos(t["hi50"]):.0f}%"></span>'
            f'<span class="buy" style="left:{pos(t["entry_price"]):.0f}%"></span><span class="now {"" if inside else "out"}" style="left:{pos(now):.0f}%"></span></span>'
            f'<small>{inr(now)}</small></span>')


def pf(x):
    return f"{x:+.1f}%".replace("-", "−")


def cause(t):
    """One plain line: why it moved, from the latest intraday check (market x the stock's usual sensitivity, its
    sector, and the rest = the company's own move)."""
    c = why["checks"].get(t["ticker"])
    if not c:
        return "No intraday check yet."
    m, s, r, b = c["bench"] * 100, c["sector"] * 100, c["residual"] * 100, c["beta"]
    pull = b * m
    if abs(r) > abs(pull):
        main = f"Fell mostly on its own ({pf(r)}); the market added {pf(pull)}." if r < 0 else f"The market pulled it down ({pf(pull)}); the company itself held up ({pf(r)})."
    else:
        main = f"Fell with the whole market (Nifty {pf(m)}, so {pf(pull)} for this stock); {pf(r)} on its own."
    return main + f" Its sector {pf(s)}."


def popover(t):
    c = why["checks"].get(t["ticker"]) or {}
    pr = why["preds"].get(t["id"].split(":", 1)[1], {}) if t["id"].startswith("acc:") else {}
    chance = pr.get("prob_up")
    exp = (f"Expected: {'a ' + format(chance * 100, '.0f') + '% chance of a rise; ' if chance else 'a rise (this benchmark buys without a forecast); '}"
           f"price at the sale {inr(t['lo80'])} to {inr(t['hi80'])} (8 in 10 times).")
    happened = f"So far: bought {inr(t['entry_price'])} at the open of {day(t['entry_date'])}, now {inr(t['exit_or_last_price'])} ({t['unrealised_pct']:+.1f}%)."
    note = why["notes"].get(t["ticker"])
    parts = [exp, happened, "Why: " + cause(t)]
    parts.append(f"Sells at the close of {day(t['exit_date'])}. Result so far is before fees. ")
    return " ".join(parts)


def progress(t):
    k = t["horizon_days"]
    done = 1  # the entry session is over (the build is after the close of Mon 12 Oct)
    return f'<span class="prog" data-tip="Held {done} of {k + 1} sessions; sells at the close of {day(t["exit_date"])}."><span style="width:{done / (k + 1) * 100:.0f}%"></span></span>'


def trade_row(ts, story, hide=None):
    """One row per company and side in a group: identical trades of several strategies of the same side (for example
    the two benchmarks buying the same stock) are one row, their results added."""
    t = ts[0]
    st = state(t)
    flagged = any((x.get("check") or {}).get("flagged") for x in ts)
    mark = icon("warning", "ms bad") if flagged else ""
    total = None if st == "pending" else sum(x["unrealised_pnl"] for x in ts)
    so_far = '<span class="muted">no price yet</span>' if st == "pending" else money(total, t["unrealised_pct"])
    who_names = " + ".join(strat.get(x["strategy_id"], x["strategy_id"]) for x in ts)
    times = f'<span class="cnt" data-tip="{len(ts)} paper trades, one per strategy, added together">×{len(ts)}</span>' if len(ts) > 1 else ""
    who = f'{side_tag(t["family"], True)}{times}<small class="nm">{e(who_names)}</small>'
    link = f'<a class="story" href="{story}">Full story {icon("chevron_right")}</a>'
    reason = ""
    if st == "against":
        note = why["notes"].get(t["ticker"])
        chip = f'<button class="note-chip" type="button" data-tip="{e("AI note at the latest check: " + note)}">{icon("description")}AI note</button>' if note else ""
        reason = f'<tr class="why"><td colspan="5"><div class="why-line">{icon("help")}<span>{e(cause(t))}</span>{chip}{link}</div></td></tr>'
    extra = f" Same trade for: {who_names}." if len(ts) > 1 else ""
    attr = f' hidden data-g="{hide}"' if hide else ""
    return f"""<tbody class="r {st}"{attr}><tr>
<td><b class="tk">{e(t['ticker'])}</b><small class="nm">{e(names.get(t['ticker'], t['ticker']))}</small><span class="show-s">{side_tag(t["family"], True)}{times}</span></td>
<td class="hide-s">{who}</td>
<td class="hide-s">{range_dot(t)}</td>
<td class="num res">{mark}{so_far}</td>
<td class="i">{info(popover(t) + extra, 'Why')}</td></tr>{reason}</tbody>"""


def totals(ts):
    vals = [t["unrealised_pnl"] for t in ts if state(t) != "pending"]
    return sum(vals) if vals else None


def side_strip(ts, fams):
    cells = []
    for f in fams:
        mine = [t for t in ts if t["family"] == f]
        if not mine:
            note = rule_none() if f == "rule" else "No trade in this hold"
            cells.append(f'<div class="ss none">{side_tag(f, True)}<div class="ssv muted">{note}</div></div>')
            continue
        w = sum(1 for t in mine if state(t) == "with")
        a = sum(1 for t in mine if state(t) == "against")
        cells.append(f"""<div class="ss">{side_tag(f, True)}<div class="ssn"><b>{len(mine)}</b> open</div>{wl_bar(w, a)}
<div class="ssc"><span class="ok">{icon('check')}{w}</span><span class="bad">{icon('close')}{a}</span><span class="ssm">{money(totals(mine))}</span></div></div>""")
    return f'<div class="strip">{"".join(cells)}</div>'


def rule_none():
    best = max((v["prob_up"] for k, v in why["preds"].items() if k.startswith("rule.") and v["prob_up"] is not None), default=None)
    tip = f"Rule strategies buy only when the signal model gives a rise at least a 55% chance. Today’s highest chance was {best * 100:.0f}%, so they stayed out. Staying out is a result too." if best else ""
    return f'No trades today: the signal model saw no clear rise {info(tip, "Why no rule trades")}'


def group(kind, ts, bid, story):
    if not ts:
        return ""
    head = {"with": ("check", "ok", "Going as predicted"), "against": ("close", "bad", "Going against the prediction"), "pending": ("pending", "", "No price yet")}[kind]
    if kind == "against":
        ts = sorted(ts, key=lambda t: (not (t.get("check") or {}).get("flagged"), t["unrealised_pnl"] or 0))
    else:
        ts = sorted(ts, key=lambda t: -(t["unrealised_pnl"] or 0))
    rows = {}
    for t in ts:
        rows.setdefault((t["ticker"], t["family"], t["entry_price"], t["unrealised_pnl"]), []).append(t)
    rows = list(rows.values())
    shown, rest = rows[:3], rows[3:]
    more = ""
    if rest:
        more = ("".join(trade_row(r, story, f"{bid}-{kind}") for r in rest) +
                f'<tbody><tr class="moreline"><td colspan="5"><button class="md-btn text small" type="button" data-more="{bid}-{kind}">Show {len(rest)} more {icon("expand_more")}</button></td></tr></tbody>')
    return (f'<tbody><tr class="gh {kind}"><td colspan="5"><span class="ghl">{icon(head[0], "ms " + head[1])}{head[2]}<span class="cnt">{len(ts)}</span></span>'
            f'<span class="ghr">{money(totals(ts))}</span></td></tr></tbody>{"".join(trade_row(r, story) for r in shown)}{more}')


def hold_block(k, ts, bid, fams, story):
    exits = sorted({t["exit_date"] for t in ts})
    g = {s: [t for t in ts if state(t) == s] for s in ("with", "against", "pending")}
    return f"""<article class="md-card hold">
<header class="bh"><div class="bt"><h3>{k}-day hold</h3><div class="bs">{icon('event')}Sells at the close of {' · '.join(day(x) for x in exits)} {progress(ts[0])}</div></div>
<div class="bn"><div class="v">{money(totals(ts), big=True)}</div><div class="l">so far on {len(ts)} open, before fees</div></div></header>
{side_strip(ts, fams)}
<div class="md-table-wrap"><table class="md-table tr3"><thead><tr><th>Company</th><th class="hide-s">Who</th><th class="hide-s" data-tip="Where the price sits in the expected range at the sale: the bar is the range (8 in 10 times), the tick is the buy price, the dot is now.">Price vs expected</th><th class="num">So far</th><th><span class="sr">Details</span></th></tr></thead>
{group('against', g['against'], bid, story)}{group('with', g['with'], bid, story)}{group('pending', g['pending'], bid, story)}</table></div>
</article>"""


def holds(ts, prefix, fams, story):
    return "".join(hold_block(k, [t for t in ts if t["horizon_days"] == k], f"{prefix}{k}", fams, story)
                   for k in sorted({t["horizon_days"] for t in ts}))


at = p["all_trades"]
S = {(r["scope"], r["family"], r["period"]): r for r in at["summary"]}
A = S[("all", "all", "to_date")]
total = A["unrealised_pnl"]
traded = sum((t["entry_price"] or 0) * (t["quantity"] or 0) for t in acc)
nw = sum(1 for t in acc if state(t) == "with")
na = sum(1 for t in acc if state(t) == "against")


def side_card(f):
    mine = [t for t in acc if t["family"] == f]
    r = S[("all", f, "to_date")]
    if not mine:
        return f"""<section class="md-card sc none"><div class="sch">{side_tag(f)}</div><div class="sce">{icon('remove')}<div>{rule_none()}</div></div>
<div class="scf"><span>Finished</span><b>{r['closed']}</b><span>Won · lost</span><b>{r['wins']} · {r['losses']}</b></div></section>"""
    w = sum(1 for t in mine if state(t) == "with")
    a = sum(1 for t in mine if state(t) == "against")
    return f"""<section class="md-card sc"><div class="sch">{side_tag(f)}{info(SIDE_TIP[f], 'About this side')}</div>
<div class="scv">{money(totals(mine), big=True)}</div><div class="scl">so far on {len(mine)} open trades, before fees</div>
{wl_bar(w, a)}<div class="ssc"><span class="ok">{icon('check')}{w} going as predicted</span><span class="bad">{icon('close')}{a} going against</span></div>
<div class="scf"><span>Finished</span><b>{r['closed']}</b><span>Won · lost</span><b>{r['wins']} · {r['losses']}</b></div></section>"""


H = {r["family"]: r for r in at["summary"] if r["scope"] == "head_to_head" and r["period"] == "to_date"}


def pick_side(f):
    mine = [t for t in h2h if t["family"] == f]
    if not mine:
        return f'<div class="ps none">{side_tag(f)}<div class="muted psn">No pick yet: no rule strategy cleared its 55% bar {info("Each day the strongest rule strategy picks one trade per company, but only from predictions that cleared its bar. None did today.", "Why no rule picks")}</div></div>'
    w = sum(1 for t in mine if state(t) == "with")
    a = sum(1 for t in mine if state(t) == "against")
    return f'<div class="ps">{side_tag(f)}<div class="psv">{money(totals(mine), big=True)}</div><div class="scl">so far on {len(mine)} open picks</div>{wl_bar(w, a)}<div class="ssc"><span class="ok">{icon("check")}{w}</span><span class="bad">{icon("close")}{a}</span><span>finished {H[f]["closed"]}</span></div></div>'


# Finished trades: an illustration with sample numbers (nothing has finished yet): today's 1-day holds as if sold at
# the latest price, minus a sample fee of 0.24%.
def finished():
    ones = sorted([t for t in acc if t["horizon_days"] == 1 and state(t) != "pending"], key=lambda t: t["unrealised_pnl"])[:2] + \
        sorted([t for t in acc if t["horizon_days"] == 1 and state(t) == "with"], key=lambda t: -t["unrealised_pnl"])[:1]
    rows = []
    for t in ones:
        net = t["unrealised_pnl"] - round(t["entry_price"] * t["quantity"] * 0.0024)
        won = net > 0
        line = "Rose against a falling market: company-specific gain." if won else cause(t).replace("Fell", "It fell")
        tipt = (f"{'Went as predicted' if won else 'Went against the prediction'}. Bought {inr(t['entry_price'])}, sold {inr(t['exit_or_last_price'])}. "
                f"{line} After market fees {inr(net, True)}; after your own broker’s fees about {inr(net - 400, True)}. The end-of-day AI reason and any lesson appear here too.")
        rows.append(f"""<tbody class="r {'with' if won else 'against'}"><tr><td><b class="tk">{e(t['ticker'])}</b><small class="nm">{e(names[t['ticker']])}</small><span class="show-s">{side_tag(t['family'], True)}</span></td>
<td class="hide-s">{side_tag(t['family'], True)}<small class="nm">{e(strat[t['strategy_id']])}</small></td>
<td>{('<span class="mb-label success">' + icon('check') + 'Won</span>') if won else ('<span class="mb-label danger">' + icon('close') + 'Lost</span>')}</td>
<td class="num">{money(net)}</td><td class="i">{info(tipt, 'Why')}</td></tr>
{'' if won else f'<tr class="why"><td colspan="5"><span class="why-line">{icon("help")}{e(line)}</span><a class="story" href="story.html">Full story {icon("chevron_right")}</a></td></tr>'}</tbody>""")
    return "".join(rows)


SPRITE = re.sub(r"<\?xml[^>]*>", "", read("design/system/icons.svg"))
CSS = (read("web/styles/fonts.css").replace('url("/fonts/', 'url("../../../web/public/fonts/') + read("web/styles/tokens.css")
       + read("design/system/tokens-dark.css") + read("web/styles/components.css"))
PAGE_CSS = """
body{background:var(--md-sys-color-surface-container-low);margin:0;color:var(--md-sys-color-on-surface)}
main{max-width:1120px;margin:0 auto;padding:24px 24px 48px}
.ann{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-tertiary-container);background:var(--md-sys-color-tertiary-container);border-radius:12px;padding:8px 16px;margin:0 0 16px}
.ms{width:18px;height:18px;vertical-align:-4px;fill:currentColor;flex:none}
.muted{color:var(--md-sys-color-on-surface-variant)} .ok{color:var(--mb-color-up)} .bad{color:var(--mb-color-down)}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:24px}
.top h1{font:var(--md-sys-typescale-headline-small);margin:0 16px 0 0}
h2.q{font:var(--md-sys-typescale-title-large);margin:40px 0 16px;letter-spacing:-.01em}
h2.q small{display:block;font:var(--md-sys-typescale-body-medium);color:var(--md-sys-color-on-surface-variant);margin-top:4px}
.md-card{box-shadow:none;border-radius:20px;padding:24px}
.hero{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:32px;align-items:center;padding:32px}
.hero .lbl{font:var(--md-sys-typescale-label-large);color:var(--md-sys-color-on-surface-variant)}
.hero .hv{font:600 44px/52px var(--md-ref-typeface-brand);letter-spacing:-.02em;margin:8px 0 4px;font-variant-numeric:tabular-nums}
.hero .hs{font:var(--md-sys-typescale-body-large);color:var(--md-sys-color-on-surface-variant)}
.hero .next{display:inline-flex;gap:8px;align-items:center;margin-top:16px;padding:8px 16px;border-radius:999px;background:var(--md-sys-color-surface-container);font:var(--md-sys-typescale-label-large)}
.hero .facts{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.fact .fv{font:600 24px/32px var(--md-ref-typeface-brand);font-variant-numeric:tabular-nums} .fact .fl{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant)}
.hero .wlw{grid-column:2;margin-top:8px}
.mny{display:inline-flex;align-items:center;gap:2px;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums}
.mny .ms{width:16px;height:16px} .mny.up{color:var(--mb-color-up)} .mny.down{color:var(--mb-color-down)} .mny.flat{color:var(--md-sys-color-on-surface-variant)}
.mny.big{font:600 28px/36px var(--md-ref-typeface-brand)} .mny.big .ms{width:24px;height:24px}
.hero .hv .mny.big{font:inherit} .hero .hv .ms{width:36px;height:36px}
.pc{color:var(--md-sys-color-on-surface-variant);font-size:12px;margin-left:8px;font-variant-numeric:tabular-nums}
.wl{display:flex;height:8px;border-radius:999px;overflow:hidden;background:var(--md-sys-color-surface-container-high);gap:2px;margin:16px 0 8px}
.wl .w{background:var(--mb-color-up)} .wl .a{background:var(--mb-color-down)} .wl .p{background:var(--md-sys-color-outline-variant)} .wl.empty{opacity:.5}
.ssc{display:flex;gap:16px;flex-wrap:wrap;font:var(--md-sys-typescale-body-small)} .ssc span{display:inline-flex;align-items:center;gap:4px} .ssc .ms{width:16px;height:16px}
.sides{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.sc .sch{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.scl{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant);margin-top:4px}
.scf{display:grid;grid-template-columns:auto auto auto auto;justify-content:start;gap:4px 8px;margin-top:16px;padding-top:16px;border-top:1px solid var(--md-sys-color-surface-container-high);font:var(--md-sys-typescale-body-small)}
.scf span{color:var(--md-sys-color-on-surface-variant)} .scf b{margin-right:16px}
.sc.none .sce{display:flex;gap:8px;color:var(--md-sys-color-on-surface-variant);font:var(--md-sys-typescale-body-medium);min-height:96px}
.side-tag{display:inline-flex;align-items:center;gap:8px;font:600 13px/20px var(--md-ref-typeface-plain);white-space:nowrap}
.side-tag i{width:10px;height:10px;border-radius:3px;display:inline-block}
.side-tag.rule i{background:var(--mb-chart-1)} .side-tag.baseline i{background:var(--mb-chart-2)} .side-tag.ai i{background:var(--mb-chart-3)}
.info{border:0;background:none;color:var(--md-sys-color-on-surface-variant);cursor:pointer;border-radius:999px;width:32px;height:32px;display:inline-grid;place-items:center;vertical-align:middle}
.info:hover,.info:focus-visible{background:var(--md-sys-color-surface-container-high);color:var(--md-sys-color-primary)}
.duo{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:16px;margin-top:16px}
.picks{display:grid;grid-template-columns:1fr 1fr;gap:24px} .ps .psv{margin-top:16px} .psn{margin-top:16px;font:var(--md-sys-typescale-body-medium)}
.cardh{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px} .cardh h3{font:var(--md-sys-typescale-title-medium);margin:0}
.own .ov{font:600 28px/36px var(--md-ref-typeface-brand)} .own p{margin:4px 0 16px}
.hold{margin-top:16px} .bh{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap;margin-bottom:24px}
.bh h3{font:var(--md-sys-typescale-title-large);margin:0} .bs{display:flex;align-items:center;gap:8px;font:var(--md-sys-typescale-body-medium);color:var(--md-sys-color-on-surface-variant);margin-top:4px}
.bn{text-align:right} .bn .l{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant)}
.prog{display:inline-block;width:72px;height:6px;border-radius:999px;background:var(--md-sys-color-surface-container-high);overflow:hidden}
.prog span{display:block;height:100%;background:var(--md-sys-color-primary)}
.strip{display:grid;grid-template-columns:repeat(var(--n,3),minmax(0,1fr));gap:8px;margin-bottom:24px}
.ss{background:var(--md-sys-color-surface-container-low);border-radius:16px;padding:16px} .ss .wl{margin:8px 0}
.ssn{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant);margin-top:8px} .ssn b{font:600 16px/24px var(--md-ref-typeface-brand);color:var(--md-sys-color-on-surface)}
.ssm{margin-left:auto} .ss.none .ssv{font:var(--md-sys-typescale-body-small);margin-top:8px}
.md-table.tr3 th{background:none;border-bottom:1px solid var(--md-sys-color-surface-container-high);padding:8px 8px;font:500 12px/16px var(--md-ref-typeface-plain);letter-spacing:.02em;text-transform:none}
.md-table.tr3 td{border-bottom:0;padding:12px 8px} .md-table.tr3 tbody.r{border-top:1px solid var(--md-sys-color-surface-container-high)}
.tk{display:block;font-weight:600} .nm{display:block;font-size:12px;color:var(--md-sys-color-on-surface-variant);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
tr.gh td{padding:24px 8px 8px!important;font:var(--md-sys-typescale-title-small)} .ghl{display:inline-flex;align-items:center;gap:8px} .ghr{float:right}
tr.gh.with .ghl{color:var(--mb-color-up)} tr.gh.against .ghl{color:var(--mb-color-down)}
td .cnt{margin-left:8px}
.cnt{font:var(--md-sys-typescale-label-medium);background:var(--md-sys-color-surface-container-high);color:var(--md-sys-color-on-surface-variant);border-radius:999px;padding:0 8px}
tr.why td{padding:0 8px 16px!important} .why-line{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant);background:var(--md-sys-color-surface-container-low);border-radius:8px;padding:8px 12px}.why-line>span{flex:1 1 280px}.note-chip{display:inline-flex;gap:4px;align-items:center;border:0;border-radius:999px;padding:2px 10px;background:var(--md-sys-color-secondary-container);color:var(--md-sys-color-on-secondary-container);font:var(--md-sys-typescale-label-medium);cursor:pointer}.note-chip .ms{width:14px;height:14px}
.why-line .ms{width:16px;height:16px;color:var(--md-sys-color-primary);margin-top:1px}
.story{display:inline-flex;align-items:center;font:var(--md-sys-typescale-label-large);color:var(--md-sys-color-primary);text-decoration:none;white-space:nowrap} .story .ms{width:18px;height:18px}
.res .ms.bad{width:16px;height:16px;margin-right:4px} td.i{width:40px;text-align:right}
.rng{display:inline-flex;align-items:center;gap:8px} .rng small{font-size:12px;color:var(--md-sys-color-on-surface-variant);font-variant-numeric:tabular-nums}
.trk{position:relative;width:96px;height:8px;border-radius:999px;background:var(--md-sys-color-surface-container-high)}
.trk .b50{position:absolute;top:0;bottom:0;border-radius:999px;background:var(--mb-chart-band-50,var(--md-sys-color-primary-container))}
.trk .buy{position:absolute;top:-3px;width:2px;height:14px;background:var(--md-sys-color-on-surface-variant)}
.trk .now{position:absolute;top:-2px;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:var(--md-sys-color-primary);border:2px solid var(--md-sys-color-surface-container-lowest)}
.trk .now.out{background:var(--mb-color-warn)}
tr.moreline td{padding:8px!important}
.empty-st{display:flex;gap:16px;align-items:center;padding:16px;border-radius:16px;background:var(--md-sys-color-surface-container-low)}
.empty-st .ei{width:48px;height:48px;border-radius:16px;display:grid;place-items:center;background:var(--md-sys-color-primary-container);color:var(--md-sys-color-on-primary-container)} .empty-st .ei .ms{width:24px;height:24px}
.empty-st b{display:block;font:var(--md-sys-typescale-title-small)} .empty-st span{font:var(--md-sys-typescale-body-medium);color:var(--md-sys-color-on-surface-variant)}
.sample{display:inline-block;font:var(--md-sys-typescale-label-small);color:var(--mb-color-on-warn-container);background:var(--mb-color-warn-container);border-radius:6px;padding:2px 8px}
.learn{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.lc h4{display:flex;align-items:center;gap:8px;font:var(--md-sys-typescale-title-small);margin:0 0 8px} .lc .ms{color:var(--md-sys-color-primary)}
.lc p{font:var(--md-sys-typescale-body-medium);margin:0 0 8px} .lc .who{font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant)}
.chipline{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.auto{background:var(--mb-color-up-container);color:var(--mb-color-on-up-container)} .appr{background:var(--mb-color-warn-container);color:var(--mb-color-on-warn-container)} .never{background:var(--md-sys-color-surface-container-high);color:var(--md-sys-color-on-surface-variant)}
.pill{font:var(--md-sys-typescale-label-medium);border-radius:999px;padding:2px 12px;display:inline-flex;gap:4px;align-items:center} .pill .ms{width:14px;height:14px}
blockquote{margin:8px 0;padding:8px 16px;border-left:3px solid var(--md-sys-color-primary);font:var(--md-sys-typescale-body-medium);color:var(--md-sys-color-on-surface)}
.show-s{display:none}.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
#pop{position:fixed;z-index:50;display:none}
footer.f{margin-top:40px;font:var(--md-sys-typescale-body-small);color:var(--md-sys-color-on-surface-variant);display:flex;gap:16px;flex-wrap:wrap}
@media (max-width:900px){.hero{grid-template-columns:minmax(0,1fr);gap:24px}.hero .wlw{grid-column:1}.sides,.learn{grid-template-columns:minmax(0,1fr)}.duo{grid-template-columns:minmax(0,1fr)}}
@media (max-width:640px){main{padding:16px 16px 40px}.md-card{padding:16px;border-radius:16px}.hero{padding:24px 16px}.hero .hv{font-size:36px;line-height:44px}
.hide-s{display:none}.show-s{display:flex!important;align-items:center;margin-top:4px}.strip{grid-template-columns:minmax(0,1fr)}.ss{padding:12px 16px}.ss .ssn{display:inline-block;margin:0 0 0 8px}
.picks{grid-template-columns:minmax(0,1fr)}.nm{max-width:110px}.pc{display:none}.why-line{max-width:none}.story{padding:4px 0}
.md-table.tr3 td,.md-table.tr3 th{padding-left:4px;padding-right:4px}.bn{text-align:left}.mny.big{font-size:24px;line-height:32px}}
"""
JS = """
const pop=document.getElementById('pop');let pinned=null;
function show(el){pop.textContent=el.dataset.tip;pop.style.display='block';const r=el.getBoundingClientRect();const w=Math.min(340,innerWidth-32);pop.style.maxWidth=w+'px';
let x=Math.min(Math.max(16,r.right-w),innerWidth-w-16),y=r.bottom+8;pop.style.left=x+'px';pop.style.top=y+'px';const h=pop.offsetHeight;if(y+h>innerHeight-8)pop.style.top=Math.max(8,r.top-h-8)+'px'}
function hide(){pop.style.display='none';pinned=null}
document.addEventListener('mouseover',ev=>{const el=ev.target.closest('[data-tip]');if(el&&!pinned)show(el)});
document.addEventListener('mouseout',ev=>{if(!pinned&&ev.target.closest('[data-tip]'))hide()});
document.addEventListener('click',ev=>{const m=ev.target.closest('[data-more]');if(m){document.querySelectorAll('[data-g="'+m.dataset.more+'"]').forEach(x=>x.hidden=false);m.closest('tbody').remove();return}
const el=ev.target.closest('[data-tip]');if(el){ev.preventDefault();pinned=el;show(el)}else hide()});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')hide()});
"""


def doc(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{CSS}{PAGE_CSS}</style></head><body>{SPRITE}<main>{body}</main>
<div id="pop" class="md-tooltip-rich" role="tooltip"></div><script>{JS}</script></body></html>"""


paper = '<span class="mb-label paper" data-tip="Every figure is Paper until a strategy passes the go-live test. A paper trade is a record, never an order; nothing here is advice.">' + icon("science") + "Paper only — no proven edge yet</span>"
review = json.loads(why.get("review_findings") or "[]")
first_finding = review[0]["text"] if review else ""

body = f"""<p class="ann"><b>Mockup v3 (UX3)</b> · real India data, Mon 12 Oct 2026, 18:31 IST, on the app’s tokens, components and icons (light and dark). Tinted notes like this one are not on the page. Hover or tap any ⓘ, “Why” or underlined label.</p>
<div class="top"><h1>Paper portfolio</h1>{paper}<span class="md-chip small">{icon('schedule')}prices Mon 12 Oct, 14:05 IST</span><span class="md-chip small">{icon('public')}India · NSE</span></div>

<section class="md-card hero" aria-label="Am I up or down?">
 <div><div class="lbl">Every strategy’s paper trades, open now {info('Each strategy’s every qualifying prediction is a paper trade of ₹1,00,000, bought at the open and sold at the close k sessions later. Before fees: fees are taken when a trade sells.', 'About this number')}</div>
  <div class="hv">{money(total, big=True)}</div>
  <div class="hs">{pf(total / traded * 100)} on ₹{traded / 1e7:.2f} crore in {A['open']} open trades, before fees</div>
  <div class="next">{icon('event')}Nothing finished yet — first results Tue 13 Oct, ~17:45 IST</div></div>
 <div><div class="facts"><div class="fact"><div class="fv">{A['open']}</div><div class="fl">open</div></div><div class="fact"><div class="fv">{A['closed']}</div><div class="fl">finished</div></div><div class="fact"><div class="fv">{A['wins']} · {A['losses']}</div><div class="fl">won · lost</div></div></div>
  {wl_bar(nw, na)}<div class="ssc"><span class="ok">{icon('check')}{nw} going as predicted</span><span class="bad">{icon('close')}{na} going against</span></div></div>
</section>

<h2 class="q">Which bets are working?<small>The three kinds of strategy side by side. Never added together with the daily picks or your own trades.</small></h2>
<div class="sides">{''.join(side_card(f) for f in FAMS)}</div>
<div class="duo">
 <section class="md-card"><div class="cardh"><h3>Rule vs AI: the daily picks</h3>{info('Each day the strongest rule strategy and the strongest AI trader each pick their trade per company. These come from the same predictions as above, so they are counted apart.', 'About the picks')}</div><div class="picks">{pick_side('rule')}{pick_side('ai')}</div></section>
 <section class="md-card own"><div class="cardh"><h3>Your own trades</h3>{info('Your manual paper trades, after your own broker’s fees.', 'About your trades')}</div><div class="ov">None yet</div><p class="muted">Shows here after the next run imports it.</p><button class="md-btn tonal" type="button">{icon('receipt_long')}Add a paper trade</button></section>
</div>

<h2 class="q">Finished trades<small>Did each one work, and why.</small></h2>
<section class="md-card">
 <div class="empty-st"><div class="ei">{icon('event')}</div><div><b>Nothing has finished yet</b><span>The first 1-day holds sell at the close of Tue 13 Oct. Results, with the reason for each, appear after the after-close run, ~17:45 IST.</span></div></div>
 <p class="ann" style="margin-top:24px">Below: how a finished day will look, as an <b>illustration with sample numbers</b> (today’s 1-day holds as if sold at the latest price, minus a sample fee). Filter chips pick the day sold; a strip compares the sides; each loss carries its one-line reason.</p>
 <div class="chipline" style="margin-bottom:16px"><button class="md-chip filter small" aria-pressed="true">Tue 13 Oct</button><button class="md-chip filter small" aria-pressed="false">Mon 12 Oct</button><button class="md-chip filter small" aria-pressed="false">Fri 9 Oct</button><span class="sample">illustration · sample numbers</span></div>
 <div class="md-table-wrap"><table class="md-table tr3"><thead><tr><th>Company</th><th class="hide-s">Who</th><th>Result</th><th class="num">After fees</th><th><span class="sr">Details</span></th></tr></thead>{finished()}</table></div>
</section>

<h2 class="q">Open trades, by how long they’re held<small>Losing trades first, each with a one-line reason. Sides compared in every block.</small></h2>
{holds(acc, 'a', FAMS, 'story.html')}

<h2 class="q">Open daily picks: Rule vs AI</h2>
{holds(h2h, 'h', ('rule', 'ai'), 'story.html')}

<h2 class="q">What the system learns<small>Honestly: only part of it learns by itself.</small></h2>
<div class="learn">
 <section class="md-card lc"><h4>{icon('history')}Lessons on finished AI forecasts</h4><p>After each AI forecast settles, a reviewer writes one short lesson. The AI forecaster reads them from the next morning.</p>
  <div class="chipline"><span class="pill auto">{icon('bolt')}Learns automatically</span></div><p class="who" style="margin-top:8px">None yet: the first AI forecasts settle from Thu 15 Oct. The other AI traders don’t read lessons.</p></section>
 <section class="md-card lc"><h4>{icon('description')}End-of-day reasons</h4><p>After each close, an AI analyst explains every Rule vs AI trade that finished, and the day’s biggest wins and misses.</p>
  <div class="chipline"><span class="pill never">{icon('info')}Explains, changes nothing</span></div><p class="who" style="margin-top:8px">First ones after the close of Tue 13 Oct.</p></section>
 <section class="md-card lc"><h4>{icon('science')}Weekly research review</h4><p>Every Friday evening (New York time) a research director proposes changes. Nothing changes until the owner approves.</p>
  <div class="chipline"><span class="pill appr">{icon('gavel')}Needs your approval</span></div>
  <blockquote>“{e(first_finding[:180])}…”</blockquote><p class="who">Week 41 · no change proposed · next review Fri 16 Oct</p></section>
</div>
<p class="muted" style="margin-top:16px">{icon('info')} Rule strategies and simple benchmarks never adjust themselves.</p>
<footer class="f"><span>{paper}</span><span>A paper trade is a record, never an order. Nothing here is advice.</span><span>Technical details ▸</span></footer>"""

open(os.path.join(OUT, "mockup-v3.html"), "w").write(doc("Paper portfolio mockup v3", body))

# ---------- the full story of one trade: LT, AI news & results (Sonnet), 5-day hold ----------
lt = next(t for t in acc if t["ticker"] == "LT" and t["strategy_id"] == "ai.news_results.sonnet.v1" and t["horizon_days"] == 5)
pr = why["preds"]["ai.news_results.sonnet.v1:2026-10-09-LT-5d"]
steps = why["lt_checks"]
c_last = steps[-1]
m, s, r, b = c_last["bench"] * 100, c_last["sector"] * 100, c_last["residual"] * 100, c_last["beta"]


def tl(icon_name, when, title, body_, tone=""):
    return f'<li class="{tone}"><span class="dot">{icon(icon_name)}</span><div><div class="when">{when}</div><b>{title}</b><div class="tb">{body_}</div></div></li>'


timeline = [
    tl("description", "Fri 9 Oct, after the close", "Predicted: a rise over 5 sessions",
       f"Chance of a rise <b>{pr['prob_up'] * 100:.0f}%</b> (its bar: 55%). In its words: <q>{e(pr['reason'])}</q>"),
    tl("receipt_long", "Mon 12 Oct, 09:15 IST", f"Bought {int(lt['quantity'])} shares at {inr(lt['entry_price'])}", "Paper only: the price is the session’s open."),
]
for c in steps:
    timeline.append(tl("sensors", f"Mon 12 Oct, {ist(c['check_at'])}", f"Check: {pf(c['ret'] * 100)} since the buy",
                       f"Market {pf(c['bench'] * 100)} · sector {pf(c['sector'] * 100)} · on its own {pf(c['residual'] * 100)}" +
                       (f"<blockquote>{e(c['note'])}</blockquote><small class='muted'>AI note, checked against the stored data</small>" if c.get("note") else ""), "bad"))
timeline += [
    tl("event", "Tue 13 – Mon 19 Oct", "More checks, a few times a session", "Each adds a line here.", "fut"),
    tl("gavel", "Mon 19 Oct, after the close (~17:45 IST)", "Sells at the close and is settled", "Result after fees, and the automatic reason: market, sector, news or company.", "fut"),
]

story = f"""<p class="ann"><b>“Full story” view, mockup v3.</b> Real stored data for one open trade. In the app this is the company page’s lifecycle view (/stocks/LT/lifecycle/2026-10-12), with the additions listed at the bottom.</p>
<div class="top"><a class="story" href="mockup-v3.html"><span style="transform:scaleX(-1);display:inline-flex">{icon('chevron_right')}</span>Back to the paper portfolio</a></div>
<section class="md-card hero">
 <div><div class="lbl">LT · Larsen &amp; Toubro · {side_tag('ai', True)} news &amp; results · 5-day hold</div>
  <div class="hv">{money(lt['unrealised_pnl'], big=True)}</div><div class="hs">{pf(lt['unrealised_pct'])} so far, before fees · <span class="bad">{icon('close')}going against the prediction</span></div>
  <div class="next">{icon('event')}Sells at the close of Mon 19 Oct {progress(lt)}</div></div>
 <div><div class="facts"><div class="fact"><div class="fv">{inr(lt['entry_price'])}</div><div class="fl">bought, Mon 12 Oct open</div></div><div class="fact"><div class="fv">{inr(lt['exit_or_last_price'])}</div><div class="fl">now, 14:05 IST</div></div><div class="fact"><div class="fv">{inr(lt['target_price'])}</div><div class="fl">middle guess at the sale</div></div></div>
  <div style="margin-top:16px">{range_dot(lt)} <span class="muted" style="font-size:12px">expected {inr(lt['lo80'])} – {inr(lt['hi80'])}</span></div></div>
</section>

<h2 class="q">Why is it going against the prediction?</h2>
<section class="md-card">
 <div class="attr">
  <div class="ar"><span>Whole market</span><div class="ab"><i class="neg" style="width:{abs(b * m) / abs(c_last['ret'] * 100) * 100:.0f}%"></i></div><b class="bad">{pf(b * m)}</b></div>
  <div class="ar"><span>LT on its own</span><div class="ab"><i class="neg" style="width:{abs(r) / abs(c_last['ret'] * 100) * 100:.0f}%"></i></div><b class="bad">{pf(r)}</b></div>
  <div class="ar tot"><span>Total since the buy</span><div class="ab"></div><b class="bad">{pf(c_last['ret'] * 100)}</b></div>
 </div>
 <p class="muted" style="margin:16px 0 0">Nifty fell {abs(m):.1f}%; LT usually moves {b:.2f}× the market, so the market explains {pf(b * m)}. Its sector (Construction) fell {abs(s):.1f}%. The two order-win announcements the trader relied on are exchange-confirmed; no new LT news today was confirmed.</p>
</section>

<h2 class="q">What happened, step by step</h2>
<section class="md-card"><ol class="tl">{''.join(timeline)}</ol></section>

<h2 class="q">What the system learned</h2>
<section class="md-card"><div class="learn">
 <div class="lc"><h4>{icon('history')}Lesson</h4><p class="who">Not yet. This trader doesn’t get lessons; only the AI forecaster does, and its LT forecast settles first.</p><span class="pill never">{icon('info')}None for this trader</span></div>
 <div class="lc"><h4>{icon('description')}End-of-day reason</h4><p class="who">Written after it sells, Mon 19 Oct, if it is one of the day’s Rule vs AI trades or biggest misses.</p><span class="pill never">{icon('info')}Explains only</span></div>
 <div class="lc"><h4>{icon('science')}Weekly review</h4><p class="who">Its result joins the review of Fri 23 Oct (New York evening). Any change needs the owner’s approval.</p><span class="pill appr">{icon('gavel')}Needs approval</span></div>
</div></section>
<p class="ann" style="margin-top:24px"><b>Data this view needs beyond today’s lifecycle page (additive):</b> each check’s market / sector / own split (intraday_checks), the deviation-explainer notes for the ticker (intraday_explanations), the lessons and end-of-day reasons for the page’s trades, the latest weekly review’s date and status. The prediction, its chance, the AI reason, the range, the checks and the settlement are already on it.</p>
<footer class="f"><span>{paper}</span><span>A paper trade is a record, never an order. Nothing here is advice.</span></footer>"""
STORY_CSS = """<style>
.attr{display:grid;gap:12px;max-width:640px}.ar{display:grid;grid-template-columns:140px 1fr 64px;gap:16px;align-items:center;font:var(--md-sys-typescale-body-medium)}
.ar b{text-align:right;font-variant-numeric:tabular-nums}.ab{height:10px;border-radius:999px;background:var(--md-sys-color-surface-container-high);overflow:hidden}.ab i{display:block;height:100%;background:var(--mb-color-down);border-radius:999px}
.ar.tot{border-top:1px solid var(--md-sys-color-surface-container-high);padding-top:12px}.ar.tot .ab{background:none}
ol.tl{list-style:none;margin:0;padding:0}ol.tl li{display:grid;grid-template-columns:40px 1fr;gap:16px;padding-bottom:24px;position:relative}
ol.tl li:not(:last-child)::before{content:"";position:absolute;left:19px;top:40px;bottom:0;width:2px;background:var(--md-sys-color-surface-container-high)}
ol.tl .dot{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:var(--md-sys-color-primary-container);color:var(--md-sys-color-on-primary-container)}
ol.tl li.bad .dot{background:var(--mb-color-down-container);color:var(--mb-color-on-down-container)} ol.tl li.fut .dot{background:var(--md-sys-color-surface-container-high);color:var(--md-sys-color-on-surface-variant)}
ol.tl .when{font:var(--md-sys-typescale-label-medium);color:var(--md-sys-color-on-surface-variant)} ol.tl b{font:var(--md-sys-typescale-title-small)} ol.tl .tb{font:var(--md-sys-typescale-body-medium);color:var(--md-sys-color-on-surface-variant);margin-top:4px}
ol.tl li.fut b,ol.tl li.fut .tb{color:var(--md-sys-color-on-surface-variant)}
@media (max-width:640px){.ar{grid-template-columns:100px 1fr 56px;gap:8px}}
</style>"""
open(os.path.join(OUT, "story.html"), "w").write(doc("Paper trade story mockup", body.replace(body, story)).replace("</head>", STORY_CSS + "</head>"))
print("wrote", OUT)
