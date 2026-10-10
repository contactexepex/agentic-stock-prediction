"""Presentation layer: the HTML report builder (html_report.py) and the Slack thread poster
(notify_slack.py, with a fake HTTP layer). Processing data is never touched here."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
import html_report as hr  # noqa: E402
import notify_slack as ns  # noqa: E402

FILLED = """# Market brief: Test, 2026-10-05

_Research log, not investment advice._
<!-- report-data: as_of=2026-10-02 regime=CALM -->

Easy-to-read version with charts and filters: [2026-10-05.html](2026-10-05.html)

## Headline
Banks lead after a rate cut (abcdef0123456789).

## Top 3 today
- The Fed cut rates by 25 bp (abcdef0123456789).
- Apple reports on Thursday.
- Oil fell 2%.

## Yesterday
The market rose; banks led (abcdef0123456789).

Market on 2026-10-02: Benchmark 100.00 (+1.0%)

### Ranges scored (target date 2026-10-02)

| Ticker | 80% range |
|---|---|
| AAPL | $1–$2 |

### Calls scored

_none_

## Today (2026-10-05)

**Regime: CALM**

| Ticker | Sector |
|---|---|
| AAPL | Tech |

1 stock(s) have ranges made after the first session they cover had opened (a mid-session or late run): they are shown for the record, are not forecasts and are never scored.

AAPL 5d up: strong demand (abcdef0123456789). MSFT: abstain, earnings tomorrow.

## Tomorrow and this week

| Date | Event | Type |
|---|---|---|
| 2026-10-08 | Apple earnings | company |

- **Apple earnings Oct 8.** Ranges are wider (ffffffffffffffff).

## By sector

![Sector moves](charts/2026-10-05/sectors.png)

### Tech

Both rose on the rate cut. Bull: demand is strong. Bear: valuations are high.

## Track record

| H | n |
|---|---|
| 1d | 2 |

## Data quality

- Indicators: 2 OK, partial: none, blocked: none
- Regime notes: none

