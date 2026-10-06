"""Offline tests for scripts/neo4j_sync.py (the Neo4j projection, docs/DESIGN.md section 12):
dry-run statements are static and parameterised, a fake Query API v2 server receives
authenticated, idempotent MERGE batches, corrections (newer enrichment, regime recompute,
retracted graph edge, moved earnings date) win, failures exit non-zero, the password is never
printed, and data/ is never touched. Optional: set NEO4J_TEST_QUERY_URL (+ NEO4J_TEST_USER,
NEO4J_TEST_PASSWORD) to a disposable Neo4j 5 server to run the same data through a real engine.
Run: pytest -q"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
MARKET = "neomkt"
PASSWORD = "pw-SECRET-4f9c2e"   # must never appear in any output
USER = "neo4j-user"

MARKET_YAML = """
market: neomkt
name: Neo test market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  BENCH: {role: benchmark, name: Benchmark}
  VOLX: {role: vol_index, name: Vol index}
  XLK: {role: sector_etf, name: Tech ETF, sectors: [Tech]}
regime: {unstable_vol: 28, event_vol: 20, calm_vol: 16, unstable_bench_vol: 0.25,
         trend_return_5d: 0.015, flat_return_5d: 0.005, stress_vol_jump: 0.30}
sectors:
  Tech: [AAA, BBB]
  Energy: [CCC]
tickers:
  AAA: {name: Alpha Inc}
  BBB: {name: Beta Ltd}
  CCC: {name: Gamma Corp}
