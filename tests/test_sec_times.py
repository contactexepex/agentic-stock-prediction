"""SEC acceptance times: the submissions JSON's acceptanceDateTime can be shifted later by the New
York UTC offset (whole file, some CIKs; seen from 2026-10-05); sec.Edgar.recent checks each file
against the SGML header <ACCEPTANCE-DATETIME> (US Eastern) of its newest filing and corrects it,
and stored rows are corrected on read through sec_times (check_sec_times.py, common.connect).
Offline: real headers (*.hdr.sgml) and real submission lists trimmed to three filings, downloaded
2026-10-06 (tests/fixtures/sec/README.md). Run: pytest -q"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FIX = REPO / "tests" / "fixtures" / "sec"
ARCH = "https://www.sec.gov/Archives/edgar/data"
MARKET = "testsectimes"
sys.path.insert(0, str(SCRIPTS))

import sec  # noqa: E402

CIKS = {"JPM": 19617, "AAPL": 320193, "TSLA": 1318605}
HEADERS = {   # accession -> (CIK, fixture): every filing of the trimmed lists
    "0001628280-26-054343": (19617, "hdr_jpm_10q_0001628280-26-054343.sgml"),
    "0001628280-26-048078": (19617, "hdr_jpm_8k_0001628280-26-048078.sgml"),
    "0001628280-26-008131": (19617, "hdr_jpm_10k_0001628280-26-008131.sgml"),
    "0001140361-26-038674": (320193, "hdr_aapl_form4_0001140361-26-038674.sgml"),
    "0000320193-26-000020": (320193, "hdr_aapl_10q_0000320193-26-000020.sgml"),
    "0000320193-25-000008": (320193, "hdr_aapl_10q_0000320193-25-000008.sgml"),
    "0001628280-26-064366": (1318605, "hdr_tsla_8k_0001628280-26-064366.sgml"),
    "0001628280-26-063820": (1318605, "hdr_tsla_8k_0001628280-26-063820.sgml"),
    "0001104659-26-106432": (1318605, "hdr_tsla_form4_0001104659-26-106432.sgml"),
}
# true acceptance (UTC) of every filing in the trimmed lists: header / index page time, ET -> UTC
TRUE = {
    "0001628280-26-054343": "2026-08-06T20:19:03.000Z",   # JPM 10-Q, 16:19:03 EDT (JSON 2026-08-07T00:19:03Z)
    "0001628280-26-048078": "2026-07-14T10:30:38.000Z",   # JPM 8-K 2.02, 06:30:38 EDT (JSON 14:30:38Z)
    "0001628280-26-008131": "2026-02-13T21:20:00.000Z",   # JPM 10-K, 16:20:00 EST (JSON 2026-02-14T02:20:00Z, +5h)
    "0001140361-26-038674": "2026-10-05T22:42:45.000Z",   # AAPL Form 4, 18:42:45 EDT (JSON 2026-10-06T02:42:45Z)
    "0000320193-26-000020": "2026-07-31T10:01:02.000Z",   # AAPL 10-Q, 06:01:02 EDT
    "0000320193-25-000008": "2025-01-31T11:01:27.000Z",   # AAPL 10-Q, 06:01:27 EST
    "0001628280-26-064366": "2026-10-02T13:04:26.000Z",   # TSLA 8-K, 09:04:26 EDT (JSON right)
    "0001628280-26-063820": "2026-09-29T20:38:50.000Z",   # TSLA 8-K, 16:38:50 EDT
    "0001104659-26-106432": "2026-09-09T23:00:10.000Z",   # TSLA Form 4, 19:00:10 EDT
}


def urls(headers=HEADERS) -> dict:
    out = {"https://www.sec.gov/files/company_tickers.json": "tickers.json"}
    for t, cik in CIKS.items():
        out[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = str(FIX / f"submissions_{t.lower()}_trimmed.json")
    for acc, (cik, name) in headers.items():
        out[sec.archive_url(cik, acc, f"{acc}.hdr.sgml")] = str(FIX / name)
    return out


def fixtures(d: Path, headers=HEADERS) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "tickers.json").write_text(json.dumps({str(i): {"cik_str": c, "ticker": t, "title": t}
                                                for i, (t, c) in enumerate(CIKS.items())}))
    (d / "urls.json").write_text(json.dumps(urls(headers), indent=1))
    return d


@pytest.fixture
def edgar(tmp_path, monkeypatch):
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures(tmp_path / "sec")))
    return sec.Edgar("market-brief tests test@example.com")


# ---------- the rule ----------

def test_header_time_is_eastern_and_converted_to_utc():
    for acc, (_, name) in HEADERS.items():
        assert sec.sgml_acceptance((FIX / name).read_bytes()) == TRUE[acc]
    assert sec.sgml_acceptance(b"<SEC-HEADER>no time</SEC-HEADER>") is None
    # the full submission .txt carries the same tag (YYYYMMDDHHMMSS, Eastern)
    assert sec.sgml_acceptance(b"<SEC-DOCUMENT>x\n<ACCEPTANCE-DATETIME>20260714063038\n") == TRUE["0001628280-26-048078"]


def test_shift_is_the_eastern_offset_and_unshift_inverts_it():
    cases = [("2026-07-14T14:30:38.000Z", TRUE["0001628280-26-048078"]),     # EDT: +4h
             ("2026-10-06T02:42:45.000Z", TRUE["0001140361-26-038674"]),     # EDT, across midnight UTC
             ("2026-02-14T02:20:00.000Z", TRUE["0001628280-26-008131"]),     # EST: +5h
             ("2025-01-31T16:01:27.000Z", TRUE["0000320193-25-000008"])]
    for shifted, true in cases:
        assert sec.is_shifted(shifted, true) and sec.unshift(shifted) == true
    assert not sec.is_shifted(TRUE["0001628280-26-064366"], TRUE["0001628280-26-064366"])
    assert not sec.is_shifted("2026-07-14T15:30:38.000Z", TRUE["0001628280-26-048078"])   # +5h in summer: not the rule
    # the days around both 2026 DST changes (March 8, November 1), at EDGAR hours
    for day in ("2026-03-06", "2026-03-09", "2026-10-30", "2026-11-02"):
        for hh in ("06:00:01", "12:00:00", "21:59:59"):
            true = datetime.fromisoformat(f"{day}T{hh}").replace(tzinfo=sec.EASTERN)
            shifted = true + timedelta(hours=sec.et_offset_hours(true))
            assert sec.unshift(sec.iso_z(shifted)) == sec.iso_z(true)


# ---------- Edgar.recent ----------

def test_recent_corrects_a_shifted_file_and_keeps_a_right_one(edgar):
    jpm = edgar.recent(CIKS["JPM"])
    assert edgar.requests == 2 and edgar.time_checks == {"19617": "shifted"}
    assert dict(zip(jpm["accessionNumber"], jpm["acceptanceDateTime"])) == {a: TRUE[a] for a in jpm["accessionNumber"]}
    assert jpm["acceptanceDateTimeJson"][1] == "2026-07-14T14:30:38.000Z"            # the served value is kept
    aapl = edgar.recent(CIKS["AAPL"])
    assert dict(zip(aapl["accessionNumber"], aapl["acceptanceDateTime"])) == {a: TRUE[a] for a in aapl["accessionNumber"]}
    tsla = edgar.recent(CIKS["TSLA"])
    assert dict(zip(tsla["accessionNumber"], tsla["acceptanceDateTime"])) == {a: TRUE[a] for a in tsla["accessionNumber"]}
    assert "acceptanceDateTimeJson" not in tsla and edgar.requests == 6               # one header per CIK
    assert sec.time_summary(edgar) == {"ok": 1, "shifted": ["19617", "320193"], "unverified": {}}
    edgar.recent(CIKS["JPM"])                                                         # header cached: no request
    assert edgar.requests == 7
    # sec.filings (insiders, stakes, holdings, fundamentals) and the merged lists carry the fix
    f = sec.filings(jpm, {"8-K"})
    assert f[0]["accepted_at"] == TRUE["0001628280-26-048078"]
    merged, failed = sec.ticker_submissions(edgar, "JPM", CIKS["JPM"], {"JPM": [CIKS["TSLA"]]})
    assert failed == [] and set(merged["acceptanceDateTime"]) == {TRUE[a] for a in merged["accessionNumber"]}


def test_unexplained_difference_or_missing_header_is_unverified_and_kept(tmp_path, monkeypatch):
    other = {**HEADERS, "0001140361-26-038674": (320193, "hdr_tsla_8k_0001628280-26-064366.sgml")}   # wrong time
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures(tmp_path / "a", other)))
    e = sec.Edgar("t t@example.com")
    raw = json.loads((FIX / "submissions_aapl_trimmed.json").read_text())["filings"]["recent"]
    assert e.recent(CIKS["AAPL"])["acceptanceDateTime"] == raw["acceptanceDateTime"]
    assert e.time_checks["320193"].startswith("unverified: 0001140361-26-038674 JSON")
    no_hdr = {k: v for k, v in HEADERS.items() if v[0] != CIKS["AAPL"]}
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures(tmp_path / "b", no_hdr)))
    e = sec.Edgar("t t@example.com")
    assert e.recent(CIKS["AAPL"])["acceptanceDateTime"] == raw["acceptanceDateTime"] and e.requests == 1
    assert sec.time_summary(e) == {"ok": 0, "shifted": [], "unverified": {"320193": "no header fixture"}}


# ---------- collectors and the read-side correction ----------

YAML = """
market: testsectimes
name: Test SEC times
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  BENCH: {role: benchmark, name: Benchmark}
sectors:
  Mixed: [JPM, AAPL, TSLA]