_none_
None: all collectors ran.
"""


def company(ticker, ranges, calls=(), close=110.0, ret=0.01):
    return {"ticker": ticker, "name": ticker + " Inc", "sector": "Tech", "close": close, "ret_1d": ret,
            "quality": "OK", "days_to_earnings": 3,
            "history": [{"d": f"2026-09-{d:02d}", "c": close * (1 + (d - 30) / 1000)} for d in range(21, 31)],
            "ranges": ranges, "calls": list(calls),
            "events": [{"date": "2026-10-08", "label": f"{ticker} earnings", "type": "earnings", "day": "Thu 8 Oct"}],
            "news": [{"id": "abcdef0123456789", "title": "Fed cuts rates", "url": "https://example.com/fed",
                      "source": "Reuters", "ts": "2026-10-02T12:00:00+00:00", "cited": True}],
            "record": {"ranges": {"1d": {"h": 1, "name": "N+1", "n": 2, "hit80": 2, "hit50": 1,
                                         "text": "Not enough history yet: 2 of 2 80% ranges were right so far."}},
                       "calls": {"n": 0, "hits": 0, "text": "No up/down calls checked yet."}}}


def rng(h, lo80, hi80, late=False, direction=None, confidence=None, target="2026-10-09", label="Fri 9 Oct",
        horizon_label="n_plus_k"):
    """A range row as view_data builds it: N+k (target k + 1 trading days after the as-of close) or an old window."""
    nk = horizon_label == "n_plus_k"
    days = h + 1 if nk else h
    return {"h": h, "horizon_label": horizon_label, "name": f"N+{h}" if nk else f"{h}-day", "ahead": days,
            "when": f"N+{h} ({days} trading days)" if nk else ("Next trading day" if h == 1 else f"{h} trading days"),
            "phrase": f"in {days} trading days (N+{h})" if nk else (
                "after the next trading day" if h == 1 else f"in {h} trading days"),
            "target_date": target, "target_label": label, "base_close": 110.0, "center_price": 110.5,
            "lo50": lo80 + 2, "hi50": hi80 - 2, "lo80": lo80, "hi80": hi80, "direction": direction,
            "confidence": confidence, "late": late, "notes": ["earnings in horizon (x3.0 day)"]}


def view():
    # AAPL: N+1 and N+5 (as of Fri 2 Oct, D = Mon 5 Oct: exits Tue 6 Oct and Mon 12 Oct); MSFT: a late range of the
    # old 5-day window (D+4 = Fri 9 Oct)
    aapl = company("AAPL", [rng(1, 104.0, 116.0, target="2026-10-06", label="Tue 6 Oct"),
                            rng(5, 98.25, 121.5, direction="up", confidence=0.65, target="2026-10-12",
                                label="Mon 12 Oct")],
                   calls=[{"h": 5, "when": "N+5 (6 trading days)", "direction": "up", "confidence": 0.65,
                           "target_label": "Mon 12 Oct",
                           "rationale": "Strong demand.", "evidence": [{"id": "abcdef0123456789", "title": "Fed cuts rates",
                                                                        "url": "https://example.com/fed", "source": "Reuters"}]}])
    msft = company("MSFT", [rng(5, 300.0, 330.0, late=True, horizon_label="legacy_cc")], close=315.0, ret=-0.02)
    return {
        "market": "us", "name": "Test market", "currency": "USD", "symbol": "$", "session": "2026-10-05",
        "session_label": "Mon 5 Oct", "as_of": "2026-10-02", "as_of_label": "Fri 2 Oct",
        "made_at": "2026-10-04T23:00:00+00:00", "generated_at": "2026-10-05T00:00:00+00:00",
        "regime": {"code": "EVENT_HEAVY", "plain": "Event-heavy: a big scheduled event can move prices more than usual.",
                   "stress": False, "vol_name": "VIX", "vol_level": 18.5, "vol_change_1d": 0.02,
                   "bench_name": "S&P 500", "bench_ret_5d": 0.01, "major_events": [], "notes": []},
        "sectors": [{"sector": "Tech", "tickers": ["AAPL", "MSFT"], "move_1d": -0.005,
                     "moves": [{"ticker": "AAPL", "ret_1d": 0.01}, {"ticker": "MSFT", "ret_1d": -0.02}]},
                    {"sector": "Banks", "tickers": ["JPM"], "move_1d": 0.02, "moves": [{"ticker": "JPM", "ret_1d": 0.02}]}],
        "companies": [aapl, msft],
        "calibration": [{"kind": "range", "label": "80% ranges, N+1", "stated": 0.8, "actual": 1.0, "n": 2}],
        "primary_horizon": 1,   # view_data.primary_horizon: the shortest horizon with a range that is not late
        "min_sample": 10,
        "counts": {"calls": 1, "companies": 2, "with_ranges": 2, "late_ranges": 1, "scored_ranges": 2, "scored_calls": 0},
        "quality": {"partial": ["MSFT"], "blocked": [], "regime_notes": []},
        "upcoming": [{"date": "2026-10-08", "day": "Thu 8 Oct", "label": "Apple earnings", "major": False}],
        "sources": {"abcdef0123456789": {"title": "Fed cuts rates", "url": "https://example.com/fed",
                                         "source": "Reuters", "ts": "2026-10-02T12:00:00+00:00"}},
    }


def fcast(h, lo80, hi80, prob, lean, strength, exit_date, exit_label, change=None):
    """One reader forecast row as presentation/reader/forecasts.forecast builds it."""
    return {"h": h, "name": f"N+{h}", "exit_date": exit_date, "exit_label": exit_label, "entry_date": "2026-10-05",
            "base_close": 110.0, "target": 110.5, "lo50": lo80 + 2, "hi50": hi80 - 2, "lo80": lo80, "hi80": hi80,
            "move_pct": 0.45, "prob_up": prob, "base_rate": 0.5, "lean": lean, "strength": strength,
            "why": f"Why line N+{h}.", "change": change}


def reader():
    """The reader block (presentation/reader/gather.reader_data) for view(): AAPL leans up, MSFT has no score."""
    change = {"since": "2026-10-02T12:00:00Z", "target_pct": 1.25, "prob_pts": 0.031, "news_added": ["abcdef0123456789"]}
    aapl = {"ticker": "AAPL", "bars": [{"d": f"2026-09-{d:02d}", "c": 100.0 + d / 10} for d in range(21, 31)],
            "forecasts": [fcast(1, 104.0, 116.0, 0.58, "up", "clear", "2026-10-06", "Tue 6 Oct", change),
                          fcast(3, 101.0, 119.0, 0.53, "up", "slight", "2026-10-08", "Thu 8 Oct"),
                          fcast(5, 98.25, 121.5, 0.51, "none", "none", "2026-10-12", "Mon 12 Oct")],
            "flags": [{"code": "earnings", "text": "Results in 3 days: prices can jump"}]}
    msft = {"ticker": "MSFT", "bars": [{"d": "2026-09-30", "c": 315.0}], "forecasts": [],
            "flags": [{"code": "contradicted", "text": "Some recent news was contradicted by other sources"}]}
    return {"horizons": [1, 3, 5], "default_horizon": 1, "lean": {"slight": 0.02, "clear": 0.05},
            "cutoff": "2026-10-05T00:00:00+00:00", "as_of": "2026-10-02", "as_of_label": "Fri 2 Oct",
            "paper_label": "Paper only — no proven edge yet",
            "mood": {"code": "EVENT_HEAVY", "word": "Event-heavy", "plain": "Event-heavy: big events.", "stress": False},
            "benchmark": {"symbol": "SPY", "name": "S&P 500", "close": 500.0, "close_date": "2026-10-02",
                          "change_pct": -1.23, "change_5d_pct": 0.5},
            "vol_index": None, "companies": [aapl, msft],
            "glance": {"1": {"up": 1, "down": 0, "none": 0, "no_score": 1, "moves": ["AAPL"]},
                       "3": {"up": 1, "down": 0, "none": 0, "no_score": 1, "moves": ["AAPL"]},
                       "5": {"up": 0, "down": 0, "none": 1, "no_score": 1, "moves": ["AAPL"]}},
            "changes": {"by_horizon": {"1": [{"ticker": "AAPL", "target_pct": 1.25, "prob_pts": 0.031}], "3": [], "5": []},
                        "news": [{"ticker": "AAPL", "id": "abcdef0123456789", "title": "Fed cuts rates",
                                  "url": "https://example.com/fed", "source": "Reuters",
                                  "ts": "2026-10-02T12:00:00+00:00", "status": "corroborated"}],
                        "news_total": 1, "since": "2026-10-02T12:00:00Z"},
            "paper": {"live": False, "live_from": "2026-10-12", "label": "SIMULATED",
                      "note": "Paper trading (simulated, no real money) starts on Mon 12 Oct."}}


def page(v=None, rd=None):
    v = v or view()
    n, _ = hr.narrative_html(hr.parse_report(FILLED, ["Tech", "Banks"]), v["sources"])
    return v, hr.build_page(v, n, {"md": "2026-10-05.md", "index": "index.html", "charts": []}, rd or reader())


def embedded(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_parse_report_keeps_only_agent_narrative():
    p = hr.parse_report(FILLED, ["Tech", "Banks"])
    assert p["headline"] == ["Banks lead after a rate cut (abcdef0123456789)."]
    assert p["top3"] == ["The Fed cut rates by 25 bp (abcdef0123456789).", "Apple reports on Thursday.", "Oil fell 2%."]
    assert p["yesterday"] == ["The market rose; banks led (abcdef0123456789)."]       # "Market on" line is the script's
    assert p["calls"] == ["AAPL 5d up: strong demand (abcdef0123456789). MSFT: abstain, earnings tomorrow."]
    assert p["outlook"] == ["- **Apple earnings Oct 8.** Ranges are wider (ffffffffffffffff)."]
    assert p["sectors"] == {"Tech": ["Both rose on the rate cut. Bull: demand is strong. Bear: valuations are high."]}
    assert p["data_quality"] == ["None: all collectors ran."]
    with pytest.raises(ValueError, match="AGENT markers"):
        hr.parse_report(FILLED.replace("Oil fell 2%.", "<!-- AGENT:top3 -->"), ["Tech"])


def test_parse_report_reads_the_older_filled_india_report():
    """The real filled report (built before the Top 3 marker existed) still parses."""
    md = (Path(__file__).resolve().parents[1] / "reports" / "india" / "2026-10-05.md")
    if not md.exists():
        pytest.skip("India report not in this checkout")
    p = hr.parse_report(md.read_text(), ["Banks", "IT", "Insurance", "Transport", "Energy", "Pharma", "Autos",
                                         "Consumer goods", "Construction", "Metals"])
    assert p["headline"][0].startswith("Late run") and p["top3"] == []
    assert len(p["sectors"]) == 10 and all(v and not v[0].startswith("![") for v in p["sectors"].values())
    assert p["calls"][0].startswith("**Calls: none.**") and p["outlook"][0].startswith("- **RBI decision")
    assert not any(l.startswith("|") for v in p.values() if isinstance(v, list) for l in v)


def test_narrative_links_sources_and_flags_unknown_ids():
    v = view()
    n, used = hr.narrative_html(hr.parse_report(FILLED, ["Tech"]), v["sources"])
    assert 'href="https://example.com/fed"' in n["headline"] and ">Reuters</a>" in n["headline"]
    assert "abcdef0123456789" not in n["headline"]                  # the id becomes a named link
    assert 'ref-missing' in n["outlook"] and "ffffffffffffffff" in n["outlook"]
    assert '<strong class="bull">Bull:</strong>' in n["sectors"]["Tech"] and '<strong class="bear">Bear:</strong>' in n["sectors"]["Tech"]
    assert used == {"abcdef0123456789"}
    # narrative text is escaped, never injected as markup
    n2, _ = hr.narrative_html({"headline": ["<script>alert(1)</script>"], "top3": [], "yesterday": [], "calls": [],
                               "outlook": [], "data_quality": [], "sectors": {}}, {})
    assert "<script>" not in n2["headline"] and "&lt;script&gt;" in n2["headline"]


def test_inline_keeps_titles_intact_and_survives_nul_and_long_words():
    """Issue #26: a source title with "Bull:" gets no markup inside its title attribute; a literal NUL
    placeholder in the narrative raises nothing; long unbroken words wrap on phones."""
    src = {"abcdef0123456789": {"source": "Reuters", "title": "Bull: shares jump", "url": "https://example.com/x"}}
    used: set = set()
    out = hr._inline("Bull: strong demand abcdef0123456789", src, used)
    assert 'title="Bull: shares jump"' in out and out.startswith('<strong class="bull">Bull:</strong>')
    assert out.count("<strong") == 1
    assert hr._inline("odd \x000\x00 text [a](https://example.com/a)", {}, set()).startswith("odd 0 text <a href=")
    from marketbrief.presentation.reader import page as reader_page
    assert "overflow-wrap:anywhere}" in reader_page.css().split("body{", 1)[1].split("\n", 2)[1]   # body rule


BAD_URLS = ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "JaVaScRiPt:alert(1)",
            "  javascript:alert(1)", "\tdata:text/html;base64,PHNjcmlwdD4="]


def test_safe_url_allows_only_http_and_https():
    from view_data import safe_url
    for bad in BAD_URLS + [None, "", "ftp://x.org/a", "//evil.example/x", "https://", "https://a b"]:
        assert safe_url(bad) is None, bad
    assert safe_url("https://example.com/a?b=1&c=2") == "https://example.com/a?b=1&c=2"
    assert safe_url("  HTTP://Example.com/x ") == "HTTP://Example.com/x"


def test_unsafe_source_urls_never_become_links():
    for i, bad in enumerate(BAD_URLS):
        sid = f"{i:016x}"
        sources = {sid: {"title": "Bad <b>feed</b>", "url": bad, "source": "Feed"}}
        out = hr._inline(f"Claim ({sid}). [click]({bad.strip()}) and [x]({bad})", sources, set())
        assert "href" not in out, (bad, out)
        assert '<span class="ref" title="Bad &lt;b&gt;feed&lt;/b&gt;">Feed</span>' in out
        assert "<script>" not in out


def test_markdown_links_are_not_rewritten_or_double_escaped():
    sources = {"0000320193-24-000123": {"title": "Apple 10-K filing", "url": "https://www.sec.gov/x", "source": "SEC EDGAR"}}
    out = hr._inline("See the [10-K](https://www.sec.gov/Archives/0000320193-24-000123.htm) and "
                     "[chart](https://example.com/q?a=1&b=2), cited (0000320193-24-000123).", sources, set())
    assert out.count("<a ") == 3 and "<a <a" not in out and out.count("</a>") == 3
    assert 'href="https://www.sec.gov/Archives/0000320193-24-000123.htm"' in out      # URL untouched
    assert 'href="https://example.com/q?a=1&amp;b=2"' in out and "&amp;amp;" not in out
    assert '>SEC EDGAR</a>' in out                                                     # the bare id still links


def test_html_page_has_sections_filters_and_matching_numbers():
    v, html = page()
    for needle in ('id="glance"', 'id="changes"', 'id="paper"', 'id="legend"', 'id="cards"', 'id="track"',
                   'id="notes"', 'id="footer"', 'id="f-sector"', 'id="f-lean"', 'id="f-sort"', 'id="f-horizon"',
                   "The day in 20 seconds", "What changed since the previous run", "How to read this page",
                   "Chance of going up", "prefers-color-scheme: dark", ':root[data-theme="dark"]', 'name="viewport"',
                   "--md-sys-color-primary", '<symbol id="ms-warning"'):
        assert needle in html, needle
    assert "<!-- AGENT" not in html and "AGENT:" not in html
    assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)="https?://', html)   # nothing loaded from the network
    assert not re.search(r"@import\s+(?:url|\x27|\")", html) and "url(http" not in html
    assert not re.search(r"\b(?:buy|sell) (?:now|signal)\b|\bstrong buy\b|\bstrong sell\b", html, re.I)   # no advice words
    d = embedded(html)
    assert [s["sector"] for s in d["sectors"]] == ["Tech", "Banks"]
    for got, want in zip(d["companies"], v["companies"]):
        assert got["ranges"] == want["ranges"] and got["close"] == want["close"]
    assert d["reader"] == reader() and d["narrative"]["top3"][1] == "Apple reports on Thursday."
    assert "sources" not in d                                                        # only what the page shows
    meta = json.loads(hr.META_RE.search(html).group(1))
    assert meta == {"session": "2026-10-05", "regime": "EVENT_HEAVY", "calls": 1, "late": 1,
                    "headline": "Banks lead after a rate cut (Reuters)."}


def test_index_lists_reports_newest_first(tmp_path):
    _, html = page()
    (tmp_path / "2026-10-05.html").write_text(html)
    (tmp_path / "2026-10-02.html").write_text(html.replace('"session": "2026-10-05"', '"session": "2026-10-02"'))
    (tmp_path / "review-2026-W40.md").write_text("x")
    idx = hr.build_index("us", "Test market", tmp_path)
    assert idx.index('href="2026-10-05.html"') < idx.index('href="2026-10-02.html"')
    assert "1 call<" in idx and "EVENT_HEAVY" in idx and "review" not in idx


def _node_playwright() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return root if root and (Path(root) / "playwright").exists() else None


RENDER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const errors = [];
  const p = await b.newPage({viewport: {width: 360, height: 800}});
  p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('request', r => { if (!r.url().startsWith('file:')) errors.push('request ' + r.url()); });
  await p.goto('file://' + process.argv[2]);
  const glance = await p.textContent('#glance'), changes = await p.textContent('#changes'), paper = await p.textContent('#paper');
  const legend = await p.textContent('#legend'), all = await p.textContent('#cards'), track = await p.textContent('#track');
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  const order = await p.$$eval('#cards article h3', hs => hs.map(h => h.textContent));
  const sectors = await p.$$eval('#f-sector option', os => os.map(o => o.value));
  await p.selectOption('#f-sector', 'Tech'); const tech = await p.locator('#cards article').count();
  await p.selectOption('#f-sector', ''); await p.selectOption('#f-lean', 'up'); const up = await p.locator('#cards article').count();
  await p.selectOption('#f-lean', 'flag'); const flagged = await p.locator('#cards article').count();
  await p.selectOption('#f-lean', ''); await p.click('#f-horizon button:nth-child(2)');
  const n3 = await p.textContent('#cards'); const g3 = await p.textContent('#glance');
  const hrefs = await p.$$eval('a', as => as.map(a => a.getAttribute('href')));
  const dates = await p.$$eval('#cards svg.fan text', ts => ts.map(t => t.textContent).filter(x => /[A-Z][a-z]{2}$/.test(x)));
  const light = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await p.emulateMedia({colorScheme: 'dark'}); const dark = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
  console.log(JSON.stringify({errors, glance, changes, paper, legend, all, track, overflow, order, sectors, tech, up, flagged, n3, g3, hrefs, dates, light, dark}));
  await b.close();
})();
"""


