"""Offline end-to-end tests: local RSS fixture, synthetic prices, prediction scoring, features,
regime and the context pack, all on a small throwaway market config.
Run: pytest -q"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
MARKET = "testmkt"

MARKET_YAML = """
market: testmkt
name: Test market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  BENCH: {role: benchmark, name: Benchmark}
  VOLX: {role: vol_index, name: Vol index}
regime: {unstable_vol: 28, event_vol: 20, calm_vol: 16, unstable_bench_vol: 0.25,
         trend_return_5d: 0.015, flat_return_5d: 0.005, stress_vol_jump: 0.30}
sectors:
  Tech: [AAPL, MSFT]
tickers:
  AAPL: {name: Apple, aliases: [iPhone]}
  MSFT: {name: Microsoft}
news:
  outlets:
    - {name: Fixture, url: '%s', category: general}
"""


def run(script: str, root: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET}
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, check=False)


def rss(items: list[tuple[str, str]]) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    body = "".join(f"<item><title>{t}</title><link>https://example.com/{i}</link>"
                   f"<description>{d}</description><pubDate>{now}</pubDate></item>"
                   for i, (t, d) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{body}</channel></rss>'


def setup(tmp: Path) -> tuple[Path, Path]:
    root, cfg = tmp / "repo", tmp / "config"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    feed = tmp / "feed.xml"
    feed.write_text(rss([("Apple raises guidance", "iPhone demand strong"),
                         ("Fed holds rates", "no ticker here"),
                         ("Apple raises guidance", "duplicate in same feed")]))
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML % feed)
    (cfg / "events.yaml").write_text((REPO / "config" / "events.yaml").read_text().replace("[us]", "[us, testmkt]"))
    (cfg / "ranges.yaml").write_text((REPO / "config" / "ranges.yaml").read_text())
    # the live slack_link_url is left out, so report links stay the repo links asserted below
    live_settings = (REPO / "config" / "settings.yaml").read_text()
    (cfg / "settings.yaml").write_text(re.sub(r"(?m)^slack_link_url:.*\n", "", live_settings))
    return root, cfg


def horizons() -> tuple[int, ...]:
    """The configured horizons N+k (config/strategies.yaml; B10)."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from marketbrief.core.horizons import horizons as configured
    return configured()


