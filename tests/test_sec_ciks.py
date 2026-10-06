"""Issue #23: a ticker's SEC filings under its mapped CIK plus its predecessor/related CIKs
(`fundamentals.predecessor_ciks`), merged and de-duplicated by accession number, in every SEC
collector (collect_filings, collect_events, collect_insiders, collect_stakes; collect_fundamentals
in tests/test_fundamentals.py). Offline: hand-made submission lists served through
MB_SEC_FIXTURES. XOM maps to ExxonMobil Holdings (2115436); Exxon Mobil Corp (34088) still files.
The Form 4 / Schedule 13G documents are the real fixtures of tests/fixtures/sec with the issuer
CIK replaced (synthetic). Run: pytest -q"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FIX = REPO / "tests" / "fixtures" / "sec"
MARKET = "testciks"
ARCH = "https://www.sec.gov/Archives/edgar/data"
sys.path.insert(0, str(SCRIPTS))

import sec  # noqa: E402
from marketbrief.sources.sec_client import Edgar  # noqa: E402

TODAY = datetime.now(timezone.utc).date()
D1, D2 = str(TODAY - timedelta(days=1)), str(TODAY - timedelta(days=2))
CIKS = {"AAPL": 320193, "XOM": 2115436}
PRED = 34088
YAML = """
market: testciks
name: Test SEC CIKs
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  BENCH: {role: benchmark, name: Benchmark}
sectors:
  Mixed: [AAPL, XOM]
tickers:
  AAPL: {name: Apple}
  XOM: {name: ExxonMobil}
filings: sec
filing_lookback_days: 7
relationships:
  insiders: {lookback_days: 7}
  stakes: {lookback_days: 7}
