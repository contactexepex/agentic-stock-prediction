"""Offline tests for phase 5 relationships: the India relations collector (replaying synthetic,
hand-written NSE responses from tests/fixtures/nse that match public scraper field names but are
not yet checked against a live NSE response), its failure path when NSE is unreachable, risk
flags and optional range widening, the connection map (validation, append-only updates,
monthly refresh attempts, second-order news hits) and the context-pack sections.
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
    (root / ".scratch-ok").write_text("")          # explicit scratch root: --replay may write here
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
    out.mkdir(parents=True)
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
    assert st["edges"] == 3 and st["refresh_due"] is True and "HDFCBANK" in st["tickers_without_edges"]
    assert json.loads(run("graph.py", root, cfg, "attempt").stdout)["edges"] == 3    # only an attempt clears it
    assert json.loads(run("graph.py", root, cfg, "status").stdout)["refresh_due"] is False

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


def test_replay_refuses_to_write_into_repo_data(tmp_path):
    _, cfg = setup(tmp_path)
    target = REPO / "data" / MARKET
    assert not target.exists()
    for i, root in enumerate((REPO, REPO / "data" / "..")):
        r = run("collect_relations_india.py", root, cfg, "--replay", str(replay_dir(tmp_path / f"r{i}")))
        assert r.returncode == 2 and "refusing" in json.loads(r.stdout)["error"]
    assert not target.exists()                                                    # nothing written


def _tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else []


def test_replay_scratch_root_rules(tmp_path):
    """Replay writes only to an explicit scratch root that is not a repo checkout or a real data
    store, and whose write targets do not escape through symlinks."""
    _, cfg = setup(tmp_path)
    replay = replay_dir(tmp_path)

    def refused(root: Path, why: str) -> None:
        before = _tree(root)
        r = run("collect_relations_india.py", root, cfg, "--replay", str(replay))
        assert r.returncode == 2, r.stdout + r.stderr
        assert why in json.loads(r.stdout)["error"], r.stdout
        assert _tree(root) == before                                              # not even a directory

    def scratch(name: str) -> Path:
        root = tmp_path / name
        (root / "data").mkdir(parents=True)
        (root / ".scratch-ok").write_text("")
        return root

    bare = tmp_path / "bare"
    (bare / "data").mkdir(parents=True)
    refused(bare, "no .scratch-ok")                                               # no opt-in marker

    # Bypass A: another checkout of the repo (e.g. the main clone, run from a worktree's scripts/)
    checkout = scratch("checkout")
    (checkout / ".git").mkdir()
    (checkout / "CLAUDE.md").write_text("# market-brief\n")
    refused(checkout, "looks like a repo checkout")
    claude_only = scratch("claude_only")
    (claude_only / "CLAUDE.md").write_text("# market-brief\n")
    refused(claude_only, "CLAUDE.md")
    store = scratch("store")
    (store / "data" / "india" / "prices" / "2026" / "10").mkdir(parents=True)
    (store / "data" / "india" / "prices" / "2026" / "10" / "2026-10-05.csv").write_text("date,ticker\n")
    refused(store, "real data store")

    # Bypass B: data/<market> is a symlink to a real data directory elsewhere
    real = tmp_path / "realrepo" / "data" / MARKET
    real.mkdir(parents=True)
    linked = scratch("linked")
    (linked / "data" / MARKET).symlink_to(real, target_is_directory=True)
    refused(linked, "outside")
    assert _tree(real) == []                                                      # nothing written through it
    whole = tmp_path / "whole"
    whole.mkdir()
    (whole / ".scratch-ok").write_text("")
    (whole / "data").symlink_to(real.parent, target_is_directory=True)            # data/ itself a symlink
    refused(whole, "outside")
    assert _tree(real) == []

    # hard-linked target file: same inode as a file in a real data tree, survives resolve()
    today = datetime.now(timezone.utc).date()
    rel = Path(MARKET) / "insiders" / f"{today:%Y}" / f"{today:%m}" / f"{today:%Y-%m-%d}.jsonl"
    real_file = tmp_path / "realrepo2" / "data" / rel
    real_file.parent.mkdir(parents=True)
    real_file.write_text('{"id": "real-row"}\n')
    hl = scratch("hl")
    (hl / "data" / rel).parent.mkdir(parents=True)
    os.link(real_file, hl / "data" / rel)
    r = run("collect_relations_india.py", hl, cfg, "--replay", str(replay), "--only", "insiders")
    assert r.returncode == 2 and "hard-linked" in json.loads(r.stdout)["error"], r.stdout
    assert real_file.read_text() == '{"id": "real-row"}\n'                        # linked file unchanged

    # a proper scratch root still works
    ok = scratch("ok")
    r = run("collect_relations_india.py", ok, cfg, "--replay", str(replay))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["new"]["insiders"] == 3
    assert any(p.endswith(".jsonl") for p in _tree(ok / "data" / MARKET / "insiders"))


def test_live_failure_reports_hosts_to_allowlist(monkeypatch):
    """No network: the HTTP opener raises like the egress proxy does; nothing may be written."""
    import urllib.error
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import collect_relations_india as cri

    def no_write(*a, **k):
        raise AssertionError("nothing should be written when every source fails")
    monkeypatch.setattr(cri, "append_jsonl", no_write)
    cfg = {"market": MARKET, "relations": {"source": "nse"},
           "tickers": {"INFY": {"yahoo": "INFY.NS"}, "RELIANCE": {"yahoo": "RELIANCE.NS"}}}

    def proxy_denied(req, timeout=None):
        raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
    nse = cri.Nse("https://www.nseindia.com", "https://nsearchives.nseindia.com", pause=0)
    monkeypatch.setattr(nse.opener, "open", proxy_denied)
    out = cri.collect(cfg, nse, ["insiders", "deals", "holdings"])
    assert out["new"] == {"insiders": None, "deals": None, "holdings": None}
    assert out["allowlist_needed"] == ["nsearchives.nseindia.com", "www.nseindia.com"]
    sources = {f["source"] for f in out["failed"]}
    assert {"insiders", "deals:bulk:nse_archive", "deals:block:nse_historical"} <= sources
    assert sum(s.startswith("holdings:") for s in sources) == 1                   # fails fast per host
    assert all("egress proxy denied" in f["error"] and f["allowlist"] for f in out["failed"])

    def nse_refuses(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    nse = cri.Nse("https://www.nseindia.com", "https://nsearchives.nseindia.com", pause=0)
    monkeypatch.setattr(nse.opener, "open", nse_refuses)
    out = cri.collect(cfg, nse, ["insiders"])
    assert out["new"] == {"insiders": None} and "allowlist_needed" not in out
    assert "HTTP 403" in out["failed"][0]["error"]


def test_graph_refresh_due_once_per_month(tmp_path):
    root, cfg = setup(tmp_path)
    assert json.loads(run("graph.py", root, cfg, "status").stdout)["refresh_due"] is True
    a = run("graph.py", root, cfg, "attempt", "--note", "no sources found")
    assert a.returncode == 0, a.stderr
    assert json.loads(a.stdout)["edges"] == 0
    st = json.loads(run("graph.py", root, cfg, "status").stdout)
    assert st["refresh_due"] is False and st["edges"] == 0 and st["last_attempt_at"]   # empty map, not repeated

    root2, cfg2 = setup(tmp_path / "old")
    last_month = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    f = root2 / "data" / MARKET / "graph_runs" / f"{last_month:%Y}" / f"{last_month:%m}" / f"{last_month:%Y-%m-%d}.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"id": "x", "run_at": last_month.isoformat(), "month": f"{last_month:%Y-%m}",
                             "edges": 5, "tickers_without_edges": 0, "note": None}) + "\n")
    assert json.loads(run("graph.py", root2, cfg2, "status").stdout)["refresh_due"] is True


def test_graph_check_validates_without_writing(tmp_path):
    root, cfg = setup(tmp_path)
    before = _tree(root)
    r = run("graph.py", root, cfg, "check", str(FIXTURES / "graph_edges.jsonl"))
    assert r.returncode == 1                                     # the fixture has one invalid edge
    out = json.loads(r.stdout)
    assert (out["step"], out["would_write"], len(out["rejected"])) == ("graph_check", 3, 1)
    assert _tree(root) == before                                 # nothing written anywhere under the root
    assert not (root / "data" / "india" / "graph").exists()
