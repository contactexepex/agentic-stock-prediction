"""Offline tests for the SEC XBRL fundamentals collector (collect_fundamentals.py), its views
and the context pack's Fundamentals section. Company facts come from tests/fixtures/sec
(real data.sec.gov responses trimmed to the collected tags and recent periods; provenance in
tests/fixtures/sec/README.md) through MB_SEC_FIXTURES. Submission lists and the ticker map are
generated here (real CIKs and accession numbers; filing dates of the "new" filing are moved to
yesterday so the recheck window and the freshness flag see it).
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
FIX = REPO / "tests" / "fixtures" / "sec"
MARKET = "testfund"
sys.path.insert(0, str(SCRIPTS))

import collect_fundamentals as cf  # noqa: E402

MARKET_YAML = """
market: testfund
name: Test fundamentals market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  BENCH: {role: benchmark, name: Benchmark}
  VOLX: {role: vol_index, name: Vol index}
regime: {unstable_vol: 28, event_vol: 20, calm_vol: 16, unstable_bench_vol: 0.25,
         trend_return_5d: 0.015, flat_return_5d: 0.005, stress_vol_jump: 0.30}
sectors:
  Mixed: [AAPL, BAC, XOM]
tickers:
  AAPL: {name: Apple}
  BAC: {name: Bank of America}
  XOM: {name: ExxonMobil}
filings: sec
fundamentals:
  history_years: 10
  recheck_days: 10
  predecessor_ciks: {XOM: [34088]}
"""
NOSEC_YAML = """
market: nosec
name: No SEC market
calendar: XBOM
timezone: Asia/Kolkata
currency: INR
symbols:
  BENCH: {role: benchmark, name: Benchmark}
tickers:
  RELIANCE: {name: Reliance}
