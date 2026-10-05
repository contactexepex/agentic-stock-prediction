"""Offline tests for phase 5 relationships: the India relations collector (replaying saved NSE
responses from tests/fixtures/nse), risk flags and optional range widening, the connection map
(validation, append-only updates, second-order news hits) and the context-pack sections.
Run: pytest -q"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FIXTURES = REPO / "tests" / "fixtures"
MARKET = "relmkt"

MARKET_YAML = """
market: relmkt
name: Relations test market
calendar: XBOM
timezone: Asia/Kolkata
currency: INR
symbols:
  BENCH: {role: benchmark, name: Benchmark}
  VOLX: {role: vol_index, name: Vol index}
regime: {unstable_vol: 22, event_vol: 17, calm_vol: 14, unstable_bench_vol: 0.25,
         trend_return_5d: 0.015, flat_return_5d: 0.005, stress_vol_jump: 0.30}
sectors:
  Banks: [HDFCBANK, ICICIBANK]
  IT: [INFY, TCS]
  Energy: [RELIANCE]
tickers:
  HDFCBANK:  {yahoo: HDFCBANK.NS, name: HDFC Bank}
  ICICIBANK: {yahoo: ICICIBANK.NS, name: ICICI Bank}
  INFY:      {yahoo: INFY.NS, name: Infosys}
  TCS:       {yahoo: TCS.NS, name: Tata Consultancy Services}
  RELIANCE:  {yahoo: RELIANCE.NS, name: Reliance Industries}
%s
"""
RELATIONS_YAML = """
relations:
  source: nse
  insider_lookback_days: 14
  deal_lookback_days: 5
  flags: {window_days: 5, big_deal_crore: 250, big_deal_adv: 0.5, insider_sale_crore: 10,
          pledge_increase_pp: 1.0, pledge_filed_days: 60}
