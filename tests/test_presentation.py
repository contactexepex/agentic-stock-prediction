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
            "record": {"ranges": {"1": {"n": 2, "hit80": 2, "hit50": 1, "text": "Not enough history yet: 2 of 2 80% ranges were right so far."}},
                       "calls": {"n": 0, "hits": 0, "text": "No up/down calls checked yet."}}}


def rng(h, lo80, hi80, late=False, direction=None, confidence=None, target="2026-10-09", label="Fri 9 Oct"):
    return {"h": h, "target_date": target, "target_label": label, "base_close": 110.0, "center_price": 110.5,
            "lo50": lo80 + 2, "hi50": hi80 - 2, "lo80": lo80, "hi80": hi80, "direction": direction,
            "confidence": confidence, "late": late, "notes": ["earnings in horizon (x3.0 day)"]}


def view():
    aapl = company("AAPL", [rng(1, 104.0, 116.0, target="2026-10-05", label="Mon 5 Oct"),
                            rng(5, 98.25, 121.5, direction="up", confidence=0.65)],
                   calls=[{"h": 5, "direction": "up", "confidence": 0.65, "target_label": "Fri 9 Oct",
                           "rationale": "Strong demand.", "evidence": [{"id": "abcdef0123456789", "title": "Fed cuts rates",
                                                                        "url": "https://example.com/fed", "source": "Reuters"}]}])
    msft = company("MSFT", [rng(5, 300.0, 330.0, late=True)], close=315.0, ret=-0.02)
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
        "calibration": [{"kind": "range", "label": "80% ranges, 1-day", "stated": 0.8, "actual": 1.0, "n": 2}],
        "min_sample": 10,
        "counts": {"calls": 1, "companies": 2, "with_ranges": 2, "late_ranges": 1, "scored_ranges": 2, "scored_calls": 0},
        "quality": {"partial": ["MSFT"], "blocked": [], "regime_notes": []},
        "upcoming": [{"date": "2026-10-08", "day": "Thu 8 Oct", "label": "Apple earnings", "major": False}],
        "sources": {"abcdef0123456789": {"title": "Fed cuts rates", "url": "https://example.com/fed",
                                         "source": "Reuters", "ts": "2026-10-02T12:00:00+00:00"}},
    }


def page():
    v = view()
    n, _ = hr.narrative_html(hr.parse_report(FILLED, ["Tech", "Banks"]), v["sources"])
    return v, hr.build_page(v, n, {"md": "2026-10-05.md", "index": "index.html", "charts": []})


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


def test_html_page_has_sections_filters_and_matching_numbers():
    v, html = page()
    for needle in ('id="summary"', 'id="charts"', 'id="cards"', 'id="notes"', 'id="footer"',
                   'id="f-sector"', 'id="f-company"', 'id="f-search"', 'id="f-reset"',
                   "How to read this", "Data quality", "Top 3 things that matter today",
                   "Late: made after this session opened. Not a forecast, never scored.",
                   "80% chance between ", "not enough history yet", "No call",
                   "prefers-color-scheme: dark", 'name="viewport"'):
        assert needle in html, needle
    assert "<!-- AGENT" not in html and "AGENT:" not in html
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', html)      # nothing loaded from the network
    d = embedded(html)
    assert [s["sector"] for s in d["sectors"]] == ["Tech", "Banks"]                   # sector dropdown source
    for got, want in zip(d["companies"], v["companies"]):
        assert got["ranges"] == want["ranges"] and got["close"] == want["close"]
    assert d["companies"][1]["ranges"][0]["late"] is True
    assert d["narrative"]["top3"][1] == "Apple reports on Thursday."
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
  const p = await b.newPage({viewport: {width: 390, height: 800}});
  p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await p.goto('file://' + process.argv[2]);
  const all = await p.textContent('#cards');
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await p.selectOption('#f-sector', 'Banks'); const banks = await p.locator('#cards article').count();
  await p.selectOption('#f-sector', 'Tech'); await p.selectOption('#f-company', 'MSFT');
  const one = await p.locator('#cards article').count(); const open = await p.$eval('#cards details.why', d => d.open);
  await p.click('#f-reset'); await p.fill('#f-search', 'aap'); const search = await p.locator('#cards article').count();
  console.log(JSON.stringify({errors, all, overflow, banks, one, open, search})); await b.close();
})();
"""


def test_html_renders_in_a_browser_with_working_filters(tmp_path):
    root = _node_playwright()
    if root is None:
        pytest.skip("node + playwright not installed")
    _, html = page()
    f = tmp_path / "r.html"
    f.write_text(html)
    js = tmp_path / "render.js"
    js.write_text(RENDER_JS)
    r = subprocess.run(["node", str(js), str(f)], capture_output=True, text=True, timeout=120,
                       env={**os.environ, "NODE_PATH": root})
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["errors"] == [] and out["overflow"] is False
    text = out["all"]
    assert "80% chance between $98.25 and $121.50" in text            # numbers as given, never re-derived
    assert "Next trading day · by Mon 5 Oct" in text and "5 trading days · by Fri 9 Oct" in text
    assert "Up call, 65% confidence" in text and "No call" in text
    assert "Late: made after this session opened. Not a forecast, never scored." in text
    assert "Range for the record: $300.00 to $330.00 (80%)" in text
    assert "80% chance between $300.00" not in text                      # a late range is never a forecast
    assert "Not enough history yet: 2 of 2" in text and "Fed cuts rates" in text and "Bull:" in text
    assert out["banks"] == 0 and out["one"] == 1 and out["open"] is True and out["search"] == 1


# ---------- Slack ----------

class FakeHTTP:
    def __init__(self, fail: str | None = None):
        self.requests, self.fail, self.n = [], fail, 0

    def __call__(self, url, data, headers):
        self.requests.append((url, data, headers))
        method = url.rsplit("/", 1)[-1]
        if self.fail and self.fail == method:
            return 200, json.dumps({"ok": False, "error": "not_in_channel"}).encode()
        if url.startswith("https://hooks.slack.com/"):
            return 200, b"ok"
        if method == "chat.postMessage":
            return 200, json.dumps({"ok": True, "ts": "1700000000.000100", "channel": "C1"}).encode()
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
    monkeypatch.setattr(ns, "ROOT", root)
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