"""

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = str(TODAY - timedelta(days=1))
CIKS = {"AAPL": 320193, "BAC": 70858, "XOM": 2115436}
NEW_ACC = "0000320193-26-000020"          # Apple 10-Q for the quarter ended 2026-06-27
PRED_NEW_ACC = "0000034088-26-000200"     # synthetic: a 10-Q listed only under XOM's predecessor CIK
# Periodic filings in the fixtures (accession, form, filing date, report date), as listed by SEC.
PERIODIC = {
    "AAPL": [("0000320193-26-000013", "10-Q", "2026-05-01", "2026-03-28"),
             ("0000320193-26-000006", "10-Q", "2026-01-30", "2025-12-27"),
             ("0000320193-25-000079", "10-K", "2025-10-31", "2025-09-27"),
             ("0000320193-25-000073", "10-Q", "2025-08-01", "2025-06-28")],
    "BAC": [("0000070858-26-000394", "10-Q", "2026-07-31", "2026-06-30"),
            ("0000070858-26-000249", "10-Q", "2026-05-01", "2026-03-31")],
    "XOM": [("0000034088-26-000093", "10-Q", "2026-08-03", "2026-06-30")],
}


def run(script: str, root: Path, cfg: Path, *args: str, market: str = MARKET) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": market,
           "MB_SEC_FIXTURES": str(root.parent / "sec"), "SEC_USER_AGENT": "market-brief tests test@example.com"}
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, check=False)


def submissions(filings: list[tuple]) -> dict:
    cols = ["accessionNumber", "form", "filingDate", "reportDate"]
    recent = {c: [f[i] for f in filings] for i, c in enumerate(cols)}
    recent["primaryDocument"] = ["doc.htm"] * len(filings)
    recent["acceptanceDateTime"] = [f"{f[2]}T20:30:00.000Z" for f in filings]
    return {"name": "x", "filings": {"recent": recent}}


def aapl_facts(with_new: bool) -> dict:
    """The AAPL fixture before the 10-Q was filed (its facts removed), or with its filed date moved
    to yesterday."""
    doc = json.loads((FIX / "companyfacts_aapl.json").read_text())
    for ns in doc["facts"].values():
        for tag in ns.values():
            for unit, facts in tag["units"].items():
                tag["units"][unit] = [{**f, "filed": YESTERDAY} if f["accn"] == NEW_ACC else f
                                      for f in facts if with_new or f["accn"] != NEW_ACC]
    return doc


def setup(tmp: Path, day: int = 1) -> tuple[Path, Path]:
    """Fixture world on day 1 (Apple's latest 10-Q not filed yet) or day 2 (filed yesterday)."""
    root, cfg, fx = tmp / "repo", tmp / "config", tmp / "sec"
    for d in (root / "data", cfg / "markets", fx):
        d.mkdir(parents=True, exist_ok=True)
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
    (cfg / "markets" / "nosec.yaml").write_text(NOSEC_YAML)
    (cfg / "events.yaml").write_text((REPO / "config" / "events.yaml").read_text().replace("[us]", "[us, testfund]"))
    for name in ("ranges.yaml", "settings.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    # hand-made ticker map with the real CIKs
    (fx / "tickers.json").write_text(json.dumps({str(i): {"cik_str": c, "ticker": t, "title": t}
                                                 for i, (t, c) in enumerate(CIKS.items())}))
    urls = {"https://www.sec.gov/files/company_tickers.json": "tickers.json"}
    for t, cik in CIKS.items():
        filings = list(PERIODIC[t])
        if t == "AAPL" and day == 2:
            filings.insert(0, (NEW_ACC, "10-Q", YESTERDAY, "2026-06-27"))
        filings.append((f"{cik:010d}-26-999999", "8-K", YESTERDAY, ""))          # ignored form
        (fx / f"sub_{t}.json").write_text(json.dumps(submissions(filings)))
        urls[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = f"sub_{t}.json"
    # XOM's predecessor registrant (predecessor_ciks): its own submission list, which also lists the
    # Q2 10-Q (a joint filing, kept once) and a 10-Q for Q3 on day 3 (filed under 34088 only)
    pred = list(PERIODIC["XOM"]) + [("0000034088-26-999998", "8-K", YESTERDAY, "")]
    if day == 3:
        pred.insert(0, (PRED_NEW_ACC, "10-Q", YESTERDAY, "2026-09-30"))
    (fx / "sub_XOM_34088.json").write_text(json.dumps(submissions(pred)))
    urls["https://data.sec.gov/submissions/CIK0000034088.json"] = "sub_XOM_34088.json"
    (fx / "facts_aapl.json").write_text(json.dumps(aapl_facts(with_new=day == 2)))
    urls[cf.facts_url(320193)] = "facts_aapl.json"
    urls[cf.facts_url(70858)] = str(FIX / "companyfacts_bac.json")
    urls[cf.facts_url(2115436)] = str(FIX / "companyfacts_xom_holdings.json")
    urls[cf.facts_url(34088)] = str(FIX / "companyfacts_xom_34088.json")
    (fx / "urls.json").write_text(json.dumps(urls, indent=1))
    return root, cfg


def rows(root: Path) -> list[dict]:
    return [json.loads(x) for f in (root / "data" / MARKET / "fundamentals").glob("**/*.jsonl")
            for x in f.read_text().splitlines()]


def connect(root: Path, monkeypatch):
    import common
    from marketbrief.core.database import connect
    monkeypatch.setattr(common, "ROOT", root)
    return connect(MARKET)


# ---------- pure functions ----------

def test_period_kind_and_fiscal_labels():
    assert cf.period_kind(None, "2026-06-27") == "instant"
    assert cf.period_kind("2026-03-29", "2026-06-27") == "quarter"            # 13 weeks
    assert cf.period_kind("2025-05-12", "2025-08-31") == "quarter"            # Costco's 16-week Q4
    assert cf.period_kind("2025-09-28", "2026-03-28") == "ytd"                # 26 weeks
    assert cf.period_kind("2024-09-29", "2025-09-27") == "annual"             # 52 weeks
    assert cf.period_kind("2026-06-01", "2026-06-27") is None                 # stub period

    facts = [  # one 10-Q (Q3) and one 10-K, as in company facts: fy/fp describe the filing
        {"start": "2025-09-28", "end": "2026-06-27", "accession": "q3", "fy": 2026, "fp": "Q3", "filing_date": "2026-07-31"},
        {"start": "2025-06-29", "end": "2025-09-27", "accession": "k", "fy": 2025, "fp": "FY", "filing_date": "2025-10-31"},
        {"start": "2024-09-29", "end": "2025-09-27", "accession": "k", "fy": 2025, "fp": "FY", "filing_date": "2025-10-31"},
        {"start": "2023-10-01", "end": "2024-09-28", "accession": "k", "fy": 2025, "fp": "FY", "filing_date": "2025-10-31"},
    ]
    by_accn, by_end = cf.report_periods(facts)
    assert by_accn["k"] == ("2025-09-27", 2025, "FY") and by_end["2026-06-27"] == (2026, "Q3")

    def label(kind, start, end, acc):
        return cf.fiscal_label(kind, {"start": start, "end": end, "accession": acc}, by_accn, by_end)
    assert label("ytd", "2025-09-28", "2026-06-27", "q3") == (2026, "9M")
    assert label("quarter", "2025-06-29", "2025-09-27", "k") == (2025, "Q4")
    assert label("annual", "2024-09-29", "2025-09-27", "k") == (2025, "FY")
    assert label("annual", "2023-10-01", "2024-09-28", "k") == (2024, "FY")       # a year before a known end
    assert label("instant", None, "2026-07-17", "q3") == (2026, "Q3")             # cover-page share count


def test_fiscal_label_from_the_period_not_the_filing():
    """Hand-made: a 10-Q/A for the same period carries a different fy than the original 10-Q
    (filers do mis-tag DocumentFiscalYearFocus). The period's label comes from the earliest
    filing for it, and a comparative fact in a later filing keeps its own period's label."""
    base = {"concept": "revenue", "tag": "us-gaap:Revenues", "tag_rank": 0, "unit": "USD", "cik": "1"}
    facts = [
        {**base, "start": "2025-04-01", "end": "2025-06-30", "value": 10, "accession": "orig", "form": "10-Q",
         "filing_date": "2025-08-01", "fy": 2025, "fp": "Q2"},
        {**base, "start": "2025-04-01", "end": "2025-06-30", "value": 11, "accession": "amend", "form": "10-Q/A",
         "filing_date": "2025-09-15", "fy": 2026, "fp": "Q2"},
        # next year's 10-Q: its own quarter and the year-ago comparative (restated to 12)
        {**base, "start": "2026-04-01", "end": "2026-06-30", "value": 20, "accession": "next", "form": "10-Q",
         "filing_date": "2026-08-01", "fy": 2026, "fp": "Q2"},
        {**base, "start": "2025-04-01", "end": "2025-06-30", "value": 12, "accession": "next", "form": "10-Q",
         "filing_date": "2026-08-01", "fy": 2026, "fp": "Q2"},
    ]
    by_accn, by_end = cf.report_periods(facts)
    assert by_end == {"2025-06-30": (2025, "Q2"), "2026-06-30": (2026, "Q2")}
    got = {(r["accession"], r["period_end"]): (r["fiscal_year"], r["fiscal_period"], r["prev_value"])
           for r in cf.new_rows("T", facts, set(), "2020-01-01", {}, "now")}
    assert got == {("orig", "2025-06-30"): (2025, "Q2", None), ("amend", "2025-06-30"): (2025, "Q2", 10),
                   ("next", "2025-06-30"): (2025, "Q2", 11), ("next", "2026-06-30"): (2026, "Q2", None)}


def test_restatement_rows_and_dedupe():
    """Real Bank of America restatement: Q2 2025 revenue 26,463m in the 2025 10-Q and 27,443m as the
    comparative in the 2026 10-Q. An unchanged comparative adds no row."""
    doc = json.loads((FIX / "companyfacts_bac.json").read_text())
    facts = cf.extract(doc, 70858)
    ids: set[str] = set()
    got = cf.new_rows("BAC", facts, ids, "2020-01-01", {}, "2026-10-05T00:00:00+00:00")
    q2 = [r for r in got if r["tag"] == "us-gaap:Revenues" and r["period_start"] == "2025-04-01" and r["period_end"] == "2025-06-30"]
    assert [(r["value"], r["prev_value"], r["accession"]) for r in q2] == [
        (26463000000, None, "0000070858-25-000268"), (27443000000, 26463000000, "0000070858-26-000394")]
    assert q2[0]["fiscal_year"] == 2025 and q2[0]["fiscal_period"] == "Q2" and q2[0]["period"] == "quarter"
    # the restating 2026 10-Q is fy 2026 / fp Q2 in company facts; the comparative keeps its own period's label
    sec_label = {(f["accession"], f["fy"], f["fp"]) for f in facts if f["accession"] == "0000070858-26-000394"}
    assert sec_label == {("0000070858-26-000394", 2026, "Q2")}
    assert (q2[1]["fiscal_year"], q2[1]["fiscal_period"]) == (2025, "Q2")
    restating = [r for r in got if r["accession"] == "0000070858-26-000394"]
    assert {(r["fiscal_year"], r["fiscal_period"]) for r in restating if r["period_end"] < "2026-01-01"} == {(2025, "Q2"), (2025, "H1")}
    assert {(r["fiscal_year"], r["fiscal_period"]) for r in restating if r["period_end"] >= "2026-01-01"} == {(2026, "Q2"), (2026, "H1")}
    # Q1 2025 diluted EPS: 0.90 as filed, 0.89 as restated a year later
    q1 = [r for r in got if r["concept"] == "eps_diluted" and r["period_start"] == "2025-01-01" and r["period"] == "quarter"]
    assert [(r["value"], r["prev_value"]) for r in q1] == [(0.9, None), (0.89, 0.9)]
    assert [(r["fiscal_year"], r["fiscal_period"], r["accession"]) for r in q1] == [
        (2025, "Q1", "0000070858-25-000200"), (2025, "Q1", "0000070858-26-000249")]   # the latter filing is fy 2026
    assert all(r["id"] in ids for r in got)
    assert cf.new_rows("BAC", facts, ids, "2020-01-01", {}, "now") == []      # stored ids: nothing new


# ---------- collector end to end (fixtures) ----------

def test_collect_gate_new_filing_and_views(tmp_path, monkeypatch):
    root, cfg = setup(tmp_path, day=1)
    r = run("collect_fundamentals.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["loaded"] == ["AAPL", "BAC", "XOM"] and out["failed"] == [] and out["new_filings"] == []
    assert out["requests"] == 1 + 4 + 4       # ticker map, 4 submissions and 4 company facts (XOM x2 each)
    day1 = rows(root)
    assert out["new_rows"] == len(day1) > 0
    assert not any(x["accession"] == NEW_ACC for x in day1)
    assert {x["cik"] for x in day1 if x["ticker"] == "XOM"} == {"2115436", "34088"}
    assert all(x["fiscal_year"] and x["fiscal_period"] for x in day1)
    assert {x["accepted_at"] for x in day1 if x["accession"] == "0000320193-26-000013"} == {"2026-05-01T20:30:00.000Z"}

    again = json.loads(run("collect_fundamentals.py", root, cfg).stdout)       # nothing new filed
    assert (again["new_rows"], again["loaded"], again["up_to_date"], again["requests"]) == (0, [], 3, 5)

    setup(tmp_path, day=2)                                                        # Apple files its 10-Q
    r2 = json.loads(run("collect_fundamentals.py", root, cfg).stdout)
    assert r2["loaded"] == ["AAPL"] and r2["up_to_date"] == 2
    assert [f["accession"] for f in r2["new_filings"]] == [NEW_ACC]
    new = [x for x in rows(root) if x not in day1]
    assert len(new) == r2["new_rows"] and {x["accession"] for x in new} == {NEW_ACC}
    rev = next(x for x in new if x["tag"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
               and x["period"] == "quarter" and x["period_end"] == "2026-06-27")
    assert (rev["value"], rev["fiscal_year"], rev["fiscal_period"], rev["form"]) == (109417000000, 2026, "Q3", "10-Q")
    # comparatives repeated unchanged in the new 10-Q (e.g. Q3 FY2025 revenue) added nothing
    assert not any(x["period_end"] == "2025-06-28" and x["concept"] == "revenue" for x in new)
    final = json.loads(run("collect_fundamentals.py", root, cfg, "--force").stdout)
    assert final["new_rows"] == 0 and final["loaded"] == ["AAPL", "BAC", "XOM"]

    con = connect(root, monkeypatch)
    m = con.execute("""SELECT fiscal_year, fiscal_period, revenue, eps_diluted, revenue_yoy, net_income_yoy, eps_yoy,
                              gross_margin, operating_margin, fcf, derived
                       FROM fundamentals_metrics WHERE ticker = 'AAPL' AND period_end = '2026-06-27'""").fetchone()
    # Apple 10-Q, quarter ended 2026-06-27: net sales 109,417m (94,036m a year earlier), diluted EPS 2.02 (1.57)
    assert m[:4] == (2026, "Q3", 109417000000, 2.02)
    assert m[4] == round(109417 / 94036 - 1, 4) and m[6] == round(2.02 / 1.57 - 1, 4)
    assert m[7] == round(54770 / 109417, 4) and m[10] is False
    # free cash flow: Q3 operating cash flow and capex derived as 9M - H1 (10-Qs report cash flows year to date)
    assert m[9] == (116996000000 - 82627000000) - (6799000000 - 4344000000)
    q4 = con.execute("""SELECT concept, value, derived, derived_from, fiscal_period FROM fundamentals_quarterly
                        WHERE ticker = 'AAPL' AND period_end = '2025-09-27' AND concept IN ('revenue', 'eps_diluted')
                        ORDER BY concept""").fetchall()
    # FY2025 416,161m - 9M 313,695m = Q4 102,466m (Apple's Q4 release: 102,466m; its EPS 1.85 vs derived 1.84)
    assert q4 == [("eps_diluted", 1.84, True, "FY - 9M", "Q4"), ("revenue", 102466000000, True, "FY - 9M", "Q4")]
    bac = con.execute("""SELECT value, prev_value, revised, first_filed FROM fundamentals_latest WHERE ticker = 'BAC'
                         AND concept = 'revenue' AND period = 'quarter' AND period_end = '2025-06-30'""").fetchone()
    assert bac == (27443000000, 26463000000, True, date(2025, 7, 31))
    # point in time: before the restating 10-Q was accepted (2026-07-31 20:30 UTC) the original value holds
    asof = """SELECT value FROM fundamentals_latest_asof(TIMESTAMPTZ '{}') WHERE ticker = 'BAC'
               AND concept = 'revenue' AND period = 'quarter' AND period_end = '2025-06-30'"""
    assert con.execute(asof.format("2026-07-31 20:00:00+00")).fetchone() == (26463000000,)
    assert con.execute(asof.format("2026-07-31 21:00:00+00")).fetchone() == (27443000000,)
    before = con.execute("""SELECT max(period_end) FROM fundamentals_metrics_asof(TIMESTAMPTZ '2026-07-01 00:00:00+00')
                            WHERE ticker = 'AAPL'""").fetchone()
    assert before == (date(2026, 3, 28),)                       # the June quarter's 10-Q was not filed yet
    # no acceptance time (XOM's predecessor filings): known at the end of the filing date (UTC)
    assert con.execute("""SELECT DISTINCT known_at FROM fundamentals_latest WHERE accession = '0000034088-26-000067'"""
                       ).fetchall() == [(datetime(2026, 5, 5, tzinfo=timezone.utc),)]
    xom = con.execute("""SELECT revenue, revenue_yoy, yoy_period_end FROM fundamentals_metrics
                         WHERE ticker = 'XOM' AND period_end = '2026-06-30'""").fetchone()
    assert xom[0] == 116017000000 and xom[1] == round(116017 / 81506 - 1, 4)  # a year ago from the predecessor CIK
    bal = con.execute("""SELECT cash, total_debt, debt_basis FROM fundamentals_balance
                         WHERE ticker = 'AAPL' AND period_end = '2026-06-27'""").fetchone()
    assert bal == (39544000000, 71340000000 + 11007000000 + 1997000000, "noncurrent + current LTD + short-term")
    latest = {t: (form, str(fd), fy, fp) for t, form, fd, fy, fp in con.execute(
        "SELECT ticker, form, filing_date, fiscal_year, fiscal_period FROM fundamentals_latest_report").fetchall()}
    assert latest == {"AAPL": ("10-Q", YESTERDAY, 2026, "Q3"), "BAC": ("10-Q", "2026-07-31", 2026, "Q2"),
                      "XOM": ("10-Q", "2026-08-03", 2026, "Q2")}

    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    text = ctx.stdout.split("## Fundamentals")[1]
    assert f"Filed in the last 5 days: AAPL 10-Q FY2026 Q3 ({YESTERDAY})" in text and "no consensus" in text
    assert f"| AAPL | FY2026 Q3 | 2026-06-27 | 10-Q | {YESTERDAY} | new | 109.42 | 16.4 | 2.02 | 28.7 |" in text
    assert "| BAC | FY2026 Q2 | 2026-06-30 | 10-Q | 2026-07-31 |  | 31.56 |" in text
    assert "| AAPL | 2026-06-27 | 39.54 | 84.34 |" in text
    nosec = run("context.py", root, cfg, market="nosec")
    assert nosec.returncode == 0 and "Fundamentals" not in nosec.stdout


def test_predecessor_cik_filing_triggers_a_reload(tmp_path):
    """Issue #23: a 10-Q listed only under XOM's predecessor CIK (34088) is a new filing for XOM;
    if the predecessor's submission list fails, XOM is reported with that CIK and not loaded."""
    root, cfg = setup(tmp_path, day=1)
    assert run("collect_fundamentals.py", root, cfg).returncode == 0
    setup(tmp_path, day=3)
    out = json.loads(run("collect_fundamentals.py", root, cfg).stdout)
    assert out["loaded"] == ["XOM"] and out["up_to_date"] == 2 and out["failed"] == []
    assert [f["accession"] for f in out["filings_without_new_values"]] == [PRED_NEW_ACC]   # not in the facts fixture
    urls = json.loads((tmp_path / "sec" / "urls.json").read_text())
    del urls["https://data.sec.gov/submissions/CIK0000034088.json"]
    (tmp_path / "sec" / "urls.json").write_text(json.dumps(urls))
    out = json.loads(run("collect_fundamentals.py", root, cfg).stdout)
    assert [(f["ticker"], f["cik"]) for f in out["failed"]] == [("XOM", 34088)]
    assert "XOM" not in out["loaded"] and out["up_to_date"] == 2


def test_skipped_without_sec(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_fundamentals.py", root, cfg, market="nosec")
    assert r.returncode == 0 and "skipped" in json.loads(r.stdout)
    assert not (root / "data" / "nosec").exists()


def test_yoy_needs_the_quarter_a_year_earlier(tmp_path, monkeypatch):
    """Hand-made rows: the year-ago quarter is missing, so the nearest older quarter (15 months
    back) must not be used as the base; with it present, growth is computed."""
    root = tmp_path / "repo"
    path = root / "data" / MARKET / "fundamentals" / "2026" / "10" / "2026-10-05.jsonl"
    path.parent.mkdir(parents=True)
    base = {"cik": "1", "concept": "revenue", "tag": "us-gaap:Revenues", "tag_rank": 0, "unit": "USD",
            "period": "quarter", "form": "10-Q", "accepted_at": None, "prev_value": None,
            "first_seen_at": "2026-10-05T00:00:00+00:00"}
    recs = []
    for t, quarters in {"GAP": [("2024-01-01", "2024-03-31", 100), ("2025-04-01", "2025-06-30", 150)],
                        "FULL": [("2024-04-01", "2024-06-30", 100), ("2025-04-01", "2025-06-30", 150)]}.items():
        for start, end, v in quarters:
            recs.append({**base, "id": f"{t}-{end}", "ticker": t, "period_start": start, "period_end": end,
                         "fiscal_year": int(end[:4]), "fiscal_period": "Q2", "accession": f"{t}-{end}",
                         "filing_date": end, "value": v})
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    con = connect(root, monkeypatch)
    got = dict((t, (y, g)) for t, y, g in con.execute(
        "SELECT ticker, yoy_period_end, revenue_yoy FROM fundamentals_metrics WHERE period_end = '2025-06-30'").fetchall())
    assert got == {"GAP": (None, None), "FULL": (date(2024, 6, 30), 0.5)}
