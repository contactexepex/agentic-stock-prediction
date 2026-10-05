"""Offline tests for the SEC relationship collectors (Form 4 insiders, 13D/13G stakes, 13F
holdings), their views, the context pack's Smart money section and the range risk flag.
SEC responses come from tests/fixtures/sec through MB_SEC_FIXTURES: real sec.gov documents
and hand-made ones with fictional filers (provenance of each file in tests/fixtures/sec/README.md).
Submission lists are generated here with dates relative to today, and some fixture URLs are
synthetic (a real document served under another company's folder).
Run: pytest -q"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FIX = REPO / "tests" / "fixtures" / "sec"
MARKET = "testsec"
sys.path.insert(0, str(SCRIPTS))

import collect_holdings as ch  # noqa: E402
import collect_insiders as ci  # noqa: E402
import collect_stakes as cs  # noqa: E402
import smart_money as sm  # noqa: E402

MARKET_YAML = """
market: testsec
name: Test SEC market
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
  AAPL: {name: Apple}
  MSFT: {name: Microsoft}
filings: sec
relationships:
  insiders: {lookback_days: 7}
  stakes: {lookback_days: 7}
  holdings:
    quarters: 2
    filers: {9999200: Example Capital, 9999300: Combo Capital, 9999400: Placeholder Capital,
              9999500: Partial Capital, 9999600: Notice Capital}
    cusips: {AAPL: "037833100", MSFT: ["594918104"]}
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
ARCH = "https://www.sec.gov/Archives/edgar/data"


def run(script: str, root: Path, cfg: Path, *args: str, market: str = MARKET) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": market,
           "MB_SEC_FIXTURES": str(root.parent / "sec"), "SEC_USER_AGENT": "market-brief tests test@example.com"}
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, check=False)


def submissions(name: str, filings: list[tuple]) -> dict:
    cols = ["accessionNumber", "form", "filingDate", "primaryDocument", "reportDate"]
    recent = {c: [f[i] for f in filings] for i, c in enumerate(cols)}
    recent["acceptanceDateTime"] = [f"{f[2]}T21:00:00.000Z" for f in filings]
    recent["primaryDocDescription"] = [f[1] for f in filings]
    return {"name": name, "filings": {"recent": recent}}


