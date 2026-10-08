"""Offline tests for the NSE collectors on trimmed REAL responses (tests/fixtures/nse/real, fetched
live on 2026-10-05; provenance in tests/fixtures/nse/README) with the real India config:
SEBI PIT XBRL, deal snapshot and per-ticker backfill, shareholding vs pledge-dataset fields,
announcements, Integrated Filing financials (Ind AS, banking, life insurance), FII/DII flows,
delivery %, empty-endpoint warnings, the retry on transient errors and the context sections.
Run: pytest -q"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
REAL = REPO / "tests" / "fixtures" / "nse" / "real"
TODAY = "2026-10-05"


def setup(tmp: Path, tickers: dict | None = None) -> tuple[Path, Path]:
    """Scratch root + a config dir holding the real india.yaml (optionally with other tickers)."""
    root, cfg = tmp / "root", tmp / "config"
    (root / "data").mkdir(parents=True)
    (root / ".scratch-ok").write_text("")
    (cfg / "markets").mkdir(parents=True)
    text = (REPO / "config" / "markets" / "india.yaml").read_text().replace(
        "delivery_lookback_days: 5", "delivery_lookback_days: 6")      # reach the 29-09 fixture
    if tickers:
        import yaml
        doc = yaml.safe_load(text)
        doc["company_meta"], doc["sectors"] = tickers, {"All": list(tickers)}
        text = yaml.safe_dump(doc)
    (cfg / "markets" / "india.yaml").write_text(text)
    for name in ("events.yaml", "settings.yaml", "ranges.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    return root, cfg


def run(script: str, root: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": "india"}
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, check=False)


def replay(script: str, root: Path, cfg: Path, directory: Path = REAL, *args: str) -> dict:
    r = run(script, root, cfg, "--replay", str(directory), "--today", TODAY, "--full", *args)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def rows(root: Path, kind: str) -> list[dict]:
    return [json.loads(line) for f in sorted((root / "data" / "india" / kind).glob("**/*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]


def test_relations_on_real_responses(tmp_path):
    root, cfg = setup(tmp_path)
    out = replay("collect_relations_india.py", root, cfg)
    assert out["new"] == {"insiders": 1, "deals": 0, "holdings": 16}
    assert out["warnings"] == [] and out["requests"] == 0
    assert all(f["error"] == "no replay file" for f in out["failed"])           # tickers without fixtures
    notes = " ".join(out["notes"])
    assert "PIT filings index (14 days): 3 rows returned, 1 for watchlist tickers" in notes
    assert "bulk+block snapshot as on 05-Oct-2026: 5 rows returned, 0 for watchlist tickers" in notes

    (pit,) = rows(root, "insiders")                                              # PIT V2 XBRL, one disclosure
    assert pit["id"] == "nse-pit-INFY-3705-Disclosure1"
    assert (pit["person"], pit["person_category"], pit["transaction"], pit["mode"]) == \
        ("Infosys Employee Benefits Trust", "Trust", "Sell", "Off Market")
    assert (pit["shares"], pit["value"], pit["holding_before_pct"], pit["holding_after_pct"]) == (1100, 1132340, 0.19, 0.19)
    assert (pit["trade_from"], pit["disclosed_at"]) == ("2026-09-23", "2026-09-28T10:04:55+00:00")  # 15:34:55 IST

    h = {(x["ticker"], x["source"], x["period_end"]): x for x in rows(root, "holdings")}
    assert h[("HDFCBANK", "nse_shp", "2026-06-30")]["promoter_pct"] == 0.0     # real 0: no promoter
    hp = h[("HDFCBANK", "nse_pledge", "2026-06-30")]
    assert hp["promoter_pct"] is None and hp["sdd_promoter_pct"] == 13.32     # depository-flagged, kept apart
    assert (h[("INFY", "nse_shp", "2026-06-30")]["promoter_pct"], h[("INFY", "nse_pledge", "2026-06-30")]["sdd_promoter_pct"]) \
        == (13.82, 20.76)
    sp = h[("SUNPHARMA", "nse_pledge", "2026-06-30")]
    assert (sp["pledged_pct_of_promoter"], sp["pledged_pct_of_total"], sp["depository_pledged_pct"],
            sp["promoter_encumbered_shares"]) == (1.65, 0.9, 2.17, 21524530)
    assert h[("RELIANCE", "nse_shp", "2026-06-30")]["promoter_pct"] == 50.48

    # NSE re-stamps the pledge dataset daily: same numbers, new broadcastDt -> no new row
    again_dir = tmp_path / "again"
    shutil.copytree(REAL, again_dir)
    f = again_dir / "corporate-pledgedata_RELIANCE.json"
    f.write_text(f.read_text().replace("05-Oct-2026 16:30:15", "06-Oct-2026 16:30:15"))
    again = replay("collect_relations_india.py", root, cfg, again_dir)
    assert again["new"] == {"insiders": 0, "deals": 0, "holdings": 0}

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "| HDFCBANK | 2026-06-30 | 0.0 |" in ctx.stdout and "Infosys Employee Benefits Trust" in ctx.stdout


def test_deals_backfill_per_ticker(tmp_path):
    root, cfg = setup(tmp_path, {"AARTIPHARM": {"yahoo": "AARTIPHARM.NS", "name": "Aarti Pharmalabs"}})
    out = replay("collect_relations_india.py", root, cfg, REAL, "--only", "deals", "--deals-backfill", "90")
    assert out["new"] == {"deals": 10}                                           # 10 real bulk deals, Aug-Sep 2026
    assert [f["source"] for f in out["failed"]] == ["deals:block:backfill:AARTIPHARM"]   # no fixture
    d = rows(root, "deals")
    assert {x["source"] for x in d} == {"nse_historical"} and {x["deal_type"] for x in d} == {"bulk"}
    assert any(x["date"] == "2026-09-21" and x["client"] == "UNIFI CAPITAL PRIVATE LIMITED" and x["shares"] == 915000
               and x["price"] == 820 for x in d)


def test_nse_primary_sources_on_real_responses(tmp_path):
    root, cfg = setup(tmp_path)
    out = replay("collect_nse_india.py", root, cfg)
    assert out["new"] == {"announcements": 7, "financials": 6, "flows": 2, "delivery": 40}
    assert out["warnings"] == []
    assert all(f["error"] == "no replay file" for f in out["failed"])
    notes = " ".join(out["notes"])
    assert "announcements (2 days): 10 rows returned, 7 for watchlist tickers" in notes
    assert "delivery: file for 2026-10-02 holds 2026-10-01 (holiday)" in notes

    ann = {a["ticker"]: a for a in rows(root, "announcements")}
    assert ann["DRREDDY"]["id"] == "nse-ann-106806305" and ann["DRREDDY"]["category"] == "Action(s) taken or orders passed"
    assert ann["LT"]["url"].startswith("https://nsearchives.nseindia.com/corporate/")

    fin = {(x["ticker"], x["basis"], x["period_type"], x["period_end"]): x for x in rows(root, "financials")}
    q = fin[("INFY", "consolidated", "quarterly", "2026-06-30")]
    assert (q["revenue"], q["net_profit"], q["profit_to_owners"], q["eps_basic"], q["taxonomy"]) == \
        (482110000000, 77750000000, 77690000000, 19.19, "INDAS")
    assert fin[("INFY", "standalone", "quarterly", "2026-06-30")]["eps_basic"] == 17.87
    a = fin[("INFY", "consolidated", "annual", "2026-03-31")]                   # Q4 filing carries the full year
    assert (a["period_start"], a["revenue"], a["eps_basic"]) == ("2025-04-01", 1786500000000, 71.58)
    b = fin[("HDFCBANK", "standalone", "quarterly", "2026-06-30")]
    assert (b["revenue_item"], b["revenue"], b["net_profit"], b["eps_basic"], b["taxonomy"]) == \
        ("InterestEarned", 793627800000, 190597200000, 12.38, "BANKING")
    s = fin[("SBILIFE", "standalone", "quarterly", "2026-06-30")]
    assert (s["revenue_item"], s["revenue"], s["net_profit"], s["eps_basic"], s["taxonomy"]) == \
        ("NetPremiumIncome", 200782091000, 7249331000, 7.22, "LI")

    fl = {x["category"]: x for x in rows(root, "flows")}
    assert (fl["FII/FPI"]["net_cr"], fl["DII"]["net_cr"], fl["DII"]["date"]) == (-4699.14, 5181.62, TODAY)

    dl = {(x["ticker"], x["date"]): x for x in rows(root, "delivery")}
    assert {d for _, d in dl} == {"2026-09-29", "2026-10-01"}
    assert (dl[("INFY", "2026-10-01")]["delivery_pct"], dl[("INFY", "2026-10-01")]["delivery_qty"]) == (51.96, 7881166)

    again = replay("collect_nse_india.py", root, cfg)
    assert set(again["new"].values()) == {0}                                     # append-only, de-duplicated

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    for needle in ("FII/FPI net -4,699 cr, DII net +5,182 cr", "Company announcements on NSE",
                   "| INFY | consolidated | 2026-06-30 | 48211.0 |", "Delivery %", "| INFY | 2026-10-01 | 51.96 |"):
        assert needle in ctx.stdout, needle
    # issue #12: partial data is labelled (one quarter stored: no y/y yet; 2 delivery sessions: 1 in the average)
    results = ctx.stdout.split("## Latest quarterly results")[1].split("\n## ")[0]
    with_results = sorted({x["ticker"] for x in rows(root, "financials")})
    assert f"y/y growth is blank for {len(with_results)} ticker(s)" in results
    tickers = yaml.safe_load((cfg / "markets" / "india.yaml").read_text())["company_meta"]
    pending = [t for t in tickers if t not in with_results]
    assert f"Quarterly results not stored yet for {len(pending)} of" in results and ", ".join(pending) in results
    assert "Shareholding (promoter, public, pledges) not stored yet for" in results
    assert "## Delivery % (latest session vs average of the 1 stored sessions before (up to 20" in ctx.stdout


def test_announcement_enrichment_view_and_context(tmp_path):
    """news_enriched rows keyed by nse-ann- ids reach the announcements_enriched view and the
    context pack (which lists the last 2 days, so the context half uses a row dated now)."""
    from datetime import datetime, timezone
    root, cfg = setup(tmp_path)
    replay("collect_nse_india.py", root, cfg, REAL, "--only", "announcements")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ann = root / "data" / "india" / "announcements" / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d}.jsonl"
    ann.parent.mkdir(parents=True, exist_ok=True)
    with ann.open("a") as f:     # in-test row (not NSE data) so the 2-day context window is time-proof
        f.write(json.dumps({"id": "nse-ann-test-1", "ticker": "LT", "company": "Larsen & Toubro Limited",
                            "published_at": now.isoformat(), "category": "Bagging/Receiving of orders/contracts",
                            "subject": "test order win", "url": None, "source": "test",
                            "first_seen_at": now.isoformat()}) + "\n")
    enr = root / "data" / "india" / "news_enriched" / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d}.jsonl"
    enr.parent.mkdir(parents=True, exist_ok=True)
    base = {"analyzed_at": now.isoformat(), "relevance": 0.9, "novelty": 0.8, "event_type": "legal",
            "urgency": "medium", "geopolitical": False, "priced_in": False, "summary": "s", "prompt_version": "news-v5"}
    enr.write_text(json.dumps({**base, "id": "nse-ann-106806305", "sentiment": -0.4, "materiality": "medium"}) + "\n" +
                   json.dumps({**base, "id": "nse-ann-test-1", "sentiment": 0.6, "materiality": "high"}) + "\n")
    q = ("from marketbrief.core.database import connect; c = connect('india'); "
         "print(c.execute(\"SELECT id, sentiment, materiality FROM "
         "announcements_enriched WHERE id IN ('nse-ann-106806305', 'nse-ann-106806590') ORDER BY id\").fetchall())")
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg)}
    v = subprocess.run([sys.executable, "-c", q], cwd=SCRIPTS, env=env, capture_output=True, text=True)
    assert v.stdout.strip() == "[('nse-ann-106806305', -0.4, 'medium'), ('nse-ann-106806590', None, None)]", v.stderr
    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    assert "| LT |" in ctx.stdout and "| test order win | 0.6 | high | nse-ann-test-1 |" in ctx.stdout


def test_empty_endpoint_is_a_warning_not_a_quiet_day(tmp_path):
    root, cfg = setup(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "corporates-pit-gg.json").write_text('{"data": []}')
    (empty / "snapshot-capital-market-largedeal.json").write_text(
        '{"as_on_date": "05-Oct-2026", "BULK_DEALS_DATA": [], "BLOCK_DEALS_DATA": []}')
    (empty / "corporate-announcements.json").write_text("[]")
    out = replay("collect_relations_india.py", root, cfg, empty, "--only", "insiders", "--only", "deals")
    warn = " ".join(out["warnings"])
    assert "insiders: PIT filings index" in warn and "deals: bulk+block snapshot" in warn
    assert "no rows at all" in warn and out["new"] == {"insiders": 0, "deals": 0}
    out = replay("collect_nse_india.py", root, cfg, empty, "--only", "announcements")
    assert "announcements (2 days): endpoint returned no rows at all" in " ".join(out["warnings"])
    # the real snapshot has rows, none for the watchlist: a note, not a warning
    out = replay("collect_relations_india.py", root, cfg, REAL, "--only", "deals")
    assert out["warnings"] == [] and "0 for watchlist tickers" in " ".join(out["notes"])


def test_transient_error_is_retried_once(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from marketbrief.sources.errors import FetchError
    from marketbrief.sources.nse_client import Nse
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"data": [1]}'

    def flaky(req, timeout=None):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.URLError(OSError("EOF occurred in violation of protocol"))
        return Resp()

    client = Nse(pause=0)
    monkeypatch.setattr(client.opener, "open", flaky)
    client.warmed = True
    assert client.json("fiidiiTradeReact") == {"data": [1]} and len(calls) == 2

    def always_eof(req, timeout=None):
        raise urllib.error.URLError(OSError("EOF occurred in violation of protocol"))
    monkeypatch.setattr(client.opener, "open", always_eof)
    try:
        client.json("fiidiiTradeReact")
    except FetchError as exc:
        assert exc.host is None and "after a retry" in exc.error     # not mistaken for a blocked host
    else:
        raise AssertionError("expected FetchError")


def test_due_tickers_order_and_quarter(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from datetime import date
    from marketbrief.collectors import nse_holdings as cri
    assert cri.latest_quarter_end(date(2026, 10, 5)) == date(2026, 9, 30)
    assert cri.latest_quarter_end(date(2026, 10, 1)) == date(2026, 9, 30)
    assert cri.latest_quarter_end(date(2027, 1, 2)) == date(2026, 12, 31)
    stored = {"A": "2026-06-30", "B": "2026-09-30", "C": "2026-03-31"}        # D, E: nothing stored
    due = cri.due_tickers(stored, ["A", "B", "C", "D", "E"], date(2026, 10, 5), None)
    assert "B" not in due and set(due[:2]) == {"D", "E"} and due[2:] == ["C", "A"]
    assert len(cri.due_tickers(stored, ["A", "B", "C", "D", "E"], date(2026, 10, 5), 2)) == 2


def test_replay_guard_covers_new_collector(tmp_path):
    _, cfg = setup(tmp_path)
    r = run("collect_nse_india.py", REPO, cfg, "--replay", str(REAL), "--today", TODAY)
    assert r.returncode == 2 and "refusing" in json.loads(r.stdout)["error"]
    r = run("collect_nse_india.py", tmp_path / "root", cfg, "--today", TODAY)
    assert r.returncode != 0 and "--today is only allowed with --replay" in r.stderr