def test_html_renders_in_a_browser_with_working_filters(tmp_path):
    root = _node_playwright()
    if root is None:
        pytest.skip("node + playwright not installed")
    # unsafe links put straight into the page data: the JS must refuse them on its own (defence in depth)
    v, rd = view(), reader()
    v["companies"][1]["news"] = [{"id": f"bad{i}", "title": f"Bad link {i}", "url": u, "source": "Feed",
                                  "ts": None, "cited": False} for i, u in enumerate(BAD_URLS)]
    rd["changes"]["news"].append({"ticker": "MSFT", "id": "evil", "title": "Evil news", "url": "JaVaScRiPt:alert(1)",
                                  "source": "Feed", "ts": None, "status": "contradicted"})
    v["sources"]["ffffffffffffffff"] = {"title": "Bad source", "url": " javascript:alert(1)", "source": "BadFeed"}
    _, html = page(v, rd)
    f = tmp_path / "r.html"
    f.write_text(html)
    js = tmp_path / "render.js"
    js.write_text(RENDER_JS)
    r = subprocess.run(["node", str(js), str(f)], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "NODE_PATH": root})
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["errors"] == [] and out["overflow"] is False
    g = out["glance"]   # the 20-second top: mood, benchmark, leans, biggest moves, the paper line
    assert "Event-heavy" in g and "S&P 500" in g and "▼ −1.23%" in g and "1 lean up" in g and "0 lean down" in g
    assert "measured at the close of Tue 6 Oct" in g and "AAPL Inc" in g and "+0.5% to $110.50" in g
    assert "Paper only — no proven edge yet" in g and "Only 2 forecast ranges checked so far: too few to judge." in g
    assert "chance of going up +3.1 pts" in out["changes"] and "Fed cuts rates" in out["changes"]
    assert "Confirmed by 2+ outlets" in out["changes"] and "Evil news" in out["changes"] and "Contradicted" in out["changes"]
    assert "starts on Mon 12 Oct" in out["paper"] and "SIMULATED" in out["paper"]
    assert "80% range about 8 times in 10" in out["legend"] and "coin flip" in out["legend"]
    text = out["all"]
    assert out["order"] == ["AAPL Inc", "MSFT Inc"]                       # strongest lean first
    assert "Last close $110.00" in text and "Lean up" in text and "Chance of going up by Tue 6 Oct58%" in text
    assert "104.00–​116.00" in text and "98.25–​121.50" in text  # numbers as given, never re-derived
    assert "Why line N+1." in text and "Results in 3 days: prices can jump" in text
    assert "Since the previous run (Fri 2 Oct, 12:00 UTC)" in text and "1 new news item counted" in text
    assert "No price range today" in text and "Some recent news was contradicted" in text
    assert "Bad link 3" in text                                          # unsafe links stay visible as plain text
    assert out["sectors"] == ["", "Tech"] and out["tech"] == 2 and out["up"] == 1   # sectors of the shown companies
    assert out["flagged"] == 2                                           # both cards carry a warning
    assert "Why line N+3." in out["n3"] and "53%" in out["n3"] and "N+3" in out["g3"]   # the horizon switch
    assert "Nothing has been checked yet" not in out["track"] and "80% ranges, N+1" in out["track"]
    assert out["hrefs"] and all(re.match(r"^(https?://|index\.html$|2026-10-05\.md$)", h) for h in out["hrefs"]), out["hrefs"]
    assert out["dates"] and all(re.match(r"^\d{1,2} [A-Z][a-z]{2}$", d) for d in out["dates"]), out["dates"]
    assert out["light"] != out["dark"]                                   # dark mode follows the system


