#!/usr/bin/env python3
"""Build the self-contained HTML report for one market's day, and the report index.

Run after the filled report (reports/<market>/<session_date>.md, no AGENT markers left) has passed the report gate
(validate.py --stage report). Numbers, charts and labels come from the stored data (view_data.py); the narrative
(headline, top 3, sector notes, outlook, data quality) is copied from the filled report, with every cited news/filing
id turned into a link to its source. Writes reports/<market>/<session_date>.html (inline CSS/JS, data embedded as JSON,
no network needed), reports/<market>/index.html (every report day, newest first) and work/slack_<market>_files.json
(the files notify_slack.py attaches). Refuses a report that still has AGENT markers."""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from view_data import NEWS_ID, gather_view, safe_url
from marketbrief.core import cli, database, paths

META_RE = re.compile(r"<!-- report-meta: (\{.*?\}) -->")
CHART_FILES = ("ranges.png", "sectors.png", "track_record.png")   # charts.py, in thread order


# ---------- the filled markdown report -> narrative sections ----------

def _sections(md: str) -> list[tuple[str, list[str]]]:
    out, title, buf = [], "", []
    for line in md.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            out.append((title, buf))
            title, buf = line.lstrip("#").strip(), []
        else:
            buf.append(line)
    out.append((title, buf))
    return out


def _text(lines: list[str]) -> list[str]:
    return [l for l in lines if l.strip() and not l.strip().startswith("<!--") and not l.startswith("![")]


def _after_tables(lines: list[str]) -> list[str]:
    last = -1
    for i, l in enumerate(lines):
        if l.startswith("|") or l.strip() == "_none_":
            last = i
    return _text(lines[last + 1:])


def parse_report(md: str, sectors: list[str]) -> dict:
    """Narrative the agents wrote into the report skeleton (report.py), by marker. Script-written
    lines (tables, the regime and market lines, image links) are left out."""
    if re.search(r"<!--\s*AGENT:", md):
        raise ValueError("report still has AGENT markers; fill them first")
    secs = _sections(md)
    get = lambda pred: next((ls for t, ls in secs if pred(t)), [])  # noqa: E731
    out: dict = {"headline": _text(get(lambda t: t == "Headline")),
                 "top3": [re.sub(r"^\s*(?:[-*•]|\d+\.)\s*", "", l) for l in _text(get(lambda t: t.startswith("Top 3")))]}
    y = get(lambda t: t == "Yesterday")
    cut = next((i for i, l in enumerate(y) if l.startswith("Market on ")), len(y))
    out["yesterday"] = _text(y[:cut])
    today = [l for l in _after_tables(get(lambda t: t.startswith("Today")))
             if not re.match(r"^\d+ stock\(s\) have ranges made after", l)]
    out["calls"] = today
    out["outlook"] = _after_tables(get(lambda t: t.startswith("Tomorrow")))
    dq = get(lambda t: t == "Data quality")
    out["data_quality"] = _after_tables(dq) if any(l.startswith("|") or l.strip() == "_none_" for l in dq) else \
        [l for l in _text(dq) if not l.startswith("- Indicators:") and not l.startswith("- Regime notes:")]
    out["sectors"] = {}
    in_sectors = False
    for t, ls in secs:
        if t == "By sector":
            in_sectors = True
            continue
        if in_sectors and t in sectors:
            out["sectors"][t] = _text(ls)
        elif in_sectors and t not in sectors:
            in_sectors = False
    return out


# ---------- markdown-ish narrative -> safe HTML ----------

def _inline(text: str, sources: dict, used: set) -> str:
    # Markdown links the agent wrote become finished HTML first and are parked behind
    # placeholders, so later steps (escaping, emphasis, id links) never touch their URLs.
    # Only http(s) URLs become links; anything else stays visible as plain text.
    parked: list[str] = []

    def park(fragment: str) -> str:
        parked.append(fragment)
        return f"\x00{len(parked) - 1}\x00"

    def md_link(m):
        url = safe_url(m.group(2))
        if url is None:
            return park(html.escape(m.group(0), quote=False))
        return park(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">'
                    f'{html.escape(m.group(1), quote=False)}</a>')
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", md_link, text.replace("\x00", ""))  # NULs mark parked parts
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w/])_(.+?)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    def link(m):
        i = m.group(0)
        src = sources.get(i)
        if not src:
            return f'<span class="ref ref-missing" title="source id not found">{i}</span>'
        used.add(i)
        label = html.escape(src.get("source") or "source")
        title = html.escape(src.get("title") or "", quote=True)
        url = safe_url(src.get("url"))
        if url is None:  # known source without a safe link: name it, do not link it
            return f'<span class="ref" title="{title}">{label}</span>'
        return f'<a class="ref" href="{html.escape(url, quote=True)}" title="{title}" target="_blank" rel="noopener">{label}</a>'
    s = re.sub(r"\b(Bull|Bear):", r'<strong class="\1">\1:</strong>', s)  # before the id links: never in a title
    s = s.replace('class="Bull"', 'class="bull"').replace('class="Bear"', 'class="bear"')
    s = NEWS_ID.sub(link, s)
    return re.sub(r"\x00(\d+)\x00", lambda m: parked[int(m.group(1))], s)