def weekdays(start: date, n: int) -> list[date]:
    """n market sessions from `start`: weekdays that are no NYSE holiday (the test market's calendar), because the
    price views leave out bars on days the exchange is closed (issue #40)."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from marketbrief.core.calendar import is_session

    days, d = [], start
    while len(days) < n:
        if is_session({"calendar": "XNYS"}, d):
            days.append(d)
        d += timedelta(days=1)
    return days


def write_bars(root: Path, series: dict[str, list[float]], days: list[date]) -> None:
    for i, day in enumerate(days):
        p = root / "data" / MARKET / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = ["date,ticker,open,high,low,close,adj_close,volume,collected_at"]
        for t, closes in series.items():
            c = closes[i]
            lines.append(f"{day},{t},{c},{c * 1.01},{c * 0.99},{c},{c},{1000 + i},2026-01-01T00:00:00+00:00")
        p.write_text("\n".join(lines) + "\n")


def test_news_collect_tags_and_dedupes(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_news.py", root, cfg)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["new_items"] == 2
    rows = [json.loads(line) for f in (root / "data" / MARKET / "news").glob("**/*.jsonl")
            for line in f.read_text().splitlines()]
    tagged = {r["title"]: r["tickers"] for r in rows}
    assert tagged["Apple raises guidance"] == ["AAPL"]
    assert tagged["Fed holds rates"] == []
    # second run sees the same items and writes nothing new
    assert json.loads(run("collect_news.py", root, cfg).stdout)["new_items"] == 0


def test_news_flags_stale_outlet(tmp_path):
    root, cfg = setup(tmp_path)
    old = tmp_path / "old.xml"   # a feed that answers but stopped updating (like Moneycontrol in 2024)
    old.write_text('<?xml version="1.0"?><rss version="2.0"><channel><title>Old</title><item><title>Old news'
                   '</title><link>https://example.com/o</link><pubDate>Tue, 23 Apr 2024 10:16:31 GMT</pubDate>'
                   '</item></channel></rss>')
    path = cfg / "markets" / f"{MARKET}.yaml"
    path.write_text(path.read_text() + f"    - {{name: Frozen, url: '{old}', category: general}}\n")
    out = json.loads(run("collect_news.py", root, cfg).stdout)
    assert out["new_items"] == 2 and not out["failed"]
    assert [s["feed"] for s in out["stale"]] == ["Frozen"] and out["stale"][0]["newest"].startswith("2024-04-23")


def test_scoring_and_context(tmp_path):
    root, cfg = setup(tmp_path)
    days = weekdays(date(2026, 9, 1), 7)
    closes = [100, 101, 102, 103, 104, 105, 99]
    write_bars(root, {"AAPL": closes, "BENCH": closes, "VOLX": [15] * 7}, days)
    pred_dir = root / "data" / MARKET / "predictions" / "2026" / "09"
    pred_dir.mkdir(parents=True)
    preds = [
        {"id": f"{days[0]}-AAPL-5d", "made_at": "2026-09-01T22:00:00+00:00", "as_of_date": str(days[0]),
         "ticker": "AAPL", "horizon_days": 5, "direction": "up", "confidence": 0.6,
         "rationale": "t", "evidence_ids": ["x"], "prompt_version": "test"},
        {"id": f"{days[1]}-AAPL-5d", "made_at": "2026-09-02T22:00:00+00:00", "as_of_date": str(days[1]),
         "ticker": "AAPL", "horizon_days": 5, "direction": "up", "confidence": 0.7,
         "rationale": "t", "evidence_ids": ["x"], "prompt_version": "test"},
        {"id": f"{days[5]}-AAPL-5d", "made_at": "2026-09-08T22:00:00+00:00", "as_of_date": str(days[5]),
         "ticker": "AAPL", "horizon_days": 5, "direction": "down", "confidence": 0.6,
         "rationale": "t", "evidence_ids": ["x"], "prompt_version": "test"},
    ]
    (pred_dir / f"{days[0]}.jsonl").write_text("".join(json.dumps(p) + "\n" for p in preds))

    r = run("score_predictions.py", root, cfg)
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout)
    assert (summary["scored"], summary["still_open"]) == (2, 1)
    outcomes = {o["prediction_id"]: o for f in (root / "data" / MARKET / "outcomes").glob("**/*.jsonl")
                for o in map(json.loads, f.read_text().splitlines())}
    assert outcomes[preds[0]["id"]]["hit"] is True        # 100 -> 105
    assert outcomes[preds[1]["id"]]["hit"] is False       # 101 -> 99
    assert outcomes[preds[0]["id"]]["target_date"] == str(days[5])
    # scoring again is idempotent
    assert json.loads(run("score_predictions.py", root, cfg).stdout)["scored"] == 0

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "| close_to_close | legacy_cc | 5 | 2 | 0.5 |" in ctx.stdout   # 1 hit of 2 scored, close basis (legacy)


def test_features_regime_and_context(tmp_path):
    root, cfg = setup(tmp_path)
    rng = np.random.default_rng(7)
    days = weekdays(date.today() - timedelta(days=420), 290)
    bench = list(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(days)))))
    aapl = list(150 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, len(days)))))
    write_bars(root, {"BENCH": bench, "AAPL": aapl, "MSFT": aapl[:-1] + [aapl[-2]],
                      "VOLX": [14.0] * len(days)}, days)
    events = root / "data" / MARKET / "events" / "2026" / "01" / "2026-01-01.jsonl"
    events.parent.mkdir(parents=True)
    soon = date.today() + timedelta(days=3)
    events.write_text(json.dumps({"id": f"AAPL-earnings-{soon}", "date": str(soon), "type": "earnings",
                                  "ticker": "AAPL", "name": "Apple earnings", "source": "test",
                                  "first_seen_at": "2026-01-01T00:00:00+00:00"}) + "\n")

    r = run("features.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["as_of_date"] == str(days[-1])
    assert out["regime"] in {"CALM", "TRENDING", "EVENT_HEAVY", "UNSTABLE"}
    assert out["tickers"]["BLOCKED"] == 0

    feats = {f["ticker"]: f for p in (root / "data" / MARKET / "features").glob("**/*.jsonl")
             for f in map(json.loads, p.read_text().splitlines())}
    a = feats["AAPL"]
    assert a["bars"] == len(days) and a["quality"] == "OK"
    assert 0 <= a["rsi_14"] <= 100 and a["atr_pct"] > 0 and a["beta_1y"] is not None
    # features count from the session after as_of (issue #21), so no clock reading can flake here (issue #43)
    from marketbrief.core.calendar import next_session
    session = next_session({"calendar": "XNYS"}, days[-1], include=False)
    assert out["session_date"] == str(session)
    assert a["days_to_earnings"] == (soon - session).days
    assert feats["MSFT"]["ret_1d"] == 0.0
    assert abs(feats["MSFT"]["rel_sector_5d"] + a["rel_sector_5d"]) < 1e-9   # mirror images

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    for heading in ("Market regime", "Upcoming events", "Indicators", "Apple earnings"):
        assert heading in ctx.stdout
    assert "SEC filings" not in ctx.stdout


def test_context_shows_sector_etf_mapping(tmp_path):
    root, cfg = setup(tmp_path)
    path = cfg / "markets" / f"{MARKET}.yaml"
    path.write_text(path.read_text().replace(
        "  VOLX: {role: vol_index, name: Vol index}\n",
        "  VOLX: {role: vol_index, name: Vol index}\n"
        "  SECT: {role: sector_etf, name: Tech fund, sectors: [Tech]}\n"))
    rng = np.random.default_rng(3)
    days = weekdays(date.today() - timedelta(days=60), 30)
    walk = lambda s: list(s * np.exp(np.cumsum(rng.normal(0, 0.01, len(days)))))  # noqa: E731
    write_bars(root, {"BENCH": walk(100), "AAPL": walk(150), "MSFT": walk(300), "SECT": walk(50),
                      "VOLX": [14.0] * len(days)}, days)
    assert run("features.py", root, cfg).returncode == 0
    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    etf = ctx.stdout.split("## Sector ETFs and indices")[1].split("##")[0]
    assert "| ticker | name | watchlist_sectors | date |" in etf and "| SECT | Tech fund | Tech | " in etf
    assert "without a sector ETF" not in ctx.stdout           # the only sector is mapped
    ind = ctx.stdout.split("## Indicators")[1].split("##")[0]
    assert "| ticker | sector | sector_etf | quality |" in ind
    assert "| AAPL | Tech | SECT | " in ind and "| MSFT | Tech | SECT | " in ind


def test_context_on_empty_repo(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("context.py", root, cfg)
    assert r.returncode == 0, r.stderr
    assert "_none_" in r.stdout


def test_market_status(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("market_status.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["market"] == MARKET and isinstance(out["trading_day"], bool)


def fat_tailed_walk(rng, n: int, start: float, daily_vol: float) -> list[float]:
    r = rng.standard_t(4, n) * daily_vol / np.sqrt(2)          # t(4) has variance 2
    return list(start * np.exp(np.cumsum(r)))


def publish_ranges(root: Path, cfg: Path) -> tuple[dict, str, dict]:
    """Calibrate on 520 synthetic sessions and publish one day's ranges with an AAPL 5-day call:
    (series, made_at, ranges by id)."""
    rng = np.random.default_rng(11)
    days = weekdays(date(2024, 6, 3), 520)
    series = {"BENCH": fat_tailed_walk(rng, 520, 100, 0.01), "AAPL": fat_tailed_walk(rng, 520, 150, 0.015),
              "MSFT": fat_tailed_walk(rng, 520, 300, 0.012), "VOLX": [15.0] * 520}
    write_bars(root, series, days)
    assert run("features.py", root, cfg).returncode == 0

    r = run("calibrate.py", root, cfg)
    assert r.returncode == 0, r.stderr
    cal = {c["horizon_days"]: c for c in json.loads(r.stdout)["calibration"]}
    assert cal[1]["source"] == "pool" and cal[1]["n_history"] > 500
    assert cal[1]["q10"] < cal[1]["q25"] < 0 < cal[1]["q75"] < cal[1]["q90"]

    as_of = days[-1]
    made_at = f"{as_of}T23:00:00+00:00"                 # after the as-of close, before the next session's
    pred = {"id": f"{as_of}-AAPL-5d", "made_at": "2026-01-01T00:00:00+00:00", "as_of_date": str(as_of),
            "ticker": "AAPL", "horizon_days": 5, "direction": "up", "confidence": 0.8, "rationale": "t",
            "evidence_ids": ["x"], "prompt_version": "test", "range_widen": 0.3}
    p = root / "data" / MARKET / "predictions" / "2026" / "01" / "2026-01-01.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(pred) + "\n")

    r = run("ranges.py", root, cfg, "--now", made_at)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["written"] == 2 * len(horizons())   # 2 tickers x N+1..N+5
    assert json.loads(r.stdout)["late"] is False
    assert json.loads(run("ranges.py", root, cfg, "--now", made_at).stdout)["written"] == 0   # written once
    rows = {x["id"]: x for f in (root / "data" / MARKET / "ranges").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())}
    a5, m5 = rows[f"{as_of}-AAPL-5d"], rows[f"{as_of}-MSFT-5d"]
    for x in rows.values():
        assert x["lo80"] < x["lo50"] < x["hi50"] < x["hi80"]
        assert x["naive_lo80"] < x["base_close"] < x["naive_hi80"]
    assert a5["direction"] == "up" and a5["center"] > 0 and any("AI widened" in n for n in a5["notes"])
    assert m5["direction"] is None and m5["center"] == 0
    return series, made_at, rows


def score_targets(root: Path, cfg: Path, series: dict, made_at: str, rows: dict) -> None:
    """Add the bars the ranges target and score them, on the clock of the ranges' made_at (so the HTML track
    record, read as of made_at since issue #26, shows them)."""
    for t in sorted({x["target_date"] for x in rows.values()}):
        d = date.fromisoformat(t)
        f = root / "data" / MARKET / "prices" / f"{d:%Y}" / f"{d:%m}" / f"{d}.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n" +
                     "".join(f"{d},{k},{v[-1]},{v[-1]},{v[-1]},{v[-1]},{v[-1]},1000,2026-01-02T00:00:00+00:00\n"
                             for k, v in series.items()))
    s = json.loads(run_at(made_at, "score_predictions.py", root, cfg).stdout)
    assert s["ranges_scored"] == 2 * len(horizons()) and s["ranges_open"] == 0
    assert s["hit80"] == 2 * len(horizons())                    # unchanged price sits inside every range
    outs = [x for f in (root / "data" / MARKET / "range_outcomes").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())]
    assert all(o["naive_hit80"] and o["width80_pct"] > 0 for o in outs)