"""

T1, T2, T3 = "2026-10-01T10:00:00+00:00", "2026-10-02T10:00:00+00:00", "2026-10-03T10:00:00+00:00"
# Distinctive values that must travel only as parameters, never inside a statement.
SENTINELS = ["SENTINEL-TITLE-7731", "Jane SENTINEL Doe", "SENTINEL Big Fund", "SENTINEL-RATIONALE-55",
             "https://example.com/SENTINEL-src"]

DATA: dict[str, list[dict]] = {
    "news": [
        {"id": "n1", "title": "SENTINEL-TITLE-7731 Alpha cuts guidance", "url": "https://e.com/n1", "source": "Wire",
         "published_at": T1, "first_seen_at": T1, "feed": "f", "category": "c", "tickers": ["AAA"], "tag_version": 2},
        {"id": "n2", "title": "Alpha and Beta \"quoted\" 'name' } { ) news", "url": "https://e.com/n2", "source": "Wire",
         "published_at": T2, "first_seen_at": T2, "feed": "f", "category": "c", "tickers": ["AAA", "BBB"], "tag_version": 2},
    ],
    "news_enriched": [
        {"id": "n1", "analyzed_at": T1, "relevance": 0.9, "sentiment": -0.5, "materiality": "high",
         "event_type": "earnings", "prompt_version": "na-v1"},
        {"id": "n1", "analyzed_at": T2, "relevance": 0.9, "sentiment": 0.7, "materiality": "medium",
         "event_type": "earnings", "prompt_version": "na-v2"},        # correction: newer analysis wins
        {"id": "n2", "analyzed_at": T2, "relevance": 0.5, "sentiment": -0.8, "materiality": "low",
         "event_type": "sector", "prompt_version": "na-v1"},
        {"id": "nse-ann-1", "analyzed_at": T2, "relevance": 0.6, "sentiment": 0.2, "materiality": "low",
         "event_type": "other", "prompt_version": "na-v1"},
    ],
    "filings": [{"id": "0000-26-000001", "ticker": "AAA", "cik": "1", "form": "8-K", "filing_date": "2026-10-01",
                 "accepted_at": T1, "description": "Results", "url": "https://sec.gov/x", "first_seen_at": T1}],
    "announcements": [{"id": "nse-ann-1", "ticker": "BBB", "company": "Beta", "published_at": T1,
                       "category": "Results", "subject": "Board meeting", "url": "https://nse/x", "source": "nse",
                       "first_seen_at": T1}],
    "events": [
        {"id": "AAA-earnings-2026-10-03", "date": "2026-10-03", "type": "earnings", "ticker": "AAA", "name": "Q3",
         "source": "yfinance", "first_seen_at": T1},
        {"id": "AAA-earnings-2026-10-04", "date": "2026-10-04", "type": "earnings", "ticker": "AAA", "name": "Q3",
         "source": "yfinance", "first_seen_at": T2},                  # moved date: the newer one is current
        {"id": "fomc-2026-10-02", "date": "2026-10-02", "type": "fomc", "ticker": None, "name": "FOMC",
         "source": "config", "first_seen_at": T1},
    ],
    "insiders": [
        {"id": "acc1-1", "accession": "acc1", "line": 1, "ticker": "AAA", "form": "4", "filing_date": "2026-10-02",
         "accepted_at": T2, "insider_name": "Jane SENTINEL Doe", "insider_cik": "0001", "role": "CFO",
         "is_director": False, "is_officer": True, "derivative": False, "transaction_date": "2026-10-01",
         "code": "S", "acquired_disposed": "D", "shares": 1000.0, "price": 10.0, "value": 10000.0,
         "url": "https://sec.gov/f4", "first_seen_at": T2},
        {"id": "pit-1", "ticker": "BBB", "source": "nse_pit", "person": "Promoter Co", "person_category": "Promoter Group",
         "transaction": "Sell", "mode": "Market Sale", "shares": 5.0, "value": 50.0, "trade_from": "2026-09-30",
         "trade_to": "2026-09-30", "disclosed_at": T1, "url": "https://nse/pit", "first_seen_at": T1},
    ],
    "deals": [{"id": "deal-1", "date": "2026-10-01", "ticker": "BBB", "deal_type": "Bulk", "client": "SENTINEL Big Fund",
               "side": "BUY", "shares": 100.0, "price": 9.0, "value": 900.0, "source": "nse", "first_seen_at": T1}],
    "stakes": [{"id": "13d-1", "ticker": "AAA", "issuer_cik": "1", "form": "SC 13D", "kind": "13D", "amendment": False,
                "filing_date": "2026-10-01", "accepted_at": T1, "event_date": "2026-09-25", "filer_name": "Activist LP",
                "filer_cik": "0009", "reporting_persons": ["Activist LP", None], "percent": 6.1, "shares": 1e6,
                "url": "https://sec.gov/13d", "first_seen_at": T1}],
    "holdings": [
        {"id": "13f-a", "accession": "a", "filer_cik": "0007", "filer_name": "Fund Seven", "period": "2026-03-31",
         "filing_date": "2026-05-10", "ticker": "AAA", "shares": 100.0, "value_usd": 1000.0, "complete": True,
         "first_seen_at": T1},
        {"id": "13f-b", "accession": "b", "filer_cik": "0007", "filer_name": "Fund Seven", "period": "2026-06-30",
         "filing_date": "2026-08-10", "ticker": "AAA", "shares": 150.0, "value_usd": 1600.0, "complete": True,
         "first_seen_at": T1},
        {"id": "shp-1", "ticker": "CCC", "period_end": "2026-06-30", "source": "nse_shp", "promoter_pct": 50.0,
         "public_pct": 50.0, "pledged_pct_of_promoter": 2.0, "filed_at": T1, "first_seen_at": T1},
    ],
    "graph": [
        {"id": "AAA|supplier|gamma-corp", "ticker": "AAA", "relation": "supplier", "target": "Gamma Corp",
         "target_kind": "company", "target_ticker": "CCC", "aliases": [], "detail": "supplies parts", "weight": None,
         "status": "active", "as_of": "2026-09-01", "source_url": "https://example.com/SENTINEL-src", "added_at": T1},
        {"id": "AAA|board|john-smith", "ticker": "AAA", "relation": "board", "target": "John Smith",
         "target_kind": "person", "target_ticker": None, "aliases": ["J. Smith"], "status": "active",
         "as_of": "2026-09-01", "source_url": "https://example.com/board", "added_at": T1},
        {"id": "BBB|competitor|delta", "ticker": "BBB", "relation": "competitor", "target": "Delta",
         "target_kind": "company", "target_ticker": None, "status": "active", "as_of": "2026-09-01",
         "source_url": "https://example.com/d", "added_at": T1},
        {"id": "BBB|competitor|delta", "ticker": "BBB", "relation": "competitor", "target": "Delta",
         "target_kind": "company", "target_ticker": None, "status": "removed", "as_of": "2026-09-02",
         "source_url": "https://example.com/d", "added_at": T2},          # retraction
    ],
    "predictions": [{"id": "2026-10-01-AAA-1d", "made_at": T1, "as_of_date": "2026-10-01", "ticker": "AAA",
                     "horizon_days": 1, "direction": "down", "confidence": 0.6, "rationale": "SENTINEL-RATIONALE-55",
                     "evidence_ids": ["n1", "0000-26-000001", "not-synced-yet"], "prompt_version": "fc-v1",
                     "range_widen": 0.0}],
    "outcomes": [{"prediction_id": "2026-10-01-AAA-1d", "scored_at": T2, "base_date": "2026-10-01", "base_close": 10.0,
                  "target_date": "2026-10-02", "target_close": 9.5, "actual_return": -0.05, "hit": True}],
    "ranges": [{"id": "2026-10-01-AAA-1d", "made_at": T1, "as_of_date": "2026-10-01", "session_date": "2026-10-02",
                "target_date": "2026-10-02", "ticker": "AAA", "horizon_days": 1, "base_close": 10.0, "center": 9.9,
                "sigma_h": 0.02, "lo50": 9.8, "hi50": 10.0, "lo80": 9.6, "hi80": 10.2, "direction": "down",
                "confidence": 0.6, "regime": "CALM", "notes": ["n"], "inputs": []}],
    "range_outcomes": [{"range_id": "2026-10-01-AAA-1d", "scored_at": T2, "target_date": "2026-10-02",
                        "actual_close": 9.5, "z": -1.2, "hit50": False, "hit80": True}],
    "regime": [
        {"id": "2026-10-01", "as_of_date": "2026-10-01", "session_date": "2026-10-02", "computed_at": T1,
         "regime": "CALM", "vol_level": 15.0, "major_event": False, "major_event_names": [], "stress": False, "notes": []},
        {"id": "2026-10-01", "as_of_date": "2026-10-01", "session_date": "2026-10-02", "computed_at": T2,
         "regime": "TRENDING", "vol_level": 15.5, "major_event": False, "major_event_names": [], "stress": False,
         "notes": []},                                                    # recomputed: latest wins
    ],
    "features": [{"id": "2026-10-01-AAA", "as_of_date": "2026-10-01", "ticker": "AAA", "computed_at": T1,
                  "close": 10.0, "rsi_14": 45.0, "quality": "OK", "warnings": [], "days_to_earnings": 2,
                  "ex_dividend_date": None}],
    "judgments": [{"id": "2026-10-01-forecaster-1-100000", "run_date": "2026-10-01", "agent": "forecaster", "round": 1,
                   "verdict": "PASS", "summary": "ok", "dropped": None, "recorded_at": T1}],
    "financials": [{"id": "fin-1", "ticker": "CCC", "basis": "consolidated", "period_type": "quarterly",
                    "period_start": "2026-04-01", "period_end": "2026-06-30", "revenue": 100.0, "net_profit": 10.0,
                    "filed_at": T1, "first_seen_at": T1}],
    "flows": [{"id": "flow-1", "date": "2026-10-01", "category": "FII", "buy_cr": 10.0, "sell_cr": 5.0, "net_cr": 5.0,
               "provisional": True, "source": "nse", "first_seen_at": T1}],
}


def setup(tmp: Path) -> tuple[Path, Path]:
    root, cfg = tmp / "repo", tmp / "config"
    (cfg / "markets").mkdir(parents=True)
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
    for name in ("events.yaml", "settings.yaml", "ranges.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    for kind, rows in DATA.items():
        path = root / "data" / MARKET / kind / "2026" / "10" / "2026-10-01.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return root, cfg


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(path)).encode() + f.read_bytes())
    return h.hexdigest()


def run(root: Path, cfg: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if not k.startswith("NEO4J_")}
    full_env = {**base, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET,
                "NEO4J_RETRY_BACKOFF": "0", **(env or {})}
    return subprocess.run([sys.executable, str(SCRIPTS / "neo4j_sync.py"), *args], cwd=SCRIPTS, env=full_env,
                          capture_output=True, text=True, check=False)


# ---------- fake Query API v2 ----------

class FakeNeo4j:
    """Records every request; answers like the Query API v2 (202 + data/counters). Keeps SyncState
    watermarks so incremental runs behave as against a real server."""

    def __init__(self, fail_on: str | None = None, status: int = 202):
        self.requests: list[dict] = []
        self.marks: dict[str, str] = {}
        self.fail_on, self.status = fail_on, status
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), **body})
                code, out = fake.answer(body["statement"], body.get("parameters") or {})
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, stmt: str, params: dict) -> tuple[int, dict]:
        if self.fail_on and self.fail_on in stmt:
            if self.status == 401:
                return 401, {"errors": [{"code": "Neo.ClientError.Security.Unauthorized",
                                         "message": f"bad credentials for {USER}"}]}
            return self.status, {"errors": [{"code": "Neo.TransientError.General", "message": "boom"}]}
        values = []
        if "RETURN s.kind AS kind" in stmt:
            values = [[k.split(":", 1)[1], w] for k, w in self.marks.items() if k.startswith(params["market"] + ":")]
        elif "SET s.market = $market, s.kind = $kind, s.watermark" in stmt:
            self.marks[params["id"]] = params["watermark"]
        elif "DETACH DELETE" in stmt:
            values = [[0]]
        return 202, {"data": {"fields": [], "values": values}, "counters": {"nodesCreated": 0}}

    def writes(self) -> list[dict]:
        return [r for r in self.requests if "$rows" in r["statement"]]

    def rows(self, kind: str) -> list[dict]:
        return [row for r in self.writes() if r["parameters"]["kind"] == kind for row in r["parameters"]["rows"]]

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake():
    f = FakeNeo4j()
    yield f
    f.close()


def env_for(f: FakeNeo4j, **extra) -> dict:
    return {"NEO4J_QUERY_URL": f.url, "NEO4J_USER": USER, "NEO4J_PASSWORD": PASSWORD,
            "NEO4J_DATABASE": "testdb", **extra}


# ---------- tests ----------

def test_default_database_is_first_host_label(monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    import neo4j_sync
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    assert neo4j_sync.default_database("neo4j+s://4132bc90.databases.neo4j.io") == "4132bc90"
    assert neo4j_sync.default_database("neo4j+s://4132bc90.databases.neo4j.io:7687") == "4132bc90"
    assert neo4j_sync.default_database("http://127.0.0.1:7474") == "neo4j"
    assert neo4j_sync.default_database("bolt://localhost:7687") == "neo4j"
    monkeypatch.setenv("NEO4J_DATABASE", "override")
    assert neo4j_sync.default_database("neo4j+s://4132bc90.databases.neo4j.io") == "override"
    monkeypatch.delenv("NEO4J_DATABASE")
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://4132bc90.databases.neo4j.io")
    monkeypatch.setenv("NEO4J_PASSWORD", PASSWORD)
    monkeypatch.delenv("NEO4J_QUERY_URL", raising=False)
    c = neo4j_sync.client_from_env()
    assert c.url == "https://4132bc90.databases.neo4j.io/db/4132bc90/query/v2"
    assert c.host == "4132bc90.databases.neo4j.io"


def test_dry_run_statements_are_static_and_parameterised(tmp_path):
    root, cfg = setup(tmp_path)
    before = tree_hash(root / "data")
    res = run(root, cfg, "--dry-run", env={"NEO4J_PASSWORD": PASSWORD})
    assert res.returncode == 0, res.stderr + res.stdout
    out = json.loads(res.stdout)
    assert out["ok"] and out["dry_run"]
    files = sorted((root / "work" / "neo4j_dryrun" / MARKET).glob("*.json"))
    assert len(files) == out["statements"] > 20
    all_params = ""
    for f in files:
        doc = json.loads(f.read_text())
        stmt, params = doc["statement"], doc["parameters"]
        all_params += json.dumps(params)
        for s in SENTINELS:
            assert s not in stmt, (f.name, s)
        for a, b in ("()", "[]", "{}"):
            assert stmt.count(a) == stmt.count(b), (f.name, a)
        assert stmt.count("'") % 2 == 0 and '"' not in stmt, f.name
        for name in set(re.findall(r"\$(\w+)", stmt)):
            assert name in params, (f.name, name)
        if not stmt.startswith(("CREATE CONSTRAINT", "CREATE INDEX")):
            assert not re.search(r"(?<!ON )\bCREATE\b", stmt), f.name   # writes are MERGE only (idempotent)
        if "$rows" in stmt:
            assert stmt.startswith("UNWIND $rows AS row")
            for row in params["rows"]:
                assert "source_id" in row and "recorded_at" in row, (f.name, row)
    for s in SENTINELS:
        assert s in all_params, s
    assert PASSWORD not in res.stdout + res.stderr + all_params
    assert tree_hash(root / "data") == before                      # data/ untouched
    kinds = out["kinds"]
    assert kinds["news"]["rows_read"] == 2 and kinds["graph"]["rows_read"] == 3
    assert all(k["failed"] == 0 for k in kinds.values())


def test_sync_sends_authenticated_batches_and_handles_corrections(tmp_path, fake):
    root, cfg = setup(tmp_path)
    before = tree_hash(root / "data")
    res = run(root, cfg, env=env_for(fake))
    assert res.returncode == 0, res.stderr + res.stdout
    out = json.loads(res.stdout)
    assert out["ok"] and out["host"] == "127.0.0.1" and out["database"] == "testdb"
    expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    assert fake.requests and all(r["auth"] == expected for r in fake.requests)
    assert all(r["path"] == "/db/testdb/query/v2" for r in fake.requests)
    assert any(r["statement"].startswith("CREATE CONSTRAINT") for r in fake.requests)
    for kind in ("news", "insiders", "deals", "graph", "predictions", "regime", "features"):
        assert out["kinds"][kind]["upserted"] == out["kinds"][kind]["rows_read"] > 0, kind

    news = {r["id"]: r for r in fake.rows("news")}
    assert news[f"{MARKET}:n1"]["props"]["sentiment"] == 0.7           # newer news_enriched row wins
    assert news[f"{MARKET}:n1"]["mentions"]["materiality"] == "medium"
    assert news[f"{MARKET}:n2"]["tickers"] == ["AAA", "BBB"]
    regime = fake.rows("regime")
    assert len(regime) == 1 and regime[0]["props"]["regime"] == "TRENDING"
    graph = {r["source_id"]: r for r in fake.rows("graph")}
    assert graph["BBB|competitor|delta"]["status"] == "removed"
    removed = [r for r in fake.writes() if r["parameters"]["kind"] == "graph"
               and r["statement"].rstrip().endswith("DELETE old")]
    assert [row["source_id"] for r in removed for row in r["parameters"]["rows"]] == ["BBB|competitor|delta"]
    assert graph["AAA|supplier|gamma-corp"]["target_id"] == f"{MARKET}:CCC"
    assert graph["AAA|board|john-smith"]["target_id"] == f"{MARKET}:name:john-smith"
    current = fake.rows("events_current")[0]["ids"]
    assert current == ["AAA-earnings-2026-10-04"]                         # the moved date replaced the old one
    pred = fake.rows("predictions")[0]
    assert [e["record_id"] for e in pred["evidence"]] == ["n1", "0000-26-000001", "not-synced-yet"]
    ins = {r["source_id"]: r for r in fake.rows("insiders")}
    assert ins["acc1-1"]["holder_id"] == f"{MARKET}:cik:0001" and ins["acc1-1"]["props"]["side"] == "sell"
    assert ins["acc1-1"]["holder_person"] is True
    assert ins["pit-1"]["holder_id"] == f"{MARKET}:name:promoter-co" and ins["pit-1"]["props"]["side"] == "sell"
    h13 = fake.rows("holdings_13f")
    assert [(r["props"]["action"], r["props"]["shares"]) for r in sorted(h13, key=lambda r: r["props"]["period"])] \
        == [("first", 100.0), ("add", 150.0)]
    assert fake.rows("stakes")[0]["props"]["reporting_persons"] == ["Activist LP"]   # nulls dropped from lists
    assert fake.rows("shareholding")[0]["holder_id"] == f"{MARKET}:promoters:CCC"
    assert PASSWORD not in res.stdout + res.stderr
    assert tree_hash(root / "data") == before


def test_rerun_is_idempotent_and_incremental(tmp_path, fake):
    root, cfg = setup(tmp_path)
    assert run(root, cfg, env=env_for(fake)).returncode == 0
    first = [(r["statement"], json.dumps([{k: v for k, v in row.items()} for row in r["parameters"]["rows"]],
                                          sort_keys=True)) for r in fake.writes()]
    assert fake.marks.get(f"{MARKET}:news") == T2
    fake.requests.clear()
    res = run(root, cfg, env=env_for(fake))
    assert res.returncode == 0, res.stdout
    out = json.loads(res.stdout)
    assert out["kinds"]["news"]["since"] == T2
    # the 3-day overlap re-reads the same rows; the statements and rows are identical, so MERGE changes nothing
    second = [(r["statement"], json.dumps([{k: v for k, v in row.items()} for row in r["parameters"]["rows"]],
                                           sort_keys=True)) for r in fake.writes()]
    assert second == first
    # a watermark beyond the overlap skips the old rows of incremental kinds but still sends derived kinds
    fake.requests.clear()
    out = json.loads(run(root, cfg, "--since", "2026-12-01T00:00:00+00:00", env=env_for(fake)).stdout)
    assert out["kinds"]["news"]["rows_read"] == 0 and out["kinds"]["holdings_13f"]["rows_read"] == 2
    assert not fake.rows("news")


def test_full_deletes_market_then_reloads(tmp_path, fake):
    root, cfg = setup(tmp_path)
    out = json.loads(run(root, cfg, "--full", env=env_for(fake)).stdout)
    assert out["mode"] == "full" and out["ok"]
    stmts = [r["statement"] for r in fake.requests]
    first_write = next(i for i, s in enumerate(stmts) if "$rows" in s)
    delete = next(i for i, s in enumerate(stmts) if "DETACH DELETE" in s)
    assert delete < first_write
    assert fake.requests[delete]["parameters"]["market"] == MARKET
    assert not any("RETURN s.kind AS kind" in s for s in stmts)        # full ignores watermarks


@pytest.mark.parametrize("status", [401, 500])
def test_failure_exits_nonzero_and_never_prints_password(tmp_path, status):
    root, cfg = setup(tmp_path)
    f = FakeNeo4j(fail_on="MENTIONS" if status == 500 else "CREATE CONSTRAINT", status=status)
    try:
        res = run(root, cfg, env=env_for(f))
    finally:
        f.close()
    assert res.returncode == 1
    out = json.loads(res.stdout)
    assert out["ok"] is False
    if status == 500:
        assert out["kinds"]["news"]["failed"] == 2 and "boom" in out["kinds"]["news"]["error"]
        assert out["kinds"]["events"]["failed"] == 0                       # other kinds still synced
        assert sum("MENTIONS" in r["statement"] for r in f.requests) == 3  # two retries on a 5xx
        assert f"{MARKET}:news" not in f.marks                             # watermark not advanced
    else:
        assert "401" in out["error"] and not out["kinds"]
    assert PASSWORD not in res.stdout + res.stderr
    assert base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode() not in res.stdout + res.stderr


def test_unreachable_host_and_unset_uri(tmp_path):
    root, cfg = setup(tmp_path)
    res = run(root, cfg, env={"NEO4J_QUERY_URL": "http://127.0.0.1:9", "NEO4J_PASSWORD": PASSWORD})
    assert res.returncode == 1 and "connection failed" in json.loads(res.stdout)["error"]
    assert PASSWORD not in res.stdout + res.stderr
    res = run(root, cfg)
    assert res.returncode == 2 and json.loads(res.stdout)["reason"] == "NEO4J_URI not set"


def test_probe(tmp_path, fake):
    root, cfg = setup(tmp_path)
    res = run(root, cfg, "--probe", env=env_for(fake))
    assert res.returncode == 0 and json.loads(res.stdout)["ok"]
    assert [r["statement"] for r in fake.requests] == ["RETURN 1 AS ok"]


# ---------- optional: a real Neo4j 5 engine (never the user's instance) ----------

def _query(url: str, auth: str, stmt: str) -> list:
    req = urllib.request.Request(f"{url}/db/neo4j/query/v2", data=json.dumps({"statement": stmt}).encode(),
                                 headers={"Authorization": auth, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["data"]["values"]


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("NEO4J_TEST_QUERY_URL"), reason="set NEO4J_TEST_QUERY_URL to a disposable server")
def test_real_engine_full_then_idempotent_incremental(tmp_path):
    url = os.environ["NEO4J_TEST_QUERY_URL"]
    user, pw = os.environ.get("NEO4J_TEST_USER", "neo4j"), os.environ.get("NEO4J_TEST_PASSWORD", "")
    auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    env = {"NEO4J_QUERY_URL": url, "NEO4J_USER": user, "NEO4J_PASSWORD": pw, "NEO4J_DATABASE": "neo4j"}
    root, cfg = setup(tmp_path)
    full = run(root, cfg, "--full", env=env)
    assert full.returncode == 0, full.stdout + full.stderr
    count = "MATCH (n) WHERE n.market = 'neomkt' RETURN count(n)"
    rels = "MATCH (a)-[r]->() WHERE r.market = 'neomkt' RETURN count(r)"
    n0, r0 = _query(url, auth, count)[0][0], _query(url, auth, rels)[0][0]
    for _ in range(2):
        out = run(root, cfg, env=env)
        assert out.returncode == 0, out.stdout
        c = json.loads(out.stdout)["counters"]
        assert c.get("nodesCreated", 0) == 0 and c.get("relationshipsCreated", 0) == 0, c
    assert (_query(url, auth, count)[0][0], _query(url, auth, rels)[0][0]) == (n0, r0)
    assert _query(url, auth, "MATCH (:NewsItem {id: 'neomkt:n1'})-[m:MENTIONS]->(:Company {id: 'neomkt:AAA'}) "
                             "RETURN m.sentiment")[0][0] == 0.7
    assert _query(url, auth, "MATCH (r:RegimeDay {id: 'neomkt:2026-10-01'}) RETURN r.regime")[0][0] == "TRENDING"
    assert _query(url, auth, "MATCH ()-[r:CONNECTED_TO]->() WHERE r.market = 'neomkt' RETURN count(r)")[0][0] == 2
    assert _query(url, auth, "MATCH (e:Event) WHERE e.market = 'neomkt' AND e.current RETURN e.record_id "
                             "ORDER BY e.record_id") == [["AAA-earnings-2026-10-04"], ["fomc-2026-10-02"]]
    assert _query(url, auth, "MATCH (:Prediction {id: 'neomkt:2026-10-01-AAA-1d'})-[:CITES]->(s:Source) "
                             "RETURN s.record_id, s.placeholder ORDER BY s.record_id") == [
        ["0000-26-000001", False], ["n1", False], ["not-synced-yet", True]]
