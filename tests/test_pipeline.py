"""Offline end-to-end tests: local RSS fixture, synthetic prices, prediction scoring, context pack.
Run: pytest -q"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def run(script: str, root: Path, cfg: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg)}
    return subprocess.run([sys.executable, str(SCRIPTS / script)], cwd=SCRIPTS, env=env,
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
    cfg.mkdir()
    feed = tmp / "feed.xml"
    feed.write_text(rss([("Apple raises guidance", "iPhone demand strong"),
                         ("Fed holds rates", "no ticker here"),
                         ("Apple raises guidance", "duplicate in same feed")]))
    (cfg / "feeds.yaml").write_text(
        f"outlets:\n  - {{name: Fixture, url: '{feed}', category: general}}\n")
    (cfg / "watchlist.yaml").write_text("tickers:\n  AAPL:\n    name: Apple\n    aliases: [iPhone]\n")
    return root, cfg


def write_prices(root: Path, start: date, closes: list[float]) -> list[date]:
    days, d = [], start
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    for day, close in zip(days, closes):
        p = root / "data" / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
                     f"{day},AAPL,{close},{close},{close},{close},{close},1000,2026-01-01T00:00:00+00:00\n")
    return days


def test_news_collect_tags_and_dedupes(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_news.py", root, cfg)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["new_items"] == 2
    rows = [json.loads(l) for f in (root / "data" / "news").glob("**/*.jsonl")
            for l in f.read_text().splitlines()]
    tagged = {r["title"]: r["tickers"] for r in rows}
    assert tagged["Apple raises guidance"] == ["AAPL"]
    assert tagged["Fed holds rates"] == []
    # second run sees the same items and writes nothing new
    assert json.loads(run("collect_news.py", root, cfg).stdout)["new_items"] == 0


def test_scoring_and_context(tmp_path):
    root, cfg = setup(tmp_path)
    days = write_prices(root, date(2026, 9, 1), [100, 101, 102, 103, 104, 105, 99])
    pred_dir = root / "data" / "predictions" / "2026" / "09"
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
    assert summary == {"step": "score", "scored": 2, "still_open": 1}
    outcomes = {o["prediction_id"]: o for f in (root / "data" / "outcomes").glob("**/*.jsonl")
                for o in map(json.loads, f.read_text().splitlines())}
    assert outcomes[preds[0]["id"]]["hit"] is True        # 100 -> 105
    assert outcomes[preds[1]["id"]]["hit"] is False       # 101 -> 99
    assert outcomes[preds[0]["id"]]["target_date"] == str(days[5])

    # scoring again is idempotent
    assert json.loads(run("score_predictions.py", root, cfg).stdout)["scored"] == 0

    run("collect_news.py", root, cfg)
    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "Latest prices and returns" in ctx.stdout and "| AAPL |" in ctx.stdout
    assert "| 5 | 2 | 0.5 |" in ctx.stdout                # 1 hit out of 2 scored


def test_context_on_empty_repo(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("context.py", root, cfg)
    assert r.returncode == 0, r.stderr
    assert "_none_" in r.stdout