"""


def setup(tmp: Path, relations: bool = True, widen: bool = False) -> tuple[Path, Path]:
    root, cfg = tmp / "repo", tmp / "config"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML % (RELATIONS_YAML if relations else ""))
    for name in ("events.yaml", "settings.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    ranges = (REPO / "config" / "ranges.yaml").read_text()
    if widen:
        assert "  enabled: false" in ranges
        ranges = ranges.replace("  enabled: false", "  enabled: true")
    (cfg / "ranges.yaml").write_text(ranges)
    return root, cfg


def run(script: str, root: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET}
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, check=False)


def replay_dir(tmp: Path) -> Path:
    """Copy the NSE fixtures, replacing __Dn__ with the IST date n days ago (NSE format)."""
    out = tmp / "nse"
    out.mkdir()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    for f in (FIXTURES / "nse").iterdir():
        text = f.read_text()
        for n in range(31):
            text = text.replace(f"__D{n}__", f"{today - timedelta(days=n):%d-%b-%Y}")
        (out / f.name).write_text(text)
    return out


def rows(root: Path, kind: str) -> list[dict]:
    return [json.loads(line) for f in sorted((root / "data" / MARKET / kind).glob("**/*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]


def test_relations_collector_flags_and_context(tmp_path):
    root, cfg = setup(tmp_path)
    replay = replay_dir(tmp_path)
    r = run("collect_relations_india.py", root, cfg, "--replay", str(replay))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["new"] == {"insiders": 3, "deals": 2, "holdings": 5}
    assert any("block deals from nse_snapshot" in n for n in out["notes"])       # fallback used
    assert out["failed"] and all("allowlist" not in f for f in out["failed"])     # missing replay files only

    ins = {r["ticker"]: r for r in rows(root, "insiders")}
    assert set(ins) == {"INFY", "RELIANCE", "TCS"}                                # NOTWATCHED dropped
    assert ins["INFY"]["value"] == 300000000 and ins["INFY"]["person_category"] == "Director"
    assert ins["RELIANCE"]["shares"] == 1000000 and ins["RELIANCE"]["value"] is None
    assert ins["INFY"]["disclosed_at"].endswith("+00:00")                        # IST converted to UTC
    deals = {d["ticker"]: d for d in rows(root, "deals")}
    assert set(deals) == {"HDFCBANK", "ICICIBANK"}                                # old deal outside lookback
    assert deals["HDFCBANK"]["side"] == "buy" and deals["HDFCBANK"]["value"] == 5000000 * 1600.5
    assert deals["ICICIBANK"]["deal_type"] == "block" and deals["ICICIBANK"]["source"] == "nse_snapshot"
    hold = rows(root, "holdings")
    assert {(h["source"], h["period_end"]) for h in hold if h["ticker"] == "RELIANCE"} == {
        ("nse_shp", "2026-06-30"), ("nse_shp", "2026-03-31"), ("nse_pledge", "2026-06-30"), ("nse_pledge", "2026-03-31")}

    # append-only and de-duplicated: a rerun writes nothing new
    again = json.loads(run("collect_relations_india.py", root, cfg, "--replay", str(replay)).stdout)
    assert again["new"] == {"insiders": 0, "deals": 0, "holdings": 0}

    fl = json.loads(run("relations.py", root, cfg).stdout)
    got = {(f["ticker"], f["flag"]) for f in fl["flags"]}
    assert got == {("HDFCBANK", "big_deal"), ("RELIANCE", "pledge_increase"), ("RELIANCE", "pledge_created"),
                   ("INFY", "insider_sale")}
    assert fl["widen"] == {}                                                      # off by default

    root2, cfg2 = setup(tmp_path / "w", widen=True)
    assert run("collect_relations_india.py", root2, cfg2, "--replay", str(replay)).returncode == 0
    widen = json.loads(run("relations.py", root2, cfg2).stdout)["widen"]
    assert widen == {"HDFCBANK": 0.10, "RELIANCE": 0.15, "INFY": 0.05}

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    for needle in ("Insider and promoter trades", "Test Director One", "Bulk and block deals", "TEST GLOBAL FUND",
                   "Promoter holding and pledge", "| RELIANCE | 2026-06-30 | 50.1 | -0.2 | 2.0 | 1.5 |",
                   "Relationship risk flags", "pledge_increase", "Connections: second-order news"):
        assert needle in ctx.stdout, needle


def test_collector_skips_market_without_relations(tmp_path):
    root, cfg = setup(tmp_path, relations=False)
    r = run("collect_relations_india.py", root, cfg)
    assert r.returncode == 0 and "skipped" in json.loads(r.stdout)
    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "Insider and promoter trades" not in ctx.stdout and "no connection map yet" in ctx.stdout


def write_news(root: Path, items: list[tuple[str, str, list[str]]]) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    f = root / "data" / MARKET / "news" / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps({"id": nid, "title": title, "url": None, "source": "Test", "published_at": now.isoformat(),
                                     "first_seen_at": now.isoformat(), "feed": "t", "category": "company",
                                     "tickers": tickers}) + "\n" for nid, title, tickers in items))


def test_graph_add_hits_and_retract(tmp_path):
    root, cfg = setup(tmp_path)
    write_news(root, [("n1", "Wipro wins a large cloud deal", []),
                      ("n2", "Infosys shares jump after results", ["INFY"]),
                      ("n3", "Mukesh Ambani speaks at Reliance Industries AGM", ["RELIANCE"]),
                      ("n4", "Wiproxyz is not a company we track", [])])
    assert json.loads(run("graph.py", root, cfg, "status").stdout)["refresh_due"] is True

    r = run("graph.py", root, cfg, "add", str(FIXTURES / "graph_edges.jsonl"))
    assert r.returncode == 1                                                      # one invalid edge
    out = json.loads(r.stdout)
    assert out["written"] == 3 and len(out["rejected"]) == 1
    assert any("relation" in e for e in out["rejected"][0]["errors"])
    assert any("source_url" in e for e in out["rejected"][0]["errors"])

    valid = tmp_path / "valid.jsonl"
    valid.write_text("".join(FIXTURES.joinpath("graph_edges.jsonl").read_text().splitlines(keepends=True)[:3]))
    again = json.loads(run("graph.py", root, cfg, "add", str(valid)).stdout)
    assert (again["written"], again["unchanged"]) == (0, 3)                       # unchanged edges not re-appended

    st = json.loads(run("graph.py", root, cfg, "status").stdout)
    assert st["edges"] == 3 and st["refresh_due"] is False and "HDFCBANK" in st["tickers_without_edges"]

    hits = json.loads(run("graph.py", root, cfg, "hits").stdout)["hits"]
    got = {(h["ticker"], h["news_id"]) for h in hits}
    assert got == {("INFY", "n1"), ("TCS", "n2")}                                 # n3 is first-order, n4 no match
    assert next(h for h in hits if h["ticker"] == "TCS")["via"] == ["competitor: Infosys"]

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "| TCS | competitor: Infosys | n2 |" in ctx.stdout and "Map: 3 edges" in ctx.stdout

    retract = tmp_path / "retract.jsonl"
    edge = json.loads(valid.read_text().splitlines()[0])
    retract.write_text(json.dumps({**edge, "status": "removed"}) + "\n")
    assert json.loads(run("graph.py", root, cfg, "add", str(retract)).stdout)["written"] == 1
    hits = json.loads(run("graph.py", root, cfg, "hits").stdout)["hits"]
    assert {(h["ticker"], h["news_id"]) for h in hits} == {("TCS", "n2")}
    files = list((root / "data" / MARKET / "graph").glob("**/*.jsonl"))
    assert len(files) == 1 and len(files[0].read_text().splitlines()) == 4        # appended, never rewritten