def run_at(now: str, script: str, root: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess:
    """A script run with MB_NOW set (the frozen clock)."""
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET, "MB_NOW": now}
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, check=False)


def check_charts_and_report(root: Path, cfg: Path) -> tuple[dict, dict, str]:
    """charts.py and report.py on the scored day: (charts summary, report summary, report text)."""
    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "Price ranges" in ctx.stdout and "Range scorecard" in ctx.stdout

    ch = run("charts.py", root, cfg)
    assert ch.returncode == 0, ch.stderr
    charts = json.loads(ch.stdout)
    # single-purpose images only (the per-ticker charts and the overview collage are gone)
    assert [Path(f).name for f in charts["charts"]] == ["ranges.png", "sectors.png", "track_record.png"]
    for f in charts["charts"]:
        assert (root / f).stat().st_size > 2000
    assert not list((root / "reports" / MARKET / "charts").glob("**/overview.png"))

    rep = run("report.py", root, cfg)
    assert rep.returncode == 0, rep.stderr
    out = json.loads(rep.stdout)
    text = (root / out["report"]).read_text()
    html_link = f"[{charts['session_date']}.html]({charts['session_date']}.html)"
    for needle in ("## Today", "<!-- AGENT:headline -->", "<!-- AGENT:top3 -->", "/ranges.png)", "/sectors.png)",
                   "/track_record.png)", html_link, "80% hit 2/2",
                   "## Track record", "<!-- AGENT:sector:Tech -->", "Market on ", "| 5d ▲ up 80% |",
                   "| 1d | since start | 2 |", "Ranges by regime", "Calls by confidence band"):
        assert needle in text, needle
    return charts, out, text


