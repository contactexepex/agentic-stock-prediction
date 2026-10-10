#!/usr/bin/env python3
"""Build the self-contained HTML report for one market's day, and the report index.

Run after the filled report (reports/<market>/<session_date>.md, no AGENT markers left) has passed the report gate
(validate.py --stage report). Numbers, charts and labels come from the stored data as of the run's clock (view_data.py
and presentation/reader/); the narrative (headline, top 3, sector notes, outlook, data quality) is copied from the
filled report, with every cited news/filing id turned into a link to its source. Writes
reports/<market>/<session_date>.html (the reader's page, presentation/reader/page.py: inline CSS/JS, data embedded as
JSON, no network needed), reports/<market>/index.html (every report day, newest first) and
work/slack_<market>_files.json (the files notify_slack.py attaches). Refuses a report that still has AGENT markers."""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from view_data import NEWS_ID, gather_view, safe_url
from marketbrief.core import cli, database, paths
from marketbrief.core.clock import clock
from marketbrief.presentation.reader import page as reader_page
from marketbrief.presentation.reader.gather import reader_data

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

def build_page(view: dict, narrative: dict, links: dict, reader: dict | None = None) -> str:
    """The reader's page: the view (minus the full source list), the narrative, the links and the reader block
    (presentation/reader/gather.reader_data) embedded as JSON in presentation/reader/page.py's template."""
    data = dict(view)
    data["narrative"], data["links"], data["reader"] = narrative, links, reader or {}
    data.pop("sources", None)
    meta = json.dumps({"session": view["session"], "regime": (view["regime"] or {}).get("code"),
                       "calls": view["counts"]["calls"], "late": view["counts"]["late_ranges"],
                       "headline": re.sub(r"<[^>]+>", "", narrative.get("headline", ""))[:240]},
                      ensure_ascii=False).replace("--", "- -")
    return reader_page.render(f"{view['name']} brief {view['session']}", meta, data)


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
    return INDEX.replace("__NAME__", html.escape(name)).replace("__CSS__", reader_page.css()) \
        .replace("__ITEMS__", items).replace("__MARKET__", html.escape(market))


def run(cfg: dict) -> dict:
    con = database.connect(cfg["market"])
    now = clock()   # MB_NOW-aware: news, ranges, scores and paper status as of the run's clock
    view = gather_view(cfg, con, now)
    folder = paths.ROOT / "reports" / cfg["market"]
    md_path = folder / f"{view['session']}.md"
    if not md_path.exists():
        raise SystemExit(f"{md_path} not found; run report.py and fill it first")
    parsed = parse_report(md_path.read_text(), list(cfg.get("sectors") or {}))
    narrative, _ = narrative_html(parsed, view["sources"])
    charts = folder / "charts" / view["session"]
    links = {"md": md_path.name, "index": "index.html",
             "charts": [f"charts/{view['session']}/{f}" for f in CHART_FILES if (charts / f).exists()]}
    page = build_page(view, narrative, links, reader_data(cfg, con, now, view))
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


# ---------- the report index (the daily page itself: presentation/reader/) ----------

INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>__NAME__ briefs</title><style>__CSS__</style></head>
<body><div class="wrap">
<header class="top"><div class="micro">Market brief · __MARKET__</div>
<h1>__NAME__: daily reports</h1><p class="muted">Newest first. Research log, not investment advice.</p></header>
<section class="card"><ul class="idx">__ITEMS__</ul></section>
</div></body></html>
"""


if __name__ == "__main__":
    sys.exit(main())