tickers:
  JPM: {name: JPMorgan}
  AAPL: {name: Apple}
  TSLA: {name: Tesla}
filings: sec
filing_lookback_days: 36500
"""


def setup(tmp: Path, headers=HEADERS) -> tuple[Path, Path, Path]:
    root, cfg = tmp / "repo", tmp / "config"
    for d in (root / "data", cfg / "markets"):
        d.mkdir(parents=True, exist_ok=True)
    (cfg / "markets" / f"{MARKET}.yaml").write_text(YAML)
    for name in ("events.yaml", "ranges.yaml", "settings.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    return root, cfg, fixtures(tmp / "sec", headers)


def run(script: str, root: Path, cfg: Path, fx: Path, *args) -> dict:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET,
           "MB_SEC_FIXTURES": str(fx), "SEC_USER_AGENT": "market-brief tests test@example.com"}
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=SCRIPTS, env=env,
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr + r.stdout
    return json.loads(r.stdout)


def query(root: Path, cfg: Path, sql: str) -> list[tuple]:
    code = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import json; from common import connect; "
            f"print(json.dumps([list(map(str, r)) for r in connect({MARKET!r}).execute({sql!r}).fetchall()]))")
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg)}
    r = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, env=env, capture_output=True, text=True, check=True)
    return [tuple(x) for x in json.loads(r.stdout)]


def utc(v: str) -> str:
    return str(pd.Timestamp(v).tz_convert("UTC"))


def test_collect_filings_stores_the_header_times(tmp_path):
    root, cfg, fx = setup(tmp_path)
    out = run("collect_filings.py", root, cfg, fx)
    assert out["sec_times"] == {"ok": 1, "shifted": ["19617", "320193"], "unverified": {}}
    got = [json.loads(x) for f in (root / "data" / MARKET / "filings").glob("**/*.jsonl") for x in f.read_text().splitlines()]
    assert got and {r["id"]: r["accepted_at"] for r in got} == {r["id"]: TRUE[r["id"]] for r in got}


def test_events_time_jpm_results_before_the_open(tmp_path, monkeypatch):
    """JPM's 8-K 2.02 of 2026-07-14: 06:30 ET (before the open), not 10:30 ET (during)."""
    import collect_events as ce
    _, _, fx = setup(tmp_path)
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fx))
    cfg = {"market": "us", "calendar": "XNYS", "timezone": "America/New_York"}
    reports, times = {}, {}
    rows, failed = ce.sec_earnings(cfg, {"JPM": {}}, "t t@example.com", reports, times)
    assert failed == [] and rows == {"JPM": [(date(2026, 7, 14), "before_open", 0)]}
    assert ce.timing(cfg, pd.Timestamp("2026-07-14T14:30:38Z")) == (date(2026, 7, 14), "during")   # the JSON's
    assert sorted(reports["JPM"]) == [(date(2026, 2, 13), "after_close", "10-K", date(2025, 12, 31)),
                                      (date(2026, 8, 6), "after_close", "10-Q", date(2026, 6, 30))]
    assert times == {"ok": 0, "shifted": ["19617"], "unverified": {}}