def setup(tmp: Path) -> tuple[Path, Path]:
    root, cfg, fx = tmp / "repo", tmp / "config", tmp / "sec"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    fx.mkdir()
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
    (cfg / "markets" / "nosec.yaml").write_text(NOSEC_YAML)
    (cfg / "events.yaml").write_text((REPO / "config" / "events.yaml").read_text().replace("[us]", "[us, testsec]"))
    for name in ("ranges.yaml", "settings.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())

    # fixture trade dates are fixed; move them to recent days so the 30-day windows see them
    recent_trade, recent_ex = str(TODAY - timedelta(days=2)), str(TODAY - timedelta(days=3))
    for src in ("form4_sale.xml", "form4_buy.xml"):
        text = (FIX / src).read_text().replace("2026-09-30", recent_trade).replace("2026-09-29", recent_ex)
        (fx / src).write_text(text)

    d1, old = str(TODAY - timedelta(days=1)), str(TODAY - timedelta(days=30))
    q = ch.quarter_end(TODAY)
    p = ch.quarter_end(q)
    subs = {
        320193: submissions("Apple Inc.", [
            ("0001140361-26-038307", "4", d1, "xslF345X06/form4.xml", ""),
            ("0009999001-26-000001", "4", d1, "xslF345X05/doc4.xml", ""),
            ("0002100119-26-000139", "SCHEDULE 13G", d1, "xslSCHEDULE_13G_X02/primary_doc.xml", ""),
            ("0009999100-26-000001", "SCHEDULE 13D", str(TODAY), "xslSCHEDULE_13D_X02/primary_doc.xml", ""),
            # real JPM 13D/A on another issuer, served under Apple's folder (synthetic URL)
            ("0001193125-26-410213", "SCHEDULE 13D/A", d1, "xslSCHEDULE_13D_X02/primary_doc.xml", ""),
            ("0000320193-26-000050", "SCHEDULE 13G/A", d1, "xslSCHEDULE_13G_X02/primary_doc.xml", ""),  # as investor
            ("0000320193-26-000010", "4", old, "xslF345X06/old.xml", ""),                                 # too old
            ("0000320193-26-000011", "8-K", d1, "a8k.htm", ""),
        ]),
        789019: submissions("MICROSOFT CORP", [("0000789019-26-000001", "8-K", d1, "msft8k.htm", "")]),
        9999200: submissions("EXAMPLE CAPITAL", [
            ("0009999200-26-000003", "13F-HR/A", d1, "xslForm13F_X02/primary_doc.xml", str(q)),  # ignored
            ("0009999200-26-000002", "13F-HR", d1, "xslForm13F_X02/primary_doc.xml", str(q)),
            ("0009999200-26-000001", "13F-HR", old, "xslForm13F_X02/primary_doc.xml", str(p)),
        ]),
        9999300: submissions("COMBO CAPITAL", [("0009999300-26-000001", "13F-HR", d1, "x/primary_doc.xml", str(q))]),
        9999400: submissions("PLACEHOLDER CAPITAL", [("0009999400-26-000001", "13F-HR", d1, "x/primary_doc.xml", str(q))]),
        9999500: submissions("PARTIAL CAPITAL", [("0009999500-26-000001", "13F-HR", d1, "x/primary_doc.xml", str(q))]),
        9999600: submissions("NOTICE CAPITAL", [("0009999600-26-000001", "13F-NT", d1, "x/primary_doc.xml", str(q))]),
    }
    urls = {"https://www.sec.gov/files/company_tickers.json": str(FIX / "company_tickers.json")}
    for cik, body in subs.items():
        (fx / f"sub_{cik}.json").write_text(json.dumps(body))
        urls[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = f"sub_{cik}.json"
    urls.update({
        f"{ARCH}/320193/000114036126038307/form4.xml": "form4_sale.xml",
        f"{ARCH}/320193/000999900126000001/doc4.xml": "form4_buy.xml",
        f"{ARCH}/320193/000210011926000139/primary_doc.xml": str(FIX / "schedule13g.xml"),
        f"{ARCH}/320193/000999910026000001/primary_doc.xml": str(FIX / "schedule13d.xml"),
        f"{ARCH}/320193/000119312526410213/primary_doc.xml": str(FIX / "schedule13d_other_issuer.xml"),
    })
    for folder, cover, table in (
            ("9999200/000999920026000002", "13f_cover.xml", "13f_table_latest.xml"),
            ("9999200/000999920026000001", "13f_cover.xml", "13f_table_previous.xml"),
            ("9999300/000999930026000001", "13f_cover_combination.xml", "13f_table_latest.xml"),
            ("9999400/000999940026000001", "13f_cover_partial.xml", "13f_table_norges_placeholder.xml"),
            ("9999500/000999950026000001", "13f_cover_partial.xml", "13f_table_latest.xml")):
        urls[f"{ARCH}/{folder}/index.json"] = str(FIX / "13f_index.json")
        urls[f"{ARCH}/{folder}/primary_doc.xml"] = str(FIX / cover)
        urls[f"{ARCH}/{folder}/infotable.xml"] = str(FIX / table)
    # a 13F notice has only a cover page (real Pershing Square 13F-NT, synthetic folder)
    urls[f"{ARCH}/9999600/000999960026000001/primary_doc.xml"] = str(FIX / "13f_notice_pershing.xml")
    (fx / "urls.json").write_text(json.dumps(urls, indent=1))
    return root, cfg


def rows(root: Path, kind: str) -> dict[str, dict]:
    return {r["id"]: r for f in (root / "data" / MARKET / kind).glob("**/*.jsonl")
            for r in map(json.loads, f.read_text().splitlines())}


# ---------- parsers (no network, no files) ----------

def test_parse_form4_lines_owners_and_codes():
    p = ci.parse_form4((FIX / "form4_buy.xml").read_bytes())
    assert p["issuer_cik"] == "0000320193" and p["plan_10b5_1"] is False
    assert [o["role"] for o in p["owners"]] == ["Director", "Trust of director"]
    buy, ex = p["lines"]                                      # the holdings-only line is skipped
    assert (buy["code"], buy["shares"], buy["price"], buy["value"], buy["derivative"]) == ("P", 1000, 250.5, 250500, False)
    assert (ex["code"], ex["derivative"], ex["price"], ex["value"]) == ("M", True, None, None)

    s = ci.parse_form4((FIX / "form4_sale.xml").read_bytes())
    assert s["plan_10b5_1"] is True and s["owners"][0]["is_officer"] and not s["owners"][0]["is_director"]
    assert s["owners"][0]["role"] == "SVP, GC and Government Affairs"
    assert [(x["code"], x["shares"], x["price"], x["shares_after"]) for x in s["lines"]] == [("S", 2399, 336.18, 41992)]


def test_parse_schedule13_13d_and_13g():
    d = cs.parse_schedule13((FIX / "schedule13d.xml").read_bytes())
    assert (d["kind"], d["amendment"], d["event_date"], int(d["issuer_cik"])) == ("13D", False, "2026-09-25", 320193)
    assert [x["percent"] for x in d["persons"]] == [5.4, 5.3] and "board representation" in d["purpose"]
    g = cs.parse_schedule13((FIX / "schedule13g.xml").read_bytes())
    assert (g["kind"], g["amendment"], g["event_date"]) == ("13G", False, "2026-03-31")
    assert g["persons"][0] == {"name": "Vanguard Capital Management", "cik": None,
                               "shares": 1099168953.0, "percent": 7.48}
    o = cs.parse_schedule13((FIX / "schedule13d_other_issuer.xml").read_bytes())
    assert o["amendment"] and int(o["issuer_cik"]) == 1034665           # JPM as investor, not issuer


def test_parse_info_table_and_quarter_end():
    with (FIX / "13f_table_latest.xml").open("rb") as f:
        agg, n, placeholder = ch.parse_info_table(f, {"037833100": "AAPL", "594918104": "MSFT"})
    assert n == 4 and not placeholder
    with (FIX / "13f_table_norges_placeholder.xml").open("rb") as f:
        assert ch.parse_info_table(f, {"037833100": "AAPL"}) == ({}, 1, True)
    assert agg[("AAPL", None)]["shares"] == 150 and agg[("AAPL", None)]["n_lines"] == 2
    assert agg[("AAPL", None)]["value_usd"] == 37500 and agg[("AAPL", "PUT")]["shares"] == 20
    assert ("MSFT", None) not in agg
    assert ch.quarter_end(date(2026, 10, 5)) == date(2026, 9, 30)
    assert ch.quarter_end(date(2026, 1, 15)) == date(2025, 12, 31)
    assert ch.quarter_end(date(2026, 6, 30)) == date(2026, 3, 31)


def test_13f_cover_and_completeness():
    norges = ch.parse_cover((FIX / "13f_cover_norges.xml").read_bytes())
    assert (norges["report_type"], norges["entry_total"], norges["confidential"]) == ("13F HOLDINGS REPORT", 1507, True)
    blk = ch.parse_cover((FIX / "13f_cover_blackrock.xml").read_bytes())
    assert (blk["report_type"], blk["entry_total"], blk["confidential"]) == ("13F COMBINATION REPORT", 49968, False)
    nt = ch.parse_cover((FIX / "13f_notice_pershing.xml").read_bytes())
    assert (nt["report_type"], nt["entry_total"], nt["other_managers"]) == ("13F NOTICE", None, ["PERSHING SQUARE INC."])

    ok = {"report_type": "13F HOLDINGS REPORT", "entry_total": 4, "confidential": False, "other_managers": []}
    assert ch.incomplete_reason(ok, 4, False) is None
    assert ch.incomplete_reason({**ok, "entry_total": None}, 4, False) is None
    assert ch.incomplete_reason({**ok, "entry_total": 1507}, 1, False) == "table has 1 of 1507 lines"
    assert "placeholder" in ch.incomplete_reason({**ok, "entry_total": 1}, 1, True)
    assert "confidential" in ch.incomplete_reason({**ok, "confidential": True}, 4, False)
    assert "COMBINATION" in ch.incomplete_reason({**ok, "report_type": "13F COMBINATION REPORT"}, 4, False)


def test_range_flags_note_and_gated_widen():
    con = duckdb.connect()
    con.execute("""CREATE TABLE activist_stakes AS SELECT * FROM (VALUES
        ('AAPL', DATE '2026-09-20', 'Example Activist', 6.5),
        ('MSFT', DATE '2026-06-01', 'Old Activist', 5.1)) t(ticker, filing_date, filer_name, percent)""")
    off = sm.range_flags(con, date(2026, 10, 1), {"activist_13d_days": 30, "activist_13d_factor": 1.0})
    assert off == {"AAPL": (1.0, ["new 13D: Example Activist 6.5% filed 2026-09-20"])}
    on = sm.range_flags(con, date(2026, 10, 1), {"activist_13d_days": 30, "activist_13d_factor": 1.1})
    assert on["AAPL"][0] == 1.1 and on["AAPL"][1][0].endswith("x1.1")
    assert sm.range_flags(con, date(2026, 10, 1), {"activist_13d_factor": 0.5})["AAPL"][0] == 1.0  # never narrows


# ---------- collectors end to end (fixtures) ----------

def test_insiders_collect_and_dedupe(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_insiders.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert (out["filings_read"], out["new_rows"], out["open_market_buys"], out["open_market_sales"]) == (2, 3, 1, 1)
    assert out["failed"] == []                                # the old filing was never requested
    got = rows(root, "insiders")
    buy = got["0009999001-26-000001-1"]
    assert buy["insider_name"] == "Doe John; Doe Family Trust" and buy["role"] == "Director; Trust of director"
    assert buy["is_director"] and buy["value"] == 250500 and buy["ownership"] == "I" and buy["line"] == 1
    assert got["0009999001-26-000001-2"]["derivative"] is True
    sale = got["0001140361-26-038307-1"]
    assert sale["ticker"] == "AAPL" and sale["plan_10b5_1"] is True and sale["issuer_cik"] == "320193"
    assert sale["url"].endswith("/320193/000114036126038307/form4.xml")
    again = json.loads(run("collect_insiders.py", root, cfg).stdout)
    assert (again["filings_read"], again["new_rows"]) == (0, 0)

    skip = run("collect_insiders.py", root, cfg, market="nosec")
    assert skip.returncode == 0 and "skipped" in json.loads(skip.stdout)


def test_stakes_collect_filters_investor_filings(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_stakes.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert (out["new_rows"], out["new_13d"], out["as_investor_skipped"], out["failed"]) == (2, 1, 2, [])
    got = rows(root, "stakes")
    d = got["0009999100-26-000001"]
    assert (d["kind"], d["percent"], d["shares"], d["filer_cik"]) == ("13D", 5.4, 800000000, "9999100")
    assert d["filer_name"] == "Example Activist Partners LP" and len(d["reporting_persons"]) == 2
    g = got["0002100119-26-000139"]
    assert (g["kind"], g["percent"], g["filer_name"], g["filer_cik"]) == ("13G", 7.48, "Vanguard Capital Management", "2100119")
    assert json.loads(run("collect_stakes.py", root, cfg).stdout)["new_rows"] == 0
    assert "skipped" in json.loads(run("collect_stakes.py", root, cfg, market="nosec").stdout)


def test_holdings_collect_changes_and_gate(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_holdings.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # Example 4+3 rows, Combo 3, Placeholder 1, Partial 3, Notice 1 (each filing has a ticker-null filing row)
    assert out["new_rows"] == 15 and out["failed"] == [] and out["waiting_on"] == []
    assert out["reported_by_other_manager"] == [f"Notice Capital {ch.quarter_end(TODAY)}: reported by PERSHING SQUARE INC."]
    got = rows(root, "holdings")
    q = str(ch.quarter_end(TODAY))

    def filer_rows(cik):
        return {(x["ticker"], x["put_call"]): x for x in got.values() if x["period"] == q and x["filer_cik"] == cik}
    ex = filer_rows("9999200")
    assert ex[("AAPL", None)]["shares"] == 150 and ex[("AAPL", "PUT")]["shares"] == 20
    assert ex[("MSFT", None)]["shares"] == 0 and ex[("MSFT", None)]["n_lines"] == 0   # complete: exit is explicit
    assert ex[(None, None)]["complete"] is True and ex[(None, None)]["n_lines"] == 4
    combo, ph, part, nt = (filer_rows(c) for c in ("9999300", "9999400", "9999500", "9999600"))
    assert set(combo) == {(None, None), ("AAPL", None), ("AAPL", "PUT")}             # no MSFT zero row
    assert combo[(None, None)]["complete"] is False and "COMBINATION" in combo[(None, None)]["note"]
    assert set(ph) == {(None, None)} and "placeholder" in ph[(None, None)]["note"]
    assert set(part) == {(None, None), ("AAPL", None), ("AAPL", "PUT")}
    assert part[(None, None)]["note"] == "table has 4 of 1507 lines" and part[("AAPL", None)]["complete"] is False
    assert set(nt) == {(None, None)} and nt[(None, None)]["report_type"] == "13F NOTICE"
    # every filer has the latest quarter: no network at all
    again = json.loads(run("collect_holdings.py", root, cfg).stdout)
    assert again["skipped"].startswith("up to date")
    forced = json.loads(run("collect_holdings.py", root, cfg, "--force").stdout)
    assert forced["new_rows"] == 0 and forced["filings_loaded"] == []

    # views and the context pack on all three collectors' output
    assert run("collect_insiders.py", root, cfg).returncode == 0
    assert run("collect_stakes.py", root, cfg).returncode == 0
    ctx = run("context.py", root, cfg)
    assert ctx.returncode == 0, ctx.stderr
    text = ctx.stdout.split("## Smart money")[1]
    for needle in ("| AAPL | 250500.0 | 806496.0 | -555996.0 |", "Doe John", "Example Activist Partners LP",
                   f"| AAPL | {q} | 3 |", "| 50.0 |", f"| MSFT | {q} | 0 | 0.0 | -100.0 | 0 | 1 |"):
        assert needle in text, needle
    nosec = run("context.py", root, cfg, market="nosec")
    assert nosec.returncode == 0 and "Smart money" not in nosec.stdout


def write_jsonl(root: Path, kind: str, recs: list[dict]) -> None:
    p = root / "data" / MARKET / kind / f"{TODAY:%Y}" / f"{TODAY:%m}" / f"{TODAY}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)


def test_views_cluster_buys_and_13f_actions(tmp_path, monkeypatch):
    import common
    root, _ = setup(tmp_path)
    t = str(TODAY - timedelta(days=5))
    base = {"form": "4", "filing_date": t, "derivative": False, "transaction_date": t, "first_seen_at": "2026-01-01T00:00:00Z"}
    write_jsonl(root, "insiders", [
        {**base, "id": f"a{i}-1", "accession": f"a{i}", "ticker": "AAPL", "insider_name": n, "code": "P", "value": 1000.0}
        for i, n in enumerate(["A", "B", "C"])] + [
        {**base, "id": "m1-1", "accession": "m1", "ticker": "MSFT", "insider_name": "A", "code": "P", "value": 5.0},
        {**base, "id": "m2-1", "accession": "m2", "ticker": "MSFT", "insider_name": "B", "code": "S", "value": 50.0,
         "plan_10b5_1": True}])
    h = {"filer_name": "F", "put_call": None, "first_seen_at": "2026-01-01T00:00:00Z"}
    write_jsonl(root, "holdings", [
        {**h, "id": "q1-AAPL", "filer_cik": "1", "ticker": "AAPL", "period": "2026-03-31", "filing_date": "2026-05-10", "shares": 0},
        {**h, "id": "q2-AAPL", "filer_cik": "1", "ticker": "AAPL", "period": "2026-06-30", "filing_date": "2026-08-10", "shares": 10},
        {**h, "id": "q1-MSFT", "filer_cik": "1", "ticker": "MSFT", "period": "2026-03-31", "filing_date": "2026-05-10", "shares": 10},
        {**h, "id": "q2-MSFT", "filer_cik": "1", "ticker": "MSFT", "period": "2026-06-30", "filing_date": "2026-08-10", "shares": 0},
        {**h, "id": "q2-MSFT-dup", "filer_cik": "1", "ticker": "MSFT", "period": "2026-06-30", "filing_date": "2026-08-01", "shares": 99},
    ])
    monkeypatch.setattr(common, "ROOT", root)
    con = common.connect(MARKET)
    flow = {r[0]: r for r in con.execute("SELECT ticker, buyers_30d, cluster_buy, net_value_30d, planned_sell_share_30d "
                                         "FROM insider_flow").fetchall()}
    assert flow["AAPL"][1:4] == (3, True, 3000.0) and flow["MSFT"][1:] == (1, False, -45.0, 1.0)
    assert con.execute("SELECT ticker, buyers_30d FROM insider_cluster_buys").fetchall() == [("AAPL", 3)]
    actions = dict(con.execute("SELECT ticker, action FROM holdings_change WHERE period = '2026-06-30'").fetchall())
    assert actions == {"AAPL": "new", "MSFT": "exit"}                 # latest filing per period wins


def fat_tailed_walk(rng, n: int, start: float, daily_vol: float) -> list[float]:
    return list(start * np.exp(np.cumsum(rng.standard_t(4, n) * daily_vol / np.sqrt(2))))


def test_ranges_carry_activist_note(tmp_path):
    root, cfg = setup(tmp_path)
    rng = np.random.default_rng(5)
    days, d = [], TODAY - timedelta(days=760)
    while len(days) < 520:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    series = {"BENCH": fat_tailed_walk(rng, 520, 100, 0.01), "VOLX": [15.0] * 520,
              "AAPL": fat_tailed_walk(rng, 520, 150, 0.015), "MSFT": fat_tailed_walk(rng, 520, 300, 0.012)}
    for i, day in enumerate(days):
        p = root / "data" / MARKET / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n" + "".join(
            f"{day},{t},{c[i]},{c[i] * 1.01},{c[i] * 0.99},{c[i]},{c[i]},{1000 + i},2026-01-01T00:00:00+00:00\n"
            for t, c in series.items()))
    assert run("collect_stakes.py", root, cfg).returncode == 0          # writes the AAPL 13D (filed today)
    (cfg / "ranges.yaml").write_text((cfg / "ranges.yaml").read_text().replace("activist_13d_factor: 1.0",
                                                                               "activist_13d_factor: 1.2"))
    for script in ("features.py", "calibrate.py"):
        r = run(script, root, cfg)
        assert r.returncode == 0, r.stderr
    # made_at on the evening of the last bar: the bars end weeks ago, and the late-run guard
    # (correctly) skips ranges whose target session closed before made_at.
    r = run("ranges.py", root, cfg, "--now", f"{days[-1]}T23:00:00+00:00")
    assert r.returncode == 0, r.stderr
    got = rows(root, "ranges")
    a1 = next(x for x in got.values() if x["ticker"] == "AAPL" and x["horizon_days"] == 1)
    m1 = next(x for x in got.values() if x["ticker"] == "MSFT" and x["horizon_days"] == 1)
    assert any(n.startswith("new 13D: Example Activist Partners LP 5.4%") and n.endswith("x1.2") for n in a1["notes"])
    assert not any("13D" in n for n in m1["notes"])