def check_report_rebuilds(root: Path, cfg: Path, out: dict, text: str) -> Path:
    """A filled report is kept by a re-run on the same data, rebuilt once the data changed."""
    rpath = root / out["report"]
    filled = re.sub(r"<!-- AGENT:[^>]*-->", "narrative", text)
    assert "<!-- report-data: as_of=" in filled
    rpath.write_text(filled)
    again = run("report.py", root, cfg)
    assert again.returncode == 0 and json.loads(again.stdout)["report_kept"] is True
    assert rpath.read_text() == filled and (root / out["slack_draft"]).exists()
    # issue #50: same as_of and regime, but this run's collect gate blocked: the forecast outcome changed
    steps = root / "work" / "steps"
    steps.mkdir(parents=True, exist_ok=True)
    gate = {"step": "validate", "market": MARKET, "stage": "collect", "failures": [{"code": "SCHEMA"}]}
    (steps / "validate_collect.json").write_text(json.dumps(gate))
    (steps / "validate_report.json").write_text(json.dumps({**gate, "stage": "report"}))   # not an input
    other = json.loads(run("report.py", root, cfg).stdout)
    assert other["report_kept"] is False and "forecast outcome" in other["warning"]
    assert (root / other["previous_report"]).read_text() == filled
    stamp = re.search(r"<!-- report-data: as_of=\S+ regime=\S+ outcome=([0-9a-f]{12}) -->", rpath.read_text())
    assert stamp and stamp.group(1) not in filled
    filled = re.sub(r"<!-- AGENT:[^>]*-->", "narrative", rpath.read_text())
    rpath.write_text(filled)
    (steps / "validate_report.json").write_text(json.dumps({**gate, "stage": "report", "failures": []}))
    assert json.loads(run("report.py", root, cfg).stdout)["report_kept"] is True   # the report gate never counts
    reg_file = sorted((root / "data" / MARKET / "regime").glob("**/*.jsonl"))[-1]
    last = json.loads(reg_file.read_text().splitlines()[-1])
    flipped = "UNSTABLE" if last["regime"] != "UNSTABLE" else "CALM"
    with reg_file.open("a") as f:
        f.write(json.dumps({**last, "regime": flipped, "computed_at": "2099-01-01T00:00:00+00:00"}) + "\n")
    stale = json.loads(run("report.py", root, cfg).stdout)
    assert stale["report_kept"] is False and "warning" in stale
    assert (root / stale["previous_report"]).read_text() == filled
    rebuilt = rpath.read_text()
    assert "<!-- AGENT:headline -->" in rebuilt and f"regime={flipped} outcome=" in rebuilt
    forced = json.loads(run("report.py", root, cfg, "--force").stdout)
    assert forced["report_kept"] is False and "<!-- AGENT:headline -->" in rpath.read_text()
    return rpath