def test_stored_shifted_rows_are_corrected_on_read(tmp_path):
    """Rows stored before the fix (headers missing: the JSON's shifted times are stored) are
    checked by check_sec_times.py and read corrected; data files are only appended to."""
    root, cfg, fx_none = setup(tmp_path / "old", headers={})
    run("collect_filings.py", root, cfg, fx_none)
    base = root / "data" / MARKET
    raw = {json.loads(x)["id"]: json.loads(x)["accepted_at"]
           for f in (base / "filings").glob("**/*.jsonl") for x in f.read_text().splitlines()}
    assert raw["0001628280-26-048078"] == "2026-07-14T14:30:38.000Z"                  # stored shifted
    ins = base / "insiders" / "2026" / "10"
    ins.mkdir(parents=True)
    (ins / "2026-10-06.jsonl").write_text(json.dumps({
        "id": "0001140361-26-038674-0", "accession": "0001140361-26-038674", "line": 0, "ticker": "AAPL",
        "issuer_cik": "320193", "form": "4", "filing_date": "2026-10-05", "accepted_at": "2026-10-06T02:42:45.000Z",
        "url": f"{ARCH}/320193/000114036126038674/form4.xml", "first_seen_at": "2026-10-06T03:00:00+00:00"}) + "\n")
    before = {p: p.read_bytes() for p in base.glob("**/*.jsonl")}
    fx = fixtures(tmp_path / "sec_full")
    out = run("check_sec_times.py", root, cfg, fx)
    assert out["checked"] == out["written"] == len(raw) and out["failed"] == []
    assert out["wrong"] == 6 and {w["stored_minus_true_h"] for w in out["wrong_rows"]} == {4.0, 5.0}
    assert all(p.read_bytes() == b for p, b in before.items())                        # append-only
    got = dict(query(root, cfg, "SELECT id, accepted_at FROM filings"))
    assert {k: utc(v) for k, v in got.items()} == {k: utc(TRUE[k]) for k in raw}
    (acc, at), = query(root, cfg, "SELECT accession, accepted_at FROM insiders")
    assert utc(at) == utc(TRUE[acc])
    again = run("check_sec_times.py", root, cfg, fx)                                  # already checked: no request
    assert again["checked"] == 0 and again["requests"] == 0 and again["already_checked"] == len(raw)
