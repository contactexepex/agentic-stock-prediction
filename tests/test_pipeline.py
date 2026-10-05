"""Offline end-to-end tests: local RSS fixture, synthetic prices, prediction scoring, features,
regime and the context pack, all on a small throwaway market config.
Run: pytest -q"""
from __future__ import annotations

import json
import os
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
    return root, cfg


def weekdays(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
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
    rows = [json.loads(l) for f in (root / "data" / MARKET / "news").glob("**/*.jsonl")
            for l in f.read_text().splitlines()]
    tagged = {r["title"]: r["tickers"] for r in rows}
    assert tagged["Apple raises guidance"] == ["AAPL"]
    assert tagged["Fed holds rates"] == []
    # second run sees the same items and writes nothing new
    assert json.loads(run("collect_news.py", root, cfg).stdout)["new_items"] == 0


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
    assert "| 5 | 2 | 0.5 |" in ctx.stdout                # 1 hit out of 2 scored


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
    assert a["days_to_earnings"] is not None and a["days_to_earnings"] <= 3
    assert feats["MSFT"]["ret_1d"] == 0.0
    assert abs(feats["MSFT"]["rel_sector_5d"] + a["rel_sector_5d"]) < 1e-9   # mirror images

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    for heading in ("Market regime", "Upcoming events", "Indicators", "Apple earnings"):
        assert heading in ctx.stdout
    assert "SEC filings" not in ctx.stdout


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


def test_calibrate_ranges_and_scoring(tmp_path):
    root, cfg = setup(tmp_path)
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
    pred = {"id": f"{as_of}-AAPL-5d", "made_at": "2026-01-01T00:00:00+00:00", "as_of_date": str(as_of),
            "ticker": "AAPL", "horizon_days": 5, "direction": "up", "confidence": 0.8, "rationale": "t",
            "evidence_ids": ["x"], "prompt_version": "test", "range_widen": 0.3}
    p = root / "data" / MARKET / "predictions" / "2026" / "01" / "2026-01-01.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(pred) + "\n")

    r = run("ranges.py", root, cfg)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["written"] == 4                 # 2 tickers x 2 horizons
    assert json.loads(run("ranges.py", root, cfg).stdout)["written"] == 0   # written once
    rows = {x["id"]: x for f in (root / "data" / MARKET / "ranges").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())}
    a5, m5 = rows[f"{as_of}-AAPL-5d"], rows[f"{as_of}-MSFT-5d"]
    for x in rows.values():
        assert x["lo80"] < x["lo50"] < x["hi50"] < x["hi80"]
        assert x["naive_lo80"] < x["base_close"] < x["naive_hi80"]
    assert a5["direction"] == "up" and a5["center"] > 0 and any("AI widened" in n for n in a5["notes"])
    assert m5["direction"] is None and m5["center"] == 0

    # add the bars the ranges target and score them
    targets = sorted({x["target_date"] for x in rows.values()})
    for i, t in enumerate(targets):
        d = date.fromisoformat(t)
        f = root / "data" / MARKET / "prices" / f"{d:%Y}" / f"{d:%m}" / f"{d}.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n" +
                     "".join(f"{d},{k},{v[-1]},{v[-1]},{v[-1]},{v[-1]},{v[-1]},1000,2026-01-02T00:00:00+00:00\n"
                             for k, v in series.items()))
    s = json.loads(run("score_predictions.py", root, cfg).stdout)
    assert s["ranges_scored"] == 4 and s["ranges_open"] == 0
    assert s["hit80"] == 4                                      # unchanged price sits inside every range
    outs = [x for f in (root / "data" / MARKET / "range_outcomes").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())]
    assert all(o["naive_hit80"] and o["width80_pct"] > 0 for o in outs)

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "Price ranges" in ctx.stdout and "Range scorecard" in ctx.stdout


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