def notify(root: Path, cfg: Path, env_no_hook: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "notify_slack.py"), *args], cwd=SCRIPTS,
                          capture_output=True, text=True,
                          env={**env_no_hook, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET})


READER_CONFIG = ("review.yaml", "strategies.yaml")


def check_html_and_slack(root: Path, cfg: Path, charts: dict, out: dict, rpath: Path) -> None:
    """The Slack draft, the HTML report (only from a filled report) and notify_slack.py's refusals and dry run."""
    slack = (root / out["slack_draft"]).read_text()
    assert "Calls today: 1 · AAPL ▲ up 80% (N+5, 80% range $" in slack
    assert out["url"].endswith(f"/reports/{MARKET}/{charts['session_date']}.html") and out["url"] in slack
    assert len(slack.strip().splitlines()) <= 12
    bad = run("html_report.py", root, cfg)
    assert bad.returncode == 1 and "AGENT markers" in bad.stdout
    rpath.write_text(re.sub(r"<!-- AGENT:[^>]*-->", "narrative", rpath.read_text()))
    for name in READER_CONFIG:   # the reader's page reads the website's readers (B4/B12), which read these
        if not (cfg / name).exists():
            (cfg / name).write_text((REPO / "config" / name).read_text())
    hr = run("html_report.py", root, cfg)
    assert hr.returncode == 0, hr.stderr
    hout = json.loads(hr.stdout)
    page = (root / hout["html"]).read_text()
    assert hout["html"] == f"reports/{MARKET}/{charts['session_date']}.html" and "AGENT" not in page
    data = json.loads(re.search(r'id="report-data">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
    reader = data["reader"]   # the reader block: as of the run's clock, active companies, N+1/N+3/N+5
    assert reader["horizons"] == [1, 3, 5] and reader["paper"]["live"] is False, reader["paper"]
    assert [c["ticker"] for c in reader["companies"]] == [c["ticker"] for c in data["companies"]]
    aapl = next(c for c in reader["companies"] if c["ticker"] == "AAPL")
    assert [f["name"] for f in aapl["forecasts"]] == ["N+1", "N+3", "N+5"] and len(aapl["bars"]) == 20
    first = aapl["forecasts"][0]
    assert first["lo80"] < first["lo50"] < first["hi50"] < first["hi80"] and first["exit_date"] > first["entry_date"]
    assert reader["mood"]["word"] == "Calm" and reader["benchmark"]["close_date"] == aapl["bars"][-1]["d"]
    assert reader["paper_label"] == "Paper only — no proven edge yet"
    assert f'href="{charts["session_date"]}.html"' in (root / hout["index"]).read_text()
    assert [Path(p).name for p in hout["images"]] == ["ranges.png", "sectors.png", "track_record.png"]

    # notify refuses unfilled drafts, then (without a token or webhook) reports exit code 2
    env_no_hook = {k: v for k, v in os.environ.items() if k not in ("SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN")}
    nb = notify(root, cfg, env_no_hook)
    assert nb.returncode == 1 and "AGENT markers" in nb.stdout
    draft = root / out["slack_draft"]
    draft.write_text(re.sub(r"<!-- AGENT:top3[^>]*-->", "• one\n• two\n• three", draft.read_text()))
    nb = notify(root, cfg, env_no_hook)
    assert nb.returncode == 2 and "AGENT" not in json.loads(nb.stdout)["text"]
    # dry run: the planned thread (summary, charts, HTML) and its files land in work/
    nb = notify(root, cfg, env_no_hook, "--dry-run")
    assert nb.returncode == 0, nb.stdout + nb.stderr
    plan = json.loads((root / json.loads(nb.stdout)["plan"]).read_text())
    assert [s["step"] for s in plan["thread"]] == ["summary", "charts", "report"]
    assert (root / "work" / f"slack_{MARKET}_plan" / f"{charts['session_date']}.html").exists()
    # holiday path: one free-text line, no draft needed
    nb = notify(root, cfg, env_no_hook, "--text", "Test market: market closed today")
    assert nb.returncode == 2 and json.loads(nb.stdout)["text"] == "Test market: market closed today\n"


def test_calibrate_ranges_and_scoring(tmp_path):
    root, cfg = setup(tmp_path)
    series, made_at, rows = publish_ranges(root, cfg)
    score_targets(root, cfg, series, made_at, rows)
    charts, out, text = check_charts_and_report(root, cfg)
    rpath = check_report_rebuilds(root, cfg, out, text)
    check_html_and_slack(root, cfg, charts, out, rpath)


def test_backtest_coverage_is_calibrated(tmp_path):
    root, cfg = setup(tmp_path)
    rng = np.random.default_rng(3)
    days = weekdays(date(2024, 1, 1), 560)
    series = {"BENCH": fat_tailed_walk(rng, 560, 100, 0.01), "VOLX": [15.0] * 560,
              "AAPL": fat_tailed_walk(rng, 560, 150, 0.015), "MSFT": fat_tailed_walk(rng, 560, 300, 0.02)}
    write_bars(root, series, days)
    r = run("backtest.py", root, cfg, "--eval-sessions", "150")
    assert r.returncode == 0, r.stderr
    h1 = json.loads(r.stdout)["horizons"]["1"]["all"]
    assert h1["n"] >= 250
    assert 0.72 <= h1["cover80"] <= 0.88 and 0.42 <= h1["cover50"] <= 0.58
    assert (root / "reports" / MARKET / f"backtest-{days[-1]}.md").exists()