def to_html(lines: list[str], sources: dict, used: set) -> str:
    out, items = [], []
    for l in lines:
        m = re.match(r"^\s*[-*]\s+(.*)", l)
        if m:
            items.append(f"<li>{_inline(m.group(1), sources, used)}</li>")
            continue
        if items:
            out.append("<ul>" + "".join(items) + "</ul>")
            items = []
        out.append(f"<p>{_inline(l, sources, used)}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "".join(out)


def narrative_html(parsed: dict, sources: dict) -> tuple[dict, set]:
    used: set = set()
    n = {k: to_html(parsed[k], sources, used) for k in ("headline", "yesterday", "calls", "outlook", "data_quality")}
    n["top3"] = [_inline(x, sources, used) for x in parsed["top3"][:3]]
    n["sectors"] = {k: to_html(v, sources, used) for k, v in parsed["sectors"].items()}
    return n, used


# ---------- page ----------

def build_page(view: dict, narrative: dict, links: dict) -> str:
    data = dict(view)
    data["narrative"], data["links"] = narrative, links
    data.pop("sources", None)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    meta = json.dumps({"session": view["session"], "regime": (view["regime"] or {}).get("code"),
                       "calls": view["counts"]["calls"], "late": view["counts"]["late_ranges"],
                       "headline": re.sub(r"<[^>]+>", "", narrative.get("headline", ""))[:240]},
                      ensure_ascii=False).replace("--", "- -")
    title = f"{view['name']} brief {view['session']}"
    return (PAGE.replace("__TITLE__", html.escape(title)).replace("__META__", meta)
            .replace("__CSS__", CSS).replace("__JS__", JS).replace("__DATA__", payload))


def build_index(market: str, name: str, folder: Path) -> str:
    rows = []
    for p in sorted(folder.glob("????-??-??.html"), reverse=True):
        m = META_RE.search(p.read_text()[:4000])
        meta = json.loads(m.group(1)) if m else {"session": p.stem}
        rows.append((p.name, meta))
    items = "".join(
        f'<li><a href="{html.escape(f)}"><span class="d">{html.escape(m.get("session", f))}</span>'
        f'<span class="r">{html.escape(str(m.get("regime") or ""))}</span>'
        f'<span class="c">{m.get("calls", 0)} call{"s" if m.get("calls", 0) != 1 else ""}</span></a>'
        f'<p>{html.escape(m.get("headline") or "")}</p></li>' for f, m in rows) or "<li>No reports yet.</li>"
    return INDEX.replace("__NAME__", html.escape(name)).replace("__CSS__", CSS).replace("__ITEMS__", items) \
        .replace("__MARKET__", html.escape(market))


def run(cfg: dict) -> dict:
    con = database.connect(cfg["market"])
    view = gather_view(cfg, con)
    folder = paths.ROOT / "reports" / cfg["market"]
    md_path = folder / f"{view['session']}.md"
    if not md_path.exists():
        raise SystemExit(f"{md_path} not found; run report.py and fill it first")
    parsed = parse_report(md_path.read_text(), list(cfg.get("sectors") or {}))
    narrative, _ = narrative_html(parsed, view["sources"])
    charts = folder / "charts" / view["session"]
    links = {"md": md_path.name, "index": "index.html",
             "charts": [f"charts/{view['session']}/{f}" for f in CHART_FILES if (charts / f).exists()]}
    page = build_page(view, narrative, links)
    out = folder / f"{view['session']}.html"
    out.write_text(page)
    (folder / "index.html").write_text(build_index(cfg["market"], cfg["name"], folder))
    manifest = {"market": cfg["market"], "session": view["session"], "html": str(out.relative_to(paths.ROOT)),
                "images": [str((charts / f).relative_to(paths.ROOT)) for f in CHART_FILES if (charts / f).exists()]}
    mpath = paths.ROOT / "work" / f"slack_{cfg['market']}_files.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2))
    return {"step": "html_report", "market": cfg["market"], "html": manifest["html"],
            "index": str((folder / "index.html").relative_to(paths.ROOT)), "slack_files": str(mpath.relative_to(paths.ROOT)),
            "images": manifest["images"], "bytes": len(page.encode())}


def main() -> int:
    cfg = cli.require_market(cli.market_arg(__doc__).parse_args())
    try:
        out = run(cfg)
    except ValueError as exc:
        print(json.dumps({"step": "html_report", "error": str(exc)}))
        return 1
    print(json.dumps(out, indent=2))
    return 0


# ---------- static parts (kept here so the output is one self-contained file) ----------

CSS = r"""
/* Layout: one reading column; summary, then one filter row scoping overview charts and company cards. */
:root{
  --page:#f4f4f1; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#6f6d68; --grid:#e1e0d9;
  --axis:#c3c2b7; --border:rgba(11,11,11,.10); --accent:#2a78d6; --accent-ink:#1c5cab;
  --band80:rgba(42,120,214,.16); --band50:rgba(42,120,214,.34); --late:rgba(137,135,129,.22);
  --up:#2a78d6; --down:#e34948; --call2:#eb6834; --warn-bg:#fff4dc; --warn-ink:#7a5200;
  --pill:#ecebe6; --font:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color-scheme:light;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#a3a198; --grid:#2c2c2a;
  --axis:#383835; --border:rgba(255,255,255,.10); --accent:#3987e5; --accent-ink:#86b6ef;
  --band80:rgba(57,135,229,.20); --band50:rgba(57,135,229,.42); --late:rgba(137,135,129,.28);
  --up:#3987e5; --down:#e66767; --call2:#d95926; --warn-bg:#3a2e12; --warn-ink:#f3cf83; --pill:#2a2a28;
  color-scheme:dark;}}
:root[data-theme="dark"]{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#a3a198; --grid:#2c2c2a;
  --axis:#383835; --border:rgba(255,255,255,.10); --accent:#3987e5; --accent-ink:#86b6ef;
  --band80:rgba(57,135,229,.20); --band50:rgba(57,135,229,.42); --late:rgba(137,135,129,.28);
  --up:#3987e5; --down:#e66767; --call2:#d95926; --warn-bg:#3a2e12; --warn-ink:#f3cf83; --pill:#2a2a28;
  color-scheme:dark;}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 var(--font);overflow-wrap:anywhere}
.wrap{max-width:980px;margin:0 auto;padding-inline:16px;padding-block:20px 48px;display:flex;flex-direction:column;gap:20px}
a{color:var(--accent-ink)} a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1,h2,h3{margin:0;text-wrap:balance;line-height:1.25}
h1{font-size:1.6rem;font-weight:650} h2{font-size:1.1rem;font-weight:650} h3{font-size:1.02rem;font-weight:650}
p{margin:0}
.eyebrow{font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600}
.sub{color:var(--ink2);font-size:.9rem}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:12px;min-width:0}
.regime{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;background:var(--pill);font-size:.8rem;font-weight:600;white-space:nowrap}
.pill.up{background:color-mix(in srgb,var(--up) 18%,transparent)} .pill.down{background:color-mix(in srgb,var(--down) 18%,transparent)}
.pill.late{background:var(--late)}
.headline p{font-size:1.05rem}
.top3{margin:0;padding-left:1.3em;display:flex;flex-direction:column;gap:4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.kpi{border-top:1px solid var(--grid);padding-top:8px}
.kpi .v{font-size:1.5rem;font-weight:650} .kpi .l{font-size:.8rem;color:var(--ink2)}
details{border-top:1px solid var(--grid);padding-top:8px}
details>summary{cursor:pointer;font-weight:600;color:var(--ink2);list-style-position:outside}
details[open]>summary{margin-bottom:8px}
.prose{display:flex;flex-direction:column;gap:8px;max-width:68ch}
.prose ul{margin:0;padding-left:1.2em;display:flex;flex-direction:column;gap:4px}
.warn{background:var(--warn-bg);color:var(--warn-ink);border-radius:8px;padding:8px 12px;font-size:.9rem}
dl.gloss{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0;font-size:.92rem}
dl.gloss dt{font-weight:600} dl.gloss dd{margin:0;color:var(--ink2)}
@media (max-width:560px){dl.gloss{grid-template-columns:1fr} dl.gloss dd{margin-bottom:6px}}
.filters{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--page);padding-block:8px;display:flex;flex-wrap:wrap;gap:10px;align-items:end;border-bottom:1px solid var(--grid)}
.filters label{display:flex;flex-direction:column;gap:2px;font-size:.75rem;color:var(--muted);font-weight:600;letter-spacing:.03em;text-transform:uppercase;min-width:0}
.filters select,.filters input{font:inherit;font-size:.95rem;padding:6px 8px;border:1px solid var(--axis);border-radius:8px;background:var(--surface);color:var(--ink);min-width:0;max-width:100%}
.filters button{font:inherit;font-size:.9rem;padding:6px 12px;border-radius:8px;border:1px solid var(--axis);background:transparent;color:var(--ink2);cursor:pointer}
.filters .count{font-size:.85rem;color:var(--ink2);margin-left:auto;padding-bottom:6px}
@media (max-width:700px){.filters{position:static} .filters label{flex:1 1 140px} .filters select,.filters input{width:100%}}
.charts{display:grid;grid-template-columns:1fr;gap:16px}
@media (min-width:860px){.charts{grid-template-columns:1fr 1fr} .charts .wide{grid-column:1 / -1}}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
/* keep chart text near its design size: a lone card or chart never scales its labels up */
.co svg{max-width:520px} .chart:not(.wide) svg{max-width:520px} .chart.wide svg{max-width:900px}
.chart .cap{font-size:.85rem;color:var(--ink2)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:.8rem;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;width:14px;height:10px;border-radius:2px}
.cards{display:grid;grid-template-columns:1fr;gap:16px}
@media (min-width:860px){.cards{grid-template-columns:1fr 1fr} .cards.one{grid-template-columns:1fr}}
.co header{display:flex;flex-direction:column;gap:4px}
.co .row{display:flex;justify-content:space-between;gap:8px;align-items:baseline;flex-wrap:wrap}
.co .tk{color:var(--muted);font-weight:500;font-size:.85rem;margin-left:6px}
.co .price{font-variant-numeric:tabular-nums;color:var(--ink2);font-size:.9rem}
.chg.up{color:var(--up)} .chg.down{color:var(--down)}
.rng{display:flex;flex-direction:column;gap:2px;border-top:1px solid var(--grid);padding-top:8px}
.rng .when{font-size:.8rem;color:var(--muted);font-weight:600;letter-spacing:.02em;text-transform:uppercase}
.rng .main{font-size:1rem} .rng .main b{font-variant-numeric:tabular-nums}
.rng .second{font-size:.88rem;color:var(--ink2)}
.rng.is-late .main{color:var(--ink2)}
.tag-late{font-size:.82rem;background:var(--late);border-radius:6px;padding:2px 8px;align-self:flex-start}
.record{font-size:.88rem;color:var(--ink2)}
.why h4{margin:6px 0 2px;font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.why ul{margin:0;padding-left:1.1em;display:flex;flex-direction:column;gap:4px;font-size:.92rem}
.why .meta{color:var(--muted);font-size:.8rem}
.ref{font-size:.85em;white-space:nowrap}
.ref-missing{color:var(--muted);font-family:ui-monospace,monospace;font-size:.8em}
strong.bull{color:var(--up)} strong.bear{color:var(--down)}
.tbl{overflow-x:auto} table{border-collapse:collapse;font-size:.85rem;font-variant-numeric:tabular-nums;width:100%}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:.82rem;box-shadow:0 4px 14px rgba(0,0,0,.12);z-index:20;max-width:260px}
#tip b{font-variant-numeric:tabular-nums}
.empty{color:var(--ink2);font-size:.92rem}
footer{color:var(--muted);font-size:.82rem;display:flex;flex-direction:column;gap:4px}
.idx{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.idx a{display:flex;gap:12px;flex-wrap:wrap;align-items:baseline;text-decoration:none;color:var(--ink);font-weight:600}
.idx .r,.idx .c{font-weight:500;color:var(--ink2);font-size:.9rem}
.idx p{color:var(--ink2);font-size:.9rem}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<!-- report-meta: __META__ -->
<style>__CSS__</style></head>
<body>
<div class="wrap" id="app">
  <header style="display:flex;flex-direction:column;gap:6px">
    <div class="eyebrow" id="eyebrow"></div>
    <h1 id="title"></h1>
    <p class="sub" id="subtitle"></p>
  </header>
  <section class="panel" id="summary" aria-label="Summary"></section>
  <nav class="filters" aria-label="Choose companies">
    <label for="f-sector">Sector<select id="f-sector"></select></label>
    <label for="f-company">Company<select id="f-company"></select></label>
    <label for="f-search">Search<input id="f-search" type="search" placeholder="Name or ticker" autocomplete="off"></label>
    <button id="f-reset" type="button">Show all</button>
    <span class="count" id="f-count" aria-live="polite"></span>
  </nav>
  <section class="charts" id="charts" aria-label="Charts"></section>
  <section class="cards" id="cards" aria-label="Companies"></section>
  <section class="panel" id="notes" aria-label="Notes"></section>
  <footer id="footer"></footer>
</div>
<div id="tip" hidden></div>
<script type="application/json" id="report-data">__DATA__</script>
<script>__JS__</script>
</body></html>
"""

INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__NAME__ briefs</title><style>__CSS__</style></head>
<body><div class="wrap">
<header style="display:flex;flex-direction:column;gap:6px"><div class="eyebrow">Market brief · __MARKET__</div>
<h1>__NAME__: daily reports</h1><p class="sub">Newest first. Research log, not investment advice.</p></header>
<section class="panel"><ul class="idx">__ITEMS__</ul></section>
</div></body></html>
"""

# pct0 (in the JS below) is scoring.percent for shares from 0 to 1; a negative half differs (JS -12, Python -13).
JS = r"""
(function(){
'use strict';
const D = JSON.parse(document.getElementById('report-data').textContent);
const $ = (s, el) => (el || document).querySelector(s);
const NS = 'http://www.w3.org/2000/svg', cur = D.symbol || '';
const pct0 = v => (v == null || /e/i.test(String(v)) ? Math.round(v * 100) : Math.round(+(String(v) + 'e2'))) + '%';  // half up
const fmtMoney = v => v == null ? '–' : cur + Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtPct = (v, d) => { if (v == null) return '–'; const s = Math.abs(v * 100).toFixed(d == null ? 1 : d);
  return (+s === 0 ? '' : v > 0 ? '+' : '−') + s + '%'; };
// links: only plain http(s) URLs ever become an href (defence in depth; the data is checked too)
const safeUrl = u => (typeof u === 'string' && /^https?:\/\/\S+$/i.test(u.trim())) ? u.trim() : null;
function linkOrText(url, text){ const u = safeUrl(url); return u ? el('a', {href: u, target: '_blank', rel: 'noopener'}, text) : el('span', null, text); }
// one date style everywhere on the charts: "4 Sep"; tooltips add the weekday: "Fri 4 Sep"
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], WD = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const fmtDay = (iso, wd) => { const d = new Date(iso.slice(0, 10) + 'T00:00:00Z'); return (wd ? WD[d.getUTCDay()] + ' ' : '') + d.getUTCDate() + ' ' + MON[d.getUTCMonth()]; };
function el(tag, attrs, text){
  const e = document.createElement(tag);
  for (const k in (attrs || {})) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
  if (text != null) e.textContent = text;
  return e;
}
function svg(tag, attrs){ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }
function sText(x, y, str, attrs){ const t = svg('text', Object.assign({x: x, y: y, fill: 'var(--muted)', 'font-size': 11}, attrs || {})); t.textContent = str; return t; }
function htmlBlock(cls, inner){ const d = el('div', {class: cls}); d.innerHTML = inner; return d; }  // narrative: escaped server-side

// ---------- tooltip ----------
const tip = $('#tip');
function showTip(ev, rows){
  tip.replaceChildren();
  rows.forEach((r, i) => { const line = el('div'); if (r[1] != null) { line.append(el('b', null, r[1]), document.createTextNode(' ' + r[0])); } else { line.textContent = r[0]; if (i === 0) line.style.fontWeight = 600; } tip.append(line); });
  tip.hidden = false;
  const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8), y = Math.min(ev.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px';
}
function hideTip(){ tip.hidden = true; }
function hover(node, rowsFn){
  node.addEventListener('pointermove', ev => showTip(ev, rowsFn(ev)));
  node.addEventListener('pointerleave', hideTip);
  node.setAttribute('tabindex', '0');
  node.addEventListener('focus', ev => { const r = node.getBoundingClientRect(); showTip({clientX: r.left + r.width / 2, clientY: r.top}, rowsFn(ev)); });
  node.addEventListener('blur', hideTip);
}

// ---------- header and summary ----------
const reg = D.regime;
$('#eyebrow').textContent = 'Market brief · ' + D.name;
$('#title').textContent = 'Session of ' + D.session_label + ' ' + D.session.slice(0, 4);
$('#subtitle').textContent = 'Prices up to the close of ' + D.as_of_label + '. Research log, not investment advice.';
document.title = D.name + ' brief ' + D.session;
const N = D.narrative || {};
const S = $('#summary');
const rg = el('div', {class: 'regime'});
rg.append(el('span', {class: 'pill'}, reg ? 'Market mood: ' + reg.code.replace('_', ' ').toLowerCase() : 'Market mood: unknown'));
if (reg) {
  rg.append(el('span', {class: 'sub'}, reg.plain + (reg.stress ? ' Stress mode is on.' : '') +
    (reg.vol_level != null ? ' ' + reg.vol_name + ' ' + reg.vol_level.toFixed(2) + ' (' + fmtPct(reg.vol_change_1d) + ' on the day).' : '') +
    (reg.bench_ret_5d != null ? ' ' + reg.bench_name + ' ' + fmtPct(reg.bench_ret_5d) + ' over 5 days.' : '')));
}
S.append(rg);
if (N.headline) S.append(htmlBlock('headline prose', N.headline));
if (N.top3 && N.top3.length) {
  S.append(el('h2', null, 'Top 3 things that matter today'));
  const ol = el('ol', {class: 'top3'});
  N.top3.forEach(x => { const li = el('li'); li.innerHTML = x; ol.append(li); });
  S.append(ol);
}
const C = D.counts;
const kp = el('div', {class: 'kpis'});
[[String(C.calls), C.calls === 1 ? 'up/down call today' : 'up/down calls today'],
 [String(C.with_ranges) + ' of ' + C.companies, 'companies with a price range'],
 [String(C.scored_ranges), 'ranges checked against the real price so far']].forEach(k => {
  const d = el('div', {class: 'kpi'}); d.append(el('div', {class: 'v'}, k[0]), el('div', {class: 'l'}, k[1])); kp.append(d); });
S.append(kp);
if (C.late_ranges) S.append(el('p', {class: 'warn'}, C.late_ranges + ' range(s) were made after the session they cover had opened. They are shown for the record, labelled late, and are not forecasts.'));
// data quality, collapsed
const Q = D.quality, dq = el('details');
const nWarn = Q.partial.length + Q.blocked.length + Q.regime_notes.length;
dq.append(el('summary', null, 'Data quality' + (nWarn ? ' (' + nWarn + ' warning' + (nWarn > 1 ? 's' : '') + ')' : '')));
const dqb = el('div', {class: 'prose'});
dqb.append(el('p', null, 'Indicators: ' + (Q.blocked.length ? 'blocked (no calls allowed): ' + Q.blocked.join(', ') + '. ' : 'none blocked. ') + (Q.partial.length ? 'Partial data: ' + Q.partial.join(', ') + '.' : 'No partial data.')));
if (Q.regime_notes.length) dqb.append(el('p', null, 'Market mood notes: ' + Q.regime_notes.join('; ')));
if (N.data_quality) dqb.append(htmlBlock('prose', N.data_quality));
dq.append(dqb); S.append(dq);
// glossary, collapsed
const gl = el('details'); gl.append(el('summary', null, 'How to read this'));
const dl = el('dl', {class: 'gloss'});
[['Price range', 'Where the closing price is likely to be on the target date. The 80% range should contain the real price about 8 times in 10; the narrower 50% range about half the time.'],
 ['Time period', 'Counted in trading days (days the exchange is open). "By Fri 9 Oct" is the close on that date.'],
 ['N+k', 'The horizon of a range or call: bought at the open of the next trading day (D) and sold at the ' +
  'close of the k-th trading day after D. N+1 ends at the close of D+1, two trading days after the last close; ' +
  'N+5 at the close of D+5.'],
 ['Call', 'An up or down view with a confidence between 50% and 90%. Most days most stocks get no call; that is on purpose.'],
 ['Track record', 'How often past ranges and calls were right once the real price was known. Below ' + D.min_sample + ' checked cases we say there is not enough history yet.'],
 ['Late', 'A range made after its session had already opened. It is shown for the record and is never scored or treated as a forecast.'],
 ['Market mood', 'The regime: calm, trending, event-heavy or unstable, from the volatility index and the index trend. Ranges widen when the mood is rougher.'],
 ['Bull / Bear', 'The best case for the price going up, and for it going down, as argued by two research agents from the news.']].forEach(g => { dl.append(el('dt', null, g[0]), el('dd', null, g[1])); });
gl.append(dl); S.append(gl);

// ---------- shared scales ----------
const H = D.primary_horizon;   // view_data.primary_horizon: shortest horizon with a range that is not late
function pctOf(c, v){ return c.close ? v / c.close - 1 : 0; }
// one y-domain (in % from the last close) for every company, so cards can be compared
let domLo = -0.02, domHi = 0.02;
D.companies.forEach(c => { if (!c.close) return;
  const vals = c.history.map(p => pctOf(c, p.c)).concat(c.ranges.flatMap(r => [pctOf(c, r.lo80), pctOf(c, r.hi80)]));
  vals.forEach(v => { domLo = Math.min(domLo, v); domHi = Math.max(domHi, v); }); });
const span = domHi - domLo;
const step = span > 0.4 ? 0.1 : span > 0.2 ? 0.05 : span > 0.08 ? 0.02 : 0.01;
domLo = Math.floor(domLo / step - 1e-9) * step; domHi = Math.ceil(domHi / step - 1e-9) * step;
function ticks(lo, hi, st){ const t = []; for (let v = Math.ceil(lo / st - 1e-9) * st; v <= hi + 1e-9; v += st) t.push(+v.toFixed(6)); return t; }

// ---------- chart: price with the forecast fan (one per company) ----------
function fanChart(c){
  const W = 440, Hh = 210, L = 44, R = 92, T = 10, B = 26;
  const n = c.history.length, maxH = Math.max(0, ...c.ranges.map(r => r.ahead));
  const xs = i => L + (W - L - R) * i / Math.max(1, n - 1 + maxH);
  const ys = v => T + (Hh - T - B) * (domHi - v) / (domHi - domLo);
  const s = svg('svg', {viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': `${c.name}: closing prices for the last ${n} trading days and the price range ahead`});
  ticks(domLo, domHi, step).forEach(v => {
    s.append(svg('line', {x1: L, x2: W - R, y1: ys(v), y2: ys(v), stroke: v === 0 ? 'var(--axis)' : 'var(--grid)', 'stroke-width': 1}));
    s.append(sText(L - 6, ys(v) + 4, fmtPct(v, 0), {'text-anchor': 'end'}));
  });
  const last = n - 1;
  const rs = c.ranges.slice().sort((a, b) => a.h - b.h);
  if (rs.length) {
    const lateAll = rs.every(r => r.late);
    const pts = [[last, 0, 0, 0, 0]].concat(rs.map(r => [last + r.ahead, pctOf(c, r.lo80), pctOf(c, r.hi80), pctOf(c, r.lo50), pctOf(c, r.hi50)]));
    const area = (lo, hi) => 'M' + pts.map(p => xs(p[0]) + ',' + ys(p[hi])).join('L') + 'L' + pts.slice().reverse().map(p => xs(p[0]) + ',' + ys(p[lo])).join('L') + 'Z';
    s.append(svg('path', {d: area(1, 2), fill: lateAll ? 'var(--late)' : 'var(--band80)'}));
    s.append(svg('path', {d: area(3, 4), fill: lateAll ? 'var(--late)' : 'var(--band50)'}));
    const far = rs[rs.length - 1];
    [['hi80', -2], ['lo80', 12]].forEach(k => s.append(sText(xs(last + far.ahead) + 6, ys(pctOf(c, far[k[0]])) + k[1], fmtMoney(far[k[0]]), {fill: 'var(--ink2)'})));
    rs.forEach(r => s.append(sText(xs(last + r.ahead), Hh - 8, fmtDay(r.target_date), {'text-anchor': 'middle'})));
    if (lateAll) s.append(sText(xs(last + far.ahead) + 6, ys(0) + 4, 'late', {fill: 'var(--ink2)', 'font-weight': 600}));
  }
  const path = c.history.map((p, i) => (i ? 'L' : 'M') + xs(i) + ',' + ys(pctOf(c, p.c))).join('');
  s.append(svg('path', {d: path, fill: 'none', stroke: 'var(--accent)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}));
  s.append(svg('circle', {cx: xs(last), cy: ys(0), r: 4, fill: 'var(--accent)', stroke: 'var(--surface)', 'stroke-width': 2}));
  if (n) s.append(sText(xs(0), Hh - 8, fmtDay(c.history[0].d), {'text-anchor': 'start'}));
  // crosshair hover: snaps to the nearest trading day (history) or target date (range)
  const cross = svg('line', {y1: T, y2: Hh - B, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden'});
  s.append(cross);
  const hit = svg('rect', {x: L, y: 0, width: W - L - R + 40, height: Hh, fill: 'transparent'});
  s.append(hit);
  hover(hit, ev => {
    const box = s.getBoundingClientRect(), px = (ev.clientX - box.left) * W / box.width;
    let best = null, bd = 1e9;
    c.history.forEach((p, i) => { const d = Math.abs(xs(i) - px); if (d < bd) { bd = d; best = {i: i, p: p}; } });
    rs.forEach(r => { const d = Math.abs(xs(last + r.ahead) - px); if (d < bd) { bd = d; best = {i: last + r.ahead, r: r}; } });
    if (!best || ev.type === 'focus') { cross.setAttribute('visibility', 'hidden'); return [[c.name], ['last close ' + D.as_of_label, fmtMoney(c.close)]]; }
    cross.setAttribute('x1', xs(best.i)); cross.setAttribute('x2', xs(best.i)); cross.setAttribute('visibility', 'visible');
    if (best.p) return [[fmtDay(best.p.d, true)], ['close', fmtMoney(best.p.c)], ['vs last close', fmtPct(pctOf(c, best.p.c))]];
    const r = best.r;
    return [[r.when + ', by ' + r.target_label + (r.late ? ' (late, not a forecast)' : '')],
            ['to ' + fmtMoney(r.hi80) + ' (80% range)', fmtMoney(r.lo80)], ['to ' + fmtMoney(r.hi50) + ' (50% range)', fmtMoney(r.lo50)]];
  });
  hit.addEventListener('pointerleave', () => cross.setAttribute('visibility', 'hidden'));
  return s;
}

// ---------- chart: every visible company's range at one horizon ----------
function rangesChart(list){
  const box = el('div', {class: 'panel chart wide'});
  const target = (list.find(c => c.ranges.some(r => r.h === H)) || {ranges: []}).ranges.find(r => r.h === H);
  box.append(el('h2', null, 'Where each price may be ' + (target ? target.phrase + ' (by ' + target.target_label + ')' : 'at horizon ' + H)));
  box.append(el('p', {class: 'cap'}, 'Shaded bar: 80% range; darker middle: 50% range; dot: the centre. In % from the last close, on one scale for every company.'));
  const rows = list.filter(c => c.ranges.some(r => r.h === H));
  if (!rows.length) { box.append(el('p', {class: 'empty'}, 'No ranges at this horizon for the companies shown.')); return box; }
  let m = 0.01; rows.forEach(c => { const r = c.ranges.find(x => x.h === H); m = Math.max(m, Math.abs(pctOf(c, r.lo80)), Math.abs(pctOf(c, r.hi80))); });
  const st = m > 0.1 ? 0.05 : m > 0.04 ? 0.02 : 0.01; m = Math.ceil(m / st) * st;
  const W = 900, L = 120, R = 150, rowH = 26, T = 8, Hh = T + rows.length * rowH + 24;
  const xs = v => L + (W - L - R) * (v + m) / (2 * m);
  const s = svg('svg', {viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'Price range per company'});
  ticks(-m, m, st).forEach(v => { s.append(svg('line', {x1: xs(v), x2: xs(v), y1: T, y2: Hh - 22, stroke: v === 0 ? 'var(--axis)' : 'var(--grid)', 'stroke-width': 1}));
    s.append(sText(xs(v), Hh - 6, fmtPct(v, 0), {'text-anchor': 'middle'})); });
  rows.forEach((c, i) => {
    const r = c.ranges.find(x => x.h === H), y = T + i * rowH + rowH / 2;
    const g = svg('g', {});
    g.append(sText(L - 10, y + 4, c.ticker, {'text-anchor': 'end', fill: 'var(--ink)', 'font-size': 12}));
    g.append(svg('rect', {x: xs(pctOf(c, r.lo80)), y: y - 5, width: Math.max(2, xs(pctOf(c, r.hi80)) - xs(pctOf(c, r.lo80))), height: 10, rx: 4, fill: r.late ? 'var(--late)' : 'var(--band80)'}));
    g.append(svg('rect', {x: xs(pctOf(c, r.lo50)), y: y - 5, width: Math.max(2, xs(pctOf(c, r.hi50)) - xs(pctOf(c, r.lo50))), height: 10, rx: 4, fill: r.late ? 'var(--late)' : 'var(--band50)'}));
    g.append(svg('circle', {cx: xs(pctOf(c, r.center_price)), cy: y, r: 4, fill: r.late ? 'var(--muted)' : 'var(--accent)', stroke: 'var(--surface)', 'stroke-width': 2}));
    const call = r.direction && !r.late ? (r.direction === 'up' ? ' ▲ ' : ' ▼ ') + pct0(r.confidence) : '';
    g.append(sText(W - R + 10, y + 4, fmtMoney(r.lo80) + '–' + fmtMoney(r.hi80).replace(cur, '') + (r.late ? '  late' : call), {fill: 'var(--ink2)'}));
    const hitbox = svg('rect', {x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent'});
    g.append(hitbox);
    hover(hitbox, () => [[c.name + ' (' + c.ticker + ')' + (r.late ? ': late, not a forecast' : '')], ['to ' + fmtMoney(r.hi80) + ' (80%)', fmtMoney(r.lo80)], ['to ' + fmtMoney(r.hi50) + ' (50%)', fmtMoney(r.lo50)], ['last close', fmtMoney(c.close)]]);
    s.append(g);
  });
  box.append(s);
  box.append(tableView(['Company', '80% range', '50% range', 'Last close', 'Note'], rows.map(c => { const r = c.ranges.find(x => x.h === H);
    return [c.ticker, fmtMoney(r.lo80) + '–' + fmtMoney(r.hi80), fmtMoney(r.lo50) + '–' + fmtMoney(r.hi50), fmtMoney(c.close), r.late ? 'late, not a forecast' : (r.direction ? r.direction + ' ' + pct0(r.confidence) : 'no call')]; })));
  return box;
}

// ---------- chart: sector moves ----------
function sectorChart(sel){
  const box = el('div', {class: 'panel chart'});
  box.append(el('h2', null, 'How each sector moved on ' + D.as_of_label));
  box.append(el('p', {class: 'cap'}, 'Average one-day price change of the sector’s companies.'));
  const rows = D.sectors.filter(x => x.move_1d != null).slice().sort((a, b) => b.move_1d - a.move_1d);
  if (!rows.length) { box.append(el('p', {class: 'empty'}, 'No price moves yet.')); return box; }
  let m = 0.005; rows.forEach(x => m = Math.max(m, Math.abs(x.move_1d)));
  const st = m > 0.04 ? 0.02 : m > 0.02 ? 0.01 : 0.005; m = Math.ceil(m / st) * st;
  const W = 440, L = 112, R = 64, rowH = 24, T = 6, Hh = T + rows.length * rowH + 22;
  const xs = v => L + (W - L - R) * (v + m) / (2 * m);
  const s = svg('svg', {viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'Sector moves'});
  ticks(-m, m, st).forEach(v => { s.append(svg('line', {x1: xs(v), x2: xs(v), y1: T, y2: Hh - 20, stroke: v === 0 ? 'var(--axis)' : 'var(--grid)', 'stroke-width': 1}));
    s.append(sText(xs(v), Hh - 5, fmtPct(v, st < 0.01 ? 1 : 0), {'text-anchor': 'middle'})); });
  rows.forEach((x, i) => {
    const y = T + i * rowH + rowH / 2, v = x.move_1d, x0 = xs(0), x1 = xs(v);
    const dim = sel && sel !== x.sector;
    const g = svg('g', {opacity: dim ? 0.35 : 1});
    g.append(sText(L - 8, y + 4, x.sector, {'text-anchor': 'end', fill: 'var(--ink)', 'font-size': 12}));
    const w = Math.max(2, Math.abs(x1 - x0));
    g.append(svg('rect', {x: Math.min(x0, x1), y: y - 8, width: w, height: 16, rx: 3, fill: v >= 0 ? 'var(--up)' : 'var(--down)'}));
    g.append(sText(W - 4, y + 4, fmtPct(v), {'text-anchor': 'end', fill: 'var(--ink2)'}));
    const hb = svg('rect', {x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent'}); g.append(hb);
    hover(hb, () => [[x.sector + ': ' + fmtPct(v) + ' on average']].concat(x.moves.map(mv => [mv.ticker, fmtPct(mv.ret_1d)])));
    s.append(g);
  });
  box.append(s);
  box.append(tableView(['Sector', 'Average move', 'Companies'], rows.map(x => [x.sector, fmtPct(x.move_1d), x.moves.map(mv => mv.ticker + ' ' + fmtPct(mv.ret_1d)).join(', ')])));
  return box;
}

// ---------- chart: track record (stated vs actual) ----------
function calibrationChart(){
  const box = el('div', {class: 'panel chart'});
  box.append(el('h2', null, 'Track record: promised vs actual'));
  const pts = D.calibration.filter(p => p.actual != null && p.n > 0);
  if (!pts.length) { box.append(el('p', {class: 'empty'}, 'Nothing has been checked yet. Ranges and calls are scored once their target date has closed.')); return box; }
  const small = pts.every(p => p.n < D.min_sample);
  box.append(el('p', {class: 'cap'}, 'Each mark compares how often something should be right (across) with how often it was (up). On the diagonal = honest. All companies in this market.' + (small ? ' Not enough history yet: fewer than ' + D.min_sample + ' checked cases per mark.' : '')));
  const W = 360, L = 44, R = 12, T = 10, B = 34, Hh = 300;
  const xs = v => L + (W - L - R) * v, ys = v => T + (Hh - T - B) * (1 - v);
  const s = svg('svg', {viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'Promised versus actual hit rate'});
  [0, .25, .5, .75, 1].forEach(v => {
    s.append(svg('line', {x1: L, x2: W - R, y1: ys(v), y2: ys(v), stroke: 'var(--grid)', 'stroke-width': 1}));
    s.append(sText(L - 6, ys(v) + 4, pct0(v), {'text-anchor': 'end'}));
    s.append(sText(xs(v), Hh - 18, pct0(v), {'text-anchor': 'middle'}));
  });
  s.append(sText((L + W - R) / 2, Hh - 3, 'promised', {'text-anchor': 'middle'}));
  s.append(svg('line', {x1: xs(0), y1: ys(0), x2: xs(1), y2: ys(1), stroke: 'var(--axis)', 'stroke-width': 1}));
  pts.forEach(p => {
    const cx = xs(p.stated), cy = ys(p.actual);
    const mark = p.kind === 'range' ? svg('circle', {cx: cx, cy: cy, r: 5, fill: 'var(--accent)', stroke: 'var(--surface)', 'stroke-width': 2})
      : svg('rect', {x: cx - 5, y: cy - 5, width: 10, height: 10, rx: 2, fill: 'var(--call2)', stroke: 'var(--surface)', 'stroke-width': 2});
    s.append(mark);
    const hb = svg('circle', {cx: cx, cy: cy, r: 13, fill: 'transparent'}); s.append(hb);
    hover(hb, () => [[p.label], ['promised', pct0(p.stated)], ['actual', pct0(p.actual)], ['checked cases', String(p.n)]]);
  });
  box.append(s);
  const lg = el('div', {class: 'legend'});
  const a = el('span'); a.append(el('span', {class: 'sw', style: 'background:var(--accent);border-radius:50%;width:10px'}), document.createTextNode('Price ranges'));
  const b = el('span'); b.append(el('span', {class: 'sw', style: 'background:var(--call2);width:10px'}), document.createTextNode('Up/down calls'));
  lg.append(a, b); box.append(lg);
  box.append(tableView(['What', 'Promised', 'Actual', 'Checked'], pts.map(p => [p.label, pct0(p.stated), pct0(p.actual), String(p.n)])));
  box.append(reliabilityChart());
  return box;
}

// ---------- chart: reliability of up/down calls (stated confidence vs hit rate, Wilson 95%) ----------
function reliabilityChart(){
  const box = el('div', {class: 'reliability'});
  const rows = (D.reliability || []).filter(r => r.n > 0);
  const cs = D.call_scores || {n: 0};
  box.append(el('h3', null, 'Up/down calls: confidence vs hit rate'));
  if (!rows.length) { box.append(el('p', {class: 'empty'}, 'No up/down call has been checked yet.')); return box; }
  const f3 = v => v == null ? '–' : v.toFixed(3);
  box.append(el('p', {class: 'cap'}, 'Each dot is a confidence group: how sure the calls said they were (across) and how often they were right (up), with the likely range of the true rate (line). Brier score ' + f3(cs.brier) + ' and log loss ' + f3(cs.log_loss) + ' over ' + cs.n + ' calls; a coin flip scores 0.250 and 0.693, lower is better.' + (cs.basis_note || '') + (cs.n < D.min_sample ? ' Not enough history yet: fewer than ' + D.min_sample + ' checked calls.' : '')));
  const W = 360, L = 44, R = 12, T = 10, B = 34, Hh = 200, lo = 0.3, hi = 1;
  const xs = v => L + (W - L - R) * (v - 0.5) / 0.4, ys = v => T + (Hh - T - B) * (1 - (v - lo) / (hi - lo));
  const s = svg('svg', {viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'Call confidence versus hit rate'});
  [0.4, 0.6, 0.8, 1].forEach(v => {
    s.append(svg('line', {x1: L, x2: W - R, y1: ys(v), y2: ys(v), stroke: 'var(--grid)', 'stroke-width': 1}));
    s.append(sText(L - 6, ys(v) + 4, pct0(v), {'text-anchor': 'end'}));
  });
  [0.5, 0.6, 0.7, 0.8, 0.9].forEach(v => s.append(sText(xs(v), Hh - 18, pct0(v), {'text-anchor': 'middle'})));
  s.append(sText((L + W - R) / 2, Hh - 3, 'stated confidence', {'text-anchor': 'middle'}));
  s.append(svg('line', {x1: xs(0.5), y1: ys(0.5), x2: xs(0.9), y2: ys(0.9), stroke: 'var(--axis)', 'stroke-width': 1, 'stroke-dasharray': '4 3'}));
  const clampY = v => ys(Math.max(lo, Math.min(hi, v)));
  rows.forEach(r => {
    const cx = xs(r.mean_conf);
    s.append(svg('line', {x1: cx, x2: cx, y1: clampY(r.wilson_lo), y2: clampY(r.wilson_hi), stroke: 'var(--call2)', 'stroke-width': 2, 'stroke-linecap': 'round'}));
    s.append(svg('circle', {cx: cx, cy: clampY(r.hit_rate), r: 5, fill: 'var(--call2)', stroke: 'var(--surface)', 'stroke-width': 2}));
    const hb = svg('circle', {cx: cx, cy: clampY(r.hit_rate), r: 13, fill: 'transparent'}); s.append(hb);
    hover(hb, () => [['Confidence ' + r.bin.replace('-', ' to ')], ['stated (mean)', pct0(r.mean_conf)], ['right', pct0(r.hit_rate)], ['95% range', pct0(r.wilson_lo) + ' to ' + pct0(r.wilson_hi)], ['checked calls', String(r.n)]]);
  });
  box.append(s);
  box.append(tableView(['Confidence', 'Stated', 'Right', '95% range', 'Checked'], rows.map(r => [r.bin, pct0(r.mean_conf), pct0(r.hit_rate), pct0(r.wilson_lo) + ' to ' + pct0(r.wilson_hi), String(r.n)])));
  return box;
}

function tableView(head, rows){
  const d = el('details'); d.append(el('summary', null, 'Show as a table'));
  const w = el('div', {class: 'tbl'}), t = el('table'), tr = el('tr');
  head.forEach(h => tr.append(el('th', null, h))); t.append(tr);
  rows.forEach(r => { const row = el('tr'); r.forEach(x => row.append(el('td', null, x))); t.append(row); });
  w.append(t); d.append(w); return d;
}

// ---------- company card ----------
function card(c){
  const a = el('article', {class: 'panel co', id: 'co-' + c.ticker.replace(/[^A-Za-z0-9]/g, '_')});
  const h = el('header');
  const top = el('div', {class: 'row'});
  const name = el('h3', null, c.name); name.append(el('span', {class: 'tk'}, c.ticker));
  const calls = c.calls;
  const pill = calls.length ? el('span', {class: 'pill ' + calls[0].direction}, (calls[0].direction === 'up' ? '▲ Up' : '▼ Down') + ' call, ' + pct0(calls[0].confidence) + ' confidence')
    : el('span', {class: 'pill'}, 'No call');
  top.append(name, pill);
  const p = el('div', {class: 'price'});
  p.append(document.createTextNode(c.sector + ' · last close ' + fmtMoney(c.close) + ' '));
  if (c.ret_1d != null) p.append(el('span', {class: 'chg ' + (c.ret_1d >= 0 ? 'up' : 'down')}, (c.ret_1d >= 0 ? '▲ ' : '▼ ') + fmtPct(c.ret_1d)));
  p.append(document.createTextNode(' on ' + D.as_of_label));
  h.append(top, p); a.append(h);
  if (!c.ranges.length) { a.append(el('p', {class: 'empty'}, 'No price range today (data quality: ' + c.quality + ').')); }
  else {
    a.append(fanChart(c));
    c.ranges.slice().sort((x, y) => x.h - y.h).forEach(r => {
      const d = el('div', {class: 'rng' + (r.late ? ' is-late' : '')});
      d.append(el('div', {class: 'when'}, r.when + ' · by ' + r.target_label));
      if (r.late) {
        d.append(el('span', {class: 'tag-late'}, 'Late: made after this session opened. Not a forecast, never scored.'));
        d.append(el('div', {class: 'second'}, 'Range for the record: ' + fmtMoney(r.lo80) + ' to ' + fmtMoney(r.hi80) + ' (80%), ' + fmtMoney(r.lo50) + ' to ' + fmtMoney(r.hi50) + ' (50%).'));
      } else {
        const m = el('div', {class: 'main'}); m.append(document.createTextNode('80% chance between '), el('b', null, fmtMoney(r.lo80)), document.createTextNode(' and '), el('b', null, fmtMoney(r.hi80)));
        d.append(m, el('div', {class: 'second'}, '50% chance between ' + fmtMoney(r.lo50) + ' and ' + fmtMoney(r.hi50) + '.' +
          (r.direction ? ' Call: ' + r.direction + ', ' + pct0(r.confidence) + ' confidence.' : ' No up/down call.')));
      }
      a.append(d);
    });
  }
  const rec = el('div', {class: 'record'});
  const parts = Object.keys(c.record.ranges).map(k => c.record.ranges[k].name + ' 80% ranges: ' + c.record.ranges[k].text);   // in horizon order
  rec.textContent = 'Track record for ' + c.ticker + '. ' + (parts.length ? parts.join(' ') : 'No ranges checked yet.') + ' Calls: ' + c.record.calls.text;
  a.append(rec);
  // reasons, collapsed unless one company is chosen
  const why = el('details', {class: 'why'}); why.append(el('summary', null, 'Why: news, events and the analysts’ view'));
  const body = el('div', {class: 'prose'});
  calls.forEach(cl => {
    body.append(el('h4', null, cl.when + ' call: ' + cl.direction));
    if (cl.rationale) body.append(el('p', null, cl.rationale));
    if (cl.evidence.length) { const ul = el('ul'); cl.evidence.forEach(e => { const li = el('li'); if (e.title || e.url) { const ln = linkOrText(e.url, e.title || e.id); li.append(ln, el('span', {class: 'meta'}, ' · ' + (e.source || ''))); } else li.textContent = 'Source ' + e.id + ' (not found)'; ul.append(li); }); body.append(ul); }
  });
  if (c.events.length) { body.append(el('h4', null, 'Coming up')); const ul = el('ul');
    c.events.forEach(e => ul.append(el('li', null, e.day + ' · ' + e.label + (e.market ? ' (whole market)' : '')))); body.append(ul); }
  if (c.news.length) { body.append(el('h4', null, 'Latest news')); const ul = el('ul');
    c.news.forEach(n => { const li = el('li'); li.append(linkOrText(n.url, n.title)); li.append(el('span', {class: 'meta'}, ' · ' + (n.source || '') + (n.ts ? ' · ' + n.ts.slice(0, 10) : '') + (n.cited ? ' · cited for the call' : ''))); ul.append(li); });
    body.append(ul); }
  const sec = (N.sectors || {})[c.sector];
  if (sec) { body.append(el('h4', null, c.sector + ': analysts’ view')); body.append(htmlBlock('prose', sec)); }
  const notes = Array.from(new Set(c.ranges.flatMap(r => r.notes)));
  if (notes.length) { body.append(el('h4', null, 'Range adjustments')); body.append(el('p', {class: 'meta'}, notes.join('; '))); }
  if (!body.childNodes.length) body.append(el('p', {class: 'empty'}, 'No news or events found for this company.'));
  why.append(body); a.append(why);
  return a;
}

// ---------- notes (narrative, collapsed) ----------
const notes = $('#notes');
notes.append(el('h2', null, 'Analyst notes'));
[['Yesterday', N.yesterday], ['Calls and abstentions', N.calls], ['This week: risks and events', N.outlook]].forEach(x => {
  if (!x[1] && x[0] !== 'This week: risks and events') return;
  const d = el('details'); d.append(el('summary', null, x[0]));
  if (x[1]) d.append(htmlBlock('prose', x[1]));
  if (x[0].startsWith('This week') && D.upcoming.length) { const ul = el('ul', {class: 'prose'}); D.upcoming.forEach(e => ul.append(el('li', null, e.day + ' · ' + e.label + (e.major ? ' (major)' : '')))); d.append(ul); }
  notes.append(d);
});
const ft = $('#footer');
ft.append(el('p', null, 'Research log, not investment advice. Numbers come from the stored data; the text is written by research agents, checked by automated validation, and sampled weekly by a separate judge agent.'));
const fl = el('p'); fl.append(document.createTextNode('Built ' + D.generated_at.replace('T', ' ').replace('+00:00', ' UTC') + ' · '));
fl.append(el('a', {href: D.links.index}, 'All report days'), document.createTextNode(' · '), el('a', {href: D.links.md}, 'Text version')); ft.append(fl);

// ---------- filters ----------
const fs = $('#f-sector'), fc = $('#f-company'), fq = $('#f-search');
fs.append(el('option', {value: ''}, 'All sectors'));
D.sectors.forEach(x => fs.append(el('option', {value: x.sector}, x.sector)));
function fillCompanies(){
  const keep = fc.value; fc.replaceChildren(el('option', {value: ''}, 'All companies'));
  D.companies.filter(c => !fs.value || c.sector === fs.value).forEach(c => fc.append(el('option', {value: c.ticker}, c.name + ' (' + c.ticker + ')')));
  fc.value = Array.from(fc.options).some(o => o.value === keep) ? keep : '';
}
function visible(){
  const q = fq.value.trim().toLowerCase();
  return D.companies.filter(c => (!fs.value || c.sector === fs.value) && (!fc.value || c.ticker === fc.value) &&
    (!q || c.ticker.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)));
}
const cards = {}; D.companies.forEach(c => cards[c.ticker] = card(c));
function render(){
  const list = visible();
  const ch = $('#charts'); ch.replaceChildren(rangesChart(list), sectorChart(fs.value || (list.length === 1 ? list[0].sector : '')), calibrationChart());
  const cs = $('#cards'); cs.replaceChildren(...list.map(c => cards[c.ticker])); cs.classList.toggle('one', list.length === 1);
  list.forEach(c => { $('details.why', cards[c.ticker]).open = list.length === 1; });
  if (!list.length) cs.append(el('p', {class: 'empty'}, 'No company matches. Clear the search or choose another sector.'));
  $('#f-count').textContent = 'Showing ' + list.length + ' of ' + D.companies.length + ' companies';
}
fs.addEventListener('change', () => { fillCompanies(); render(); });
fc.addEventListener('change', render);
fq.addEventListener('input', render);
$('#f-reset').addEventListener('click', () => { fs.value = ''; fq.value = ''; fillCompanies(); fc.value = ''; render(); });
fillCompanies();
const hash = decodeURIComponent(location.hash.slice(1));
if (hash && D.companies.some(c => c.ticker === hash)) { fs.value = ''; fillCompanies(); fc.value = hash; }
render();
})();
"""


if __name__ == "__main__":
    sys.exit(main())