# ---------- Slack ----------

class FakeHTTP:
    def __init__(self, fail: str | None = None):
        self.requests, self.fail, self.n, self.posts = [], fail, 0, 0

    def __call__(self, url, data, headers):
        self.requests.append((url, data, headers))
        method = url.rsplit("/", 1)[-1]
        if self.fail and self.fail == method:
            return 200, json.dumps({"ok": False, "error": "not_in_channel"}).encode()
        if url.startswith("https://hooks.slack.com/"):
            return 200, b"ok"
        if method == "chat.postMessage":   # a distinct ts per message; the first is 1700000000.000100
            self.posts += 1
            return 200, json.dumps({"ok": True, "ts": f"1700000000.{99 + self.posts:06d}", "channel": "C1"}).encode()
        if method == "files.getUploadURLExternal":
            self.n += 1
            return 200, json.dumps({"ok": True, "upload_url": f"https://files.slack.com/upload/v1/F{self.n}",
                                    "file_id": f"F{self.n}"}).encode()
        if method == "files.completeUploadExternal":
            return 200, json.dumps({"ok": True, "files": []}).encode()
        if url.startswith("https://files.slack.com/upload/"):
            return 200, b"OK - %d" % len(data)
        return 404, b"{}"


@pytest.fixture
def slack_root(tmp_path, monkeypatch):
    root = tmp_path
    (root / "work").mkdir()
    charts = root / "reports" / "us" / "charts" / "2026-10-05"
    charts.mkdir(parents=True)
    for name in ("ranges.png", "sectors.png"):
        (charts / name).write_bytes(b"\x89PNG fake " + name.encode())
    (root / "reports" / "us" / "2026-10-05.html").write_text("<html>report</html>")
    (root / "work" / "slack_us.md").write_text("*Market brief · US · 2026-10-05*\nTop 3 today:\n• a\n• b\n• c\n"
                                               "Calls today: none.\n<!-- AGENT:failures (only if...) -->\nFull report: x\n")
    (root / "work" / "slack_us_files.json").write_text(json.dumps({
        "market": "us", "session": "2026-10-05", "html": "reports/us/2026-10-05.html",
        "images": ["reports/us/charts/2026-10-05/ranges.png", "reports/us/charts/2026-10-05/sectors.png"]}))
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    return root