"""
PRED_YAML = "fundamentals:\n  predecessor_ciks: {XOM: [34088]}\n"

# (accession, form, filing date, primary document, items, acceptance time)
SUBS = {
    320193: [("0000320193-26-000101", "8-K", D1, "a8k.htm", "2.02,9.01", f"{D1}T20:30:00.000Z"),
             ("0001140361-26-038307", "4", D1, "xslF345X06/form4.xml", "", f"{D1}T21:00:00.000Z"),
             ("0002100119-26-000139", "SCHEDULE 13G", D2, "xslSCHEDULE_13G_X02/primary_doc.xml", "", f"{D2}T15:00:00.000Z"),
             ("0000320193-26-000100", "10-Q", D2, "a10q.htm", "", f"{D2}T20:31:00.000Z")],
    2115436: [("0002115436-26-000020", "8-K", D1, "x8k.htm", "7.01", f"{D1}T12:00:00.000Z"),
              ("0002115436-26-000021", "4", D1, "xslF345X06/form4.xml", "", f"{D1}T21:05:00.000Z"),
              # joint filing: listed under both CIKs (kept once, under the mapped CIK)
              ("0000034088-26-000093", "10-Q", D2, "xom10q.htm", "", f"{D2}T10:15:00.000Z")],
    PRED: [("0000034088-26-000093", "10-Q", D2, "xom10q.htm", "", f"{D2}T10:15:00.000Z"),
           ("0000034088-26-000110", "8-K", D1, "xom8k.htm", "2.02,9.01", f"{D1}T10:30:00.000Z"),
           ("0000034088-26-000111", "4", D1, "xslF345X06/form4.xml", "", f"{D1}T21:10:00.000Z"),
           ("0002100119-26-000200", "SCHEDULE 13G", D2, "xslSCHEDULE_13G_X02/primary_doc.xml", "", f"{D2}T16:00:00.000Z"),
           ("0000034088-26-000050", "8-K", str(TODAY - timedelta(days=60)), "old.htm", "8.01", None)],  # too old
}
XOM_ACCS = {"0002115436-26-000020", "0002115436-26-000021", "0000034088-26-000093",
            "0000034088-26-000110", "0000034088-26-000111", "0002100119-26-000200"}


def submissions(name: str, filings: list[tuple]) -> dict:
    cols = ["accessionNumber", "form", "filingDate", "primaryDocument", "items", "acceptanceDateTime"]
    recent = {c: [f[i] for f in filings] for i, c in enumerate(cols)}
    recent["reportDate"] = ["2026-06-30" if f[1] == "10-Q" else "" for f in filings]
    recent["primaryDocDescription"] = [f[1] for f in filings]
    return {"name": name, "filings": {"recent": recent}}


def issuer_doc(src: str, cik: int) -> str:
    return (FIX / src).read_text().replace("0000320193", f"{cik:010d}")


def setup(tmp: Path, predecessors: bool = True) -> tuple[Path, Path]:
    root, cfg, fx = tmp / "repo", tmp / "config", tmp / "sec"
    for d in (root / "data", cfg / "markets", fx):
        d.mkdir(parents=True, exist_ok=True)
    (cfg / "markets" / f"{MARKET}.yaml").write_text(YAML + (PRED_YAML if predecessors else ""))
    (cfg / "events.yaml").write_text((REPO / "config" / "events.yaml").read_text())
    for name in ("ranges.yaml", "settings.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    (fx / "tickers.json").write_text(json.dumps({str(i): {"cik_str": c, "ticker": t, "title": t}
                                                 for i, (t, c) in enumerate(CIKS.items())}))
    urls = {"https://www.sec.gov/files/company_tickers.json": "tickers.json"}
    for cik, filings in SUBS.items():
        (fx / f"sub_{cik}.json").write_text(json.dumps(submissions(str(cik), filings)))
        urls[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = f"sub_{cik}.json"
    for name, src, cik in (("f4_xom.xml", "form4_sale.xml", 2115436), ("f4_pred.xml", "form4_sale.xml", PRED),
                           ("g_pred.xml", "schedule13g.xml", PRED)):
        (fx / name).write_text(issuer_doc(src, cik))
    urls.update({
        f"{ARCH}/320193/000114036126038307/form4.xml": str(FIX / "form4_sale.xml"),
        f"{ARCH}/320193/000210011926000139/primary_doc.xml": str(FIX / "schedule13g.xml"),
        f"{ARCH}/2115436/000211543626000021/form4.xml": "f4_xom.xml",
        f"{ARCH}/34088/000003408826000111/form4.xml": "f4_pred.xml",
        f"{ARCH}/34088/000210011926000200/primary_doc.xml": "g_pred.xml",
    })
    (fx / "urls.json").write_text(json.dumps(urls, indent=1))
    return root, cfg


def run(script: str, root: Path, cfg: Path) -> dict:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET,
           "MB_SEC_FIXTURES": str(root.parent / "sec"), "SEC_USER_AGENT": "market-brief tests test@example.com"}
    r = subprocess.run([sys.executable, str(SCRIPTS / script)], cwd=SCRIPTS, env=env,
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr + r.stdout
    return json.loads(r.stdout)


def rows(root: Path, kind: str) -> list[dict]:
    return [json.loads(x) for f in sorted((root / "data" / MARKET / kind).glob("**/*.jsonl"))
            for x in f.read_text().splitlines()]


def strip(rs: list[dict]) -> list[dict]:
    return sorted(({k: v for k, v in r.items() if k != "first_seen_at"} for r in rs), key=lambda r: r["id"])


# ---------- shared mechanism (sec.py) ----------

def test_related_ciks_reads_the_fundamentals_key():
    assert sec.related_ciks({"fundamentals": {"predecessor_ciks": {"xom": [34088], "ABC": 7}}}) == {"XOM": [34088], "ABC": [7]}
    assert sec.related_ciks({"market": "x"}) == {} and sec.related_ciks({"fundamentals": None}) == {}


def test_merge_recent_dedupes_by_accession_and_keeps_one_cik_unchanged():
    a = {"name": "A", **submissions("A", SUBS[2115436])["filings"]["recent"]}   # as Edgar.recent returns it
    p = {"name": "P", **submissions("P", SUBS[PRED])["filings"]["recent"]}
    one = sec.merge_recent([(2115436, a)])
    assert {k: v for k, v in one.items() if k != "cik"} == a and one["cik"] == [2115436] * 3
    m = sec.merge_recent([(2115436, a), (PRED, p)])
    assert len(m["accessionNumber"]) == len(set(m["accessionNumber"])) == 7       # 3 + 5 - 1 joint
    joint = m["accessionNumber"].index("0000034088-26-000093")
    assert m["cik"][joint] == 2115436                                             # first CIK wins
    assert m["filingDate"] == sorted(m["filingDate"], reverse=True)               # newest first
    assert all(len(v) == 7 for k, v in m.items() if k != "name") and m["name"] == "A"
    # a column one CIK lacks is None for its filings
    m2 = sec.merge_recent([(1, {"form": ["8-K"], "accessionNumber": ["x"], "items": ["2.02"]}),
                           (2, {"form": ["4"], "accessionNumber": ["y"]})])
    assert m2["items"] == ["2.02", None] or m2["items"] == [None, "2.02"]


def test_ticker_submissions_reports_each_failed_cik(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setenv("MB_SEC_FIXTURES", str(tmp_path / "sec"))
    edgar = Edgar("t t@example.com")
    rec, failed = sec.ticker_submissions(edgar, "XOM", 2115436, {"XOM": [34088, 999]})
    assert set(rec["cik"]) == {2115436, PRED} and edgar.requests == 3
    assert [(f["ticker"], f["cik"]) for f in failed] == [("XOM", 999)] and "no fixture" in failed[0]["error"]
    rec, failed = sec.ticker_submissions(edgar, "AAPL", 320193, {"XOM": [34088]})
    assert failed == [] and set(rec["cik"]) == {320193} and edgar.requests == 4   # other tickers: one request
    assert sec.ticker_submissions(edgar, "X", 1, {"X": [2]})[0] is None             # every CIK failed


# ---------- collectors end to end ----------

def test_collect_filings_merges_xom_ciks_once_and_keeps_aapl(tmp_path):
    root, cfg = setup(tmp_path / "with")
    out = run("collect_filings.py", root, cfg)
    assert out["failed"] == [] and out["requests"] == 1 + 3                      # ticker map + 3 submission lists
    got = rows(root, "filings")
    xom = [r for r in got if r["ticker"] == "XOM"]
    assert sorted(r["id"] for r in xom) == sorted(XOM_ACCS)                     # each filing exactly once
    by = {r["id"]: r for r in xom}
    assert by["0000034088-26-000110"]["cik"] == "34088"
    assert by["0000034088-26-000110"]["url"] == f"{ARCH}/34088/000003408826000110/xom8k.htm"
    assert by["0000034088-26-000093"]["cik"] == "2115436"                       # joint: the mapped CIK's folder
    assert run("collect_filings.py", root, cfg)["new_filings"] == 0                # second run: nothing new

    root0, cfg0 = setup(tmp_path / "without", predecessors=False)              # before #23: mapped CIK only
    run("collect_filings.py", root0, cfg0)
    old = rows(root0, "filings")
    assert {r["id"] for r in old if r["ticker"] == "XOM"} == {"0002115436-26-000020", "0002115436-26-000021",
                                                              "0000034088-26-000093"}
    assert strip([r for r in got if r["ticker"] == "AAPL"]) == strip([r for r in old if r["ticker"] == "AAPL"])


def test_collect_insiders_and_stakes_follow_the_predecessor_cik(tmp_path):
    root, cfg = setup(tmp_path / "with")
    ins = run("collect_insiders.py", root, cfg)
    assert ins["failed"] == [] and ins["filings_read"] == 3 and ins["other_issuer_skipped"] == 0
    got = rows(root, "insiders")
    xom = {r["accession"]: r for r in got if r["ticker"] == "XOM"}
    assert set(xom) == {"0002115436-26-000021", "0000034088-26-000111"}
    assert (xom["0000034088-26-000111"]["issuer_cik"], xom["0002115436-26-000021"]["issuer_cik"]) == ("34088", "2115436")
    assert xom["0000034088-26-000111"]["url"] == f"{ARCH}/34088/000003408826000111/form4.xml"
    stk = run("collect_stakes.py", root, cfg)
    assert stk["failed"] == [] and stk["new_rows"] == 2 and stk["as_investor_skipped"] == 0
    st = {r["id"]: r for r in rows(root, "stakes")}
    assert st["0002100119-26-000200"]["ticker"] == "XOM" and st["0002100119-26-000200"]["issuer_cik"] == "34088"

    root0, cfg0 = setup(tmp_path / "without", predecessors=False)
    run("collect_insiders.py", root0, cfg0)
    run("collect_stakes.py", root0, cfg0)
    old_ins, old_st = rows(root0, "insiders"), rows(root0, "stakes")
    assert {r["accession"] for r in old_ins if r["ticker"] == "XOM"} == {"0002115436-26-000021"}
    assert not [r for r in old_st if r["ticker"] == "XOM"]
    for new, old in ((got, old_ins), (list(st.values()), old_st)):               # AAPL unchanged
        assert strip([r for r in new if r["ticker"] == "AAPL"]) == strip([r for r in old if r["ticker"] == "AAPL"])
        assert [r for r in new if r["ticker"] == "AAPL"]


def test_sec_earnings_merges_xom_ciks_once(tmp_path, monkeypatch):
    import collect_events as ce
    setup(tmp_path)
    monkeypatch.setenv("MB_SEC_FIXTURES", str(tmp_path / "sec"))
    us = {"market": "us", "calendar": "XNYS", "timezone": "America/New_York"}
    with_pred = {**us, "fundamentals": {"predecessor_ciks": {"XOM": [34088]}}}
    rep, rep0 = {}, {}
    out, failed = ce.sec_earnings(with_pred, {"AAPL": {}, "XOM": {}}, "t t@example.com", rep)
    out0, failed0 = ce.sec_earnings(us, {"AAPL": {}, "XOM": {}}, "t t@example.com", rep0)
    assert failed == failed0 == []
    assert len(out["XOM"]) == 1 and "XOM" not in out0              # the results 8-K under 34088 only
    assert out["XOM"][0][1:] == ("before_open", 0)                 # accepted 06:30 New York time
    assert len(rep["XOM"]) == len(rep0["XOM"]) == 1                # the joint 10-Q once
    assert out["AAPL"] == out0["AAPL"] and rep["AAPL"] == rep0["AAPL"]


def test_failed_predecessor_list_is_reported_like_any_failed_cik(tmp_path):
    root, cfg = setup(tmp_path)
    urls = json.loads((tmp_path / "sec" / "urls.json").read_text())
    del urls[f"https://data.sec.gov/submissions/CIK{PRED:010d}.json"]
    (tmp_path / "sec" / "urls.json").write_text(json.dumps(urls))
    for script in ("collect_filings.py", "collect_insiders.py", "collect_stakes.py"):
        out = run(script, root, cfg)
        assert [(f["ticker"], f["cik"]) for f in out["failed"]] == [("XOM", PRED)], script
    # the mapped CIK's filings are still collected
    assert {"0002115436-26-000020", "0002115436-26-000021"} <= {r["id"] for r in rows(root, "filings")}