def form(data: bytes) -> dict:
    from urllib.parse import parse_qs
    return {k: v[0] for k, v in parse_qs(data.decode()).items()}


def test_thread_posts_summary_then_charts_then_html(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    http = FakeHTTP()
    assert ns.main(["--market", "us"], http=http) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "thread" and out["posted"] == ["summary", "charts", "report"]
    seq = [u.replace("https://slack.com/api/", "").split("/upload/")[0] for u, _, _ in http.requests]
    assert seq == ["chat.postMessage",
                   "files.getUploadURLExternal", "https://files.slack.com", "files.getUploadURLExternal", "https://files.slack.com",
                   "files.completeUploadExternal",
                   "files.getUploadURLExternal", "https://files.slack.com", "files.completeUploadExternal"]
    first = form(http.requests[0][1])
    assert first["channel"] == "C0C6REB7QS2" and "thread_ts" not in first
    assert "AGENT" not in first["text"] and first["text"].startswith("*Market brief")
    assert http.requests[0][2]["Authorization"] == "Bearer xoxb-test"
    get1 = form(http.requests[1][1])
    assert get1["filename"] == "ranges.png" and int(get1["length"]) == len(b"\x89PNG fake ranges.png")
    assert http.requests[2][1] == b"\x89PNG fake ranges.png"                          # raw bytes to the upload URL
    charts, report = form(http.requests[5][1]), form(http.requests[8][1])
    for c in (charts, report):                                                        # replies in the thread
        assert c["channel_id"] == "C0C6REB7QS2" and c["thread_ts"] == "1700000000.000100"
    assert [f["id"] for f in json.loads(charts["files"])] == ["F1", "F2"]
    assert json.loads(report["files"]) == [{"id": "F3", "title": "Report 2026-10-05"}]
    assert get1 and form(http.requests[6][1])["filename"] == "2026-10-05.html"


def test_thread_error_is_reported(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    assert ns.main(["--market", "us"], http=FakeHTTP(fail="files.completeUploadExternal")) == 1
    out = json.loads(capsys.readouterr().out)
    assert "not_in_channel" in out["error"] and out["calls"][0] == "chat.postMessage"


def test_without_token_falls_back_to_webhook_text(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    http = FakeHTTP()
    assert ns.main(["--market", "us"], http=http) == 0
    assert len(http.requests) == 1 and http.requests[0][0].startswith("https://hooks.slack.com/")
    body = json.loads(http.requests[0][1])
    assert body["text"].startswith("*Market brief") and "AGENT" not in body["text"]
    assert json.loads(capsys.readouterr().out)["mode"] == "webhook"
    monkeypatch.delenv("SLACK_WEBHOOK_URL")
    assert ns.main(["--market", "us"], http=http) == 2 and len(http.requests) == 1   # nothing configured


def test_refuses_unfilled_draft(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    (slack_root / "work" / "slack_us.md").write_text("head\n<!-- AGENT:top3 (three lines) -->\n")
    http = FakeHTTP()
    assert ns.main(["--market", "us"], http=http) == 1 and http.requests == []
    assert "AGENT markers" in capsys.readouterr().out


def test_dry_run_writes_plan_and_files(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    http = FakeHTTP()
    assert ns.main(["--market", "us", "--dry-run"], http=http) == 0 and http.requests == []
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "thread" and out["plan"] == "work/slack_us_plan.json"
    plan = json.loads((slack_root / out["plan"]).read_text())
    assert plan["channel_id"] == "C0C6REB7QS2"
    assert [s["step"] for s in plan["thread"]] == ["summary", "charts", "report"]
    assert [f["title"] for f in plan["thread"][1]["files"]] == ["Price ranges", "Sector moves"]
    assert sorted(p.name for p in (slack_root / "work" / "slack_us_plan").iterdir()) == \
        ["2026-10-05.html", "ranges.png", "sectors.png"]


def test_holiday_text_with_token_is_one_message(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    http = FakeHTTP()
    assert ns.main(["--market", "us", "--text", "US: market closed today"], http=http) == 0
    assert [u for u, _, _ in http.requests] == ["https://slack.com/api/chat.postMessage"]
    assert form(http.requests[0][1])["text"] == "US: market closed today\n"


def test_missing_file_manifest_posts_summary_only(slack_root, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    (slack_root / "work" / "slack_us_files.json").unlink()
    http = FakeHTTP()
    assert ns.main(["--market", "us"], http=http) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["posted"] == ["summary"] and "html_report.py" in out["files_warning"]


def test_primary_horizon_is_the_shortest_on_time_horizon():
    """view_data.primary_horizon (decision 37): the shortest horizon with a range that is not late; when every range
    is late, the longest one published; with no range, the longest configured horizon."""
    import view_data
    from marketbrief.core.horizons import horizons
    v = view()
    assert view_data.primary_horizon(v) == 1
    v["companies"][0]["ranges"][0]["late"] = True                        # N+1 late: N+5 of AAPL is on time
    assert view_data.primary_horizon(v) == 5
    for c in v["companies"]:
        for r in c["ranges"]:
            r["late"] = True
    assert view_data.primary_horizon(v) == 5
    for c in v["companies"]:
        c["ranges"] = []
    assert view_data.primary_horizon(v) == horizons()[-1]


def test_report_parts_keep_old_windows_apart_and_cover_every_horizon():
    """The report's 'Yesterday' line headlines the shortest horizon's N+k ranges; the old window and the other
    horizons scored on the same date each get their own sentence (never pooled); today's table shows the shortest
    and the longest configured horizon and lists the calls of every horizon (B10)."""
    from types import SimpleNamespace

    import pandas as pd
    from marketbrief.core.market_config import load_market
    from marketbrief.presentation.report import report_parts

    cfg = load_market("us")
    scored = pd.DataFrame([
        {"ticker": t, "horizon_days": h, "horizon_label": label, "lo80": 1.0, "hi80": 2.0, "lo50": 1.2, "hi50": 1.8,
         "actual_close": 1.5, "hit80": hit, "hit50": hit, "naive_hit80": hit}
        for t, h, label, hit in (("JPM", 1, "n_plus_k", True), ("BAC", 1, "n_plus_k", False),
                                 ("JPM", 1, "legacy_cc", True), ("JPM", 3, "n_plus_k", True))])
    day = {"as_of": "2026-10-09", "market": pd.DataFrame(columns=["ticker", "close", "ret_1d"]), "scored": scored,
           "calls_scored": pd.DataFrame(columns=["ticker", "horizon_days", "label_basis", "direction", "confidence",
                                                 "actual_return", "hit"])}
    out = report_parts.yesterday_tables(cfg, "USD", day, pd.DataFrame())
    _, h50, h80, line5, _, _, one_day_count, one_day_name, _, scored_rows = out
    assert (one_day_name, one_day_count, h80, h50, len(scored_rows)) == ("N+1", 2, 1, 1, 2)
    assert line5 == ("1-day ranges that matured on the same date: 80% hit 1/1, 50% hit 1/1. "
                     "N+3 ranges that matured on the same date: 80% hit 1/1, 50% hit 1/1.")

    def published(h, direction=None):
        return SimpleNamespace(ticker="JPM", horizon_days=h, horizon_label="n_plus_k", base_close=100.0,
                               lo80=90.0 + h, hi80=110.0 + h, lo50=95.0, hi50=105.0, direction=direction,
                               confidence=0.6 if direction else None, notes=[f"note {h}"], as_of_date=None,
                               made_at=None)
    ranges = {("JPM", h): published(h, "up" if h == 3 else None) for h in (1, 2, 3, 4, 5)}
    _, rows = report_parts.today_rows_by_sector(cfg, "USD", pd.DataFrame(), ranges)
    jpm = next(r for r in rows if r[0] == "JPM")
    assert jpm[3] == "$91.00–$111.00" and jpm[5] == "$95.00–$115.00"          # N+1 80% and N+5 80%
    assert jpm[6] == "3d ▲ up 60%" and jpm[8] == "note 1; note 2; note 3; note 4; note 5"


@pytest.mark.usefixtures("slack_root")
def test_brief_joins_the_days_thread_started_by_the_morning_picks(monkeypatch, capsys):
    """One thread per market per day (owner, 2026-10-07): the brief replies to the thread alerts.py morning started,
    and its files go into the same thread; a rerun posts the brief text once."""
    from marketbrief.alerts.publish import Message, publisher
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    http = FakeHTTP()
    picks = publisher("us", dry_run=False, http=http).publish(
        Message("morning", "morning:us:2026-10-05", "picks", "us:2026-10-05"))
    assert ns.main(["--market", "us"], http=http) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["thread_ts"] == picks["thread_ts"]
    posts = [form(d) for u, d, _ in http.requests if u.endswith("chat.postMessage")]
    assert len(posts) == 2 and posts[1]["thread_ts"] == picks["thread_ts"] and posts[1]["text"].startswith("*Market")
    shares = [form(d) for u, d, _ in http.requests if u.endswith("files.completeUploadExternal")]
    assert shares and all(s["thread_ts"] == picks["thread_ts"] for s in shares)
    assert picks["thread_ts"] == "1700000000.000100" and out["posted"][0] == "summary"
    assert ns.main(["--market", "us"], http=http) == 0                                  # rerun: no second brief
    assert len([u for u, _, _ in http.requests if u.endswith("chat.postMessage")]) == 2
    again = json.loads(capsys.readouterr().out)
    assert again["skipped"] == ["summary"] and "summary" not in again["posted"]
