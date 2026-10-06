"""SEC acceptance times: the submissions JSON's acceptanceDateTime can be shifted later by the New
York UTC offset (whole file, some CIKs; seen from 2026-10-05); Edgar.recent checks each file
against the SGML header <ACCEPTANCE-DATETIME> (US Eastern) of its newest filing and corrects it,
and stored rows are corrected on read through sec_times (check_sec_times.py, core.database.connect).
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

from marketbrief.sources import sec_filings as sec  # noqa: E402
from marketbrief.sources.sec_acceptance import (EASTERN, et_offset_hours, is_shifted, sgml_acceptance, time_summary,
                                                time_warnings, unshift)  # noqa: E402
from marketbrief.sources.sec_client import Edgar, archive_url  # noqa: E402
from marketbrief.utils.timefmt import format_utc_z, parse_utc_z  # noqa: E402

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
        out[archive_url(cik, acc, f"{acc}.hdr.sgml")] = str(FIX / name)
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
    return Edgar("market-brief tests test@example.com")


# ---------- the rule ----------

def test_header_time_is_eastern_and_converted_to_utc():
    for acc, (_, name) in HEADERS.items():
        assert sgml_acceptance((FIX / name).read_bytes()) == TRUE[acc]
    assert sgml_acceptance(b"<SEC-HEADER>no time</SEC-HEADER>") is None
    # the full submission .txt carries the same tag (YYYYMMDDHHMMSS, Eastern)
    assert sgml_acceptance(b"<SEC-DOCUMENT>x\n<ACCEPTANCE-DATETIME>20260714063038\n") == TRUE["0001628280-26-048078"]


def test_shift_is_the_eastern_offset_and_unshift_inverts_it():
    cases = [("2026-07-14T14:30:38.000Z", TRUE["0001628280-26-048078"]),     # EDT: +4h
             ("2026-10-06T02:42:45.000Z", TRUE["0001140361-26-038674"]),     # EDT, across midnight UTC
             ("2026-02-14T02:20:00.000Z", TRUE["0001628280-26-008131"]),     # EST: +5h
             ("2025-01-31T16:01:27.000Z", TRUE["0000320193-25-000008"])]
    for shifted, true in cases:
        assert is_shifted(shifted, true) and unshift(shifted) == true
    assert not is_shifted(TRUE["0001628280-26-064366"], TRUE["0001628280-26-064366"])
    assert not is_shifted("2026-07-14T15:30:38.000Z", TRUE["0001628280-26-048078"])   # +5h in summer: not the rule
    # the days around both 2026 DST changes (March 8, November 1), at EDGAR hours
    for day in ("2026-03-06", "2026-03-09", "2026-10-30", "2026-11-02"):
        for hh in ("06:00:01", "12:00:00", "21:59:59"):
            true = datetime.fromisoformat(f"{day}T{hh}").replace(tzinfo=EASTERN)
            shifted = true + timedelta(hours=et_offset_hours(true))
            assert unshift(format_utc_z(shifted)) == format_utc_z(true)


# ---------- Edgar.recent ----------

def test_recent_corrects_a_shifted_file_and_keeps_a_right_one(edgar):
    jpm = edgar.recent(CIKS["JPM"])
    assert edgar.requests == 3 and edgar.time_checks == {"19617": "shifted"}
    assert dict(zip(jpm["accessionNumber"], jpm["acceptanceDateTime"])) == {a: TRUE[a] for a in jpm["accessionNumber"]}
    assert jpm["acceptanceDateTimeJson"][1] == "2026-07-14T14:30:38.000Z"            # the served value is kept
    aapl = edgar.recent(CIKS["AAPL"])
    assert dict(zip(aapl["accessionNumber"], aapl["acceptanceDateTime"])) == {a: TRUE[a] for a in aapl["accessionNumber"]}
    tsla = edgar.recent(CIKS["TSLA"])
    assert dict(zip(tsla["accessionNumber"], tsla["acceptanceDateTime"])) == {a: TRUE[a] for a in tsla["accessionNumber"]}
    assert "acceptanceDateTimeJson" not in tsla and edgar.requests == 9               # newest + oldest header per CIK
    assert time_summary(edgar) == {"ok": 1, "shifted": ["19617", "320193"], "unverified": {}}
    edgar.recent(CIKS["JPM"])                                                         # header cached: no request
    assert edgar.requests == 10
    # sec.filings (insiders, stakes, holdings, fundamentals) and the merged lists carry the fix
    f = sec.filings_of_forms(jpm, {"8-K"})
    assert f[0]["accepted_at"] == TRUE["0001628280-26-048078"]
    merged, failed = sec.ticker_submissions(edgar, "JPM", CIKS["JPM"], {"JPM": [CIKS["TSLA"]]})
    assert failed == [] and set(merged["acceptanceDateTime"]) == {TRUE[a] for a in merged["accessionNumber"]}


def test_unexplained_difference_or_missing_header_is_unverified_and_kept(tmp_path, monkeypatch):
    other = {**HEADERS, "0001140361-26-038674": (320193, "hdr_tsla_8k_0001628280-26-064366.sgml")}   # wrong time
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures(tmp_path / "a", other)))
    e = Edgar("t t@example.com")
    raw = json.loads((FIX / "submissions_aapl_trimmed.json").read_text())["filings"]["recent"]
    assert e.recent(CIKS["AAPL"])["acceptanceDateTime"] == raw["acceptanceDateTime"]
    assert e.time_checks["320193"].startswith("unverified: 0001140361-26-038674 JSON")
    no_hdr = {k: v for k, v in HEADERS.items() if v[0] != CIKS["AAPL"]}
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures(tmp_path / "b", no_hdr)))
    e = Edgar("t t@example.com")
    assert e.recent(CIKS["AAPL"])["acceptanceDateTime"] == raw["acceptanceDateTime"] and e.requests == 1
    assert time_summary(e) == {"ok": 0, "shifted": [], "unverified": {"320193": "no header fixture"}}


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
    code = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import json; from marketbrief.core.database import connect; "
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
    from marketbrief.collectors import event_timing, events_sec
    from marketbrief.sources import sec_acceptance
    _, _, fx = setup(tmp_path)
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fx))
    cfg = {"market": "us", "calendar": "XNYS", "timezone": "America/New_York"}
    reports, times = {}, {}
    rows, failed = events_sec.sec_earnings(cfg, {"JPM": {}}, "t t@example.com", reports, times)
    assert failed == [] and rows == {"JPM": [(date(2026, 7, 14), "before_open", 0)]}
    assert event_timing.timing(cfg, pd.Timestamp("2026-07-14T14:30:38Z")) == (date(2026, 7, 14), "during")   # the JSON's
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


# ---------- round 2: mixed files, warnings, several checks per accession, ai_replay ----------

def mixed_fixtures(d: Path, which: str) -> Path:
    """AAPL's trimmed list with one end set to its true time: `which` = "oldest" (newest shifted,
    oldest right) or "newest" (newest right, oldest shifted)."""
    fx = fixtures(d)
    sub = json.loads((FIX / "submissions_aapl_trimmed.json").read_text())
    rec = sub["filings"]["recent"]
    k = -1 if which == "oldest" else 0
    rec["acceptanceDateTime"][k] = TRUE[rec["accessionNumber"][k]]
    (fx / "sub_aapl_mixed.json").write_text(json.dumps(sub))
    u = json.loads((fx / "urls.json").read_text())
    u[f"https://data.sec.gov/submissions/CIK{CIKS['AAPL']:010d}.json"] = "sub_aapl_mixed.json"
    (fx / "urls.json").write_text(json.dumps(u, indent=1))
    return fx


@pytest.mark.parametrize("which", ["oldest", "newest"])
def test_mixed_file_is_unverified_and_never_unshifted(tmp_path, monkeypatch, which):
    """A file with one right and one shifted end: unshifting it would move the right values 4-5h
    EARLIER (look-ahead), so it is kept as served and reported."""
    fx = mixed_fixtures(tmp_path / "sec", which)
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fx))
    e = Edgar("t t@example.com")
    served = json.loads((fx / "sub_aapl_mixed.json").read_text())["filings"]["recent"]["acceptanceDateTime"]
    rec = e.recent(CIKS["AAPL"])
    assert rec["acceptanceDateTime"] == served and "acceptanceDateTimeJson" not in rec
    assert e.time_checks["320193"].startswith("unverified: mixed file") and e.requests == 3
    assert all(parse_utc_z(v) >= parse_utc_z(TRUE[a]) for a, v in zip(rec["accessionNumber"], rec["acceptanceDateTime"]))
    w = time_warnings(e)
    assert len(w) == 1 and "CIK 320193 unverified" in w[0] and "mixed file" in w[0]
    assert time_warnings(time_summary(e)) == w


def test_collectors_put_unverified_ciks_in_warnings(tmp_path):
    root, cfg, _ = setup(tmp_path)
    fx = mixed_fixtures(tmp_path / "sec_mixed", "oldest")
    out = run("collect_filings.py", root, cfg, fx)
    assert out["sec_times"]["shifted"] == ["19617"] and list(out["sec_times"]["unverified"]) == ["320193"]
    assert len(out["warnings"]) == 1 and out["warnings"][0].startswith("SEC acceptance times of CIK 320193 unverified")
    clean_root, clean_cfg, clean_fx = setup(tmp_path / "clean")
    assert run("collect_filings.py", clean_root, clean_cfg, clean_fx)["warnings"] == []


def test_events_summary_warns_about_unverified_ciks(tmp_path, monkeypatch):
    from marketbrief.collectors import event_timing, events_sec
    from marketbrief.sources import sec_acceptance
    fx = mixed_fixtures(tmp_path / "sec", "oldest")
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fx))
    times: dict = {}
    events_sec.sec_earnings({"market": "us", "calendar": "XNYS", "timezone": "America/New_York"},
                    {"AAPL": {}, "JPM": {}}, "t t@example.com", {}, times)
    assert times["shifted"] == ["19617"] and list(times["unverified"]) == ["320193"]
    w = sec_acceptance.time_warnings(times)
    assert len(w) == 1 and w[0].startswith("SEC acceptance times of CIK 320193 unverified, stored as served")


def test_several_checks_per_accession_keep_row_counts(tmp_path):
    root, cfg, fx_none = setup(tmp_path, headers={})
    run("collect_filings.py", root, cfg, fx_none)
    n = len(query(root, cfg, "SELECT id FROM filings"))
    acc = "0001140361-26-038674"
    d = root / "data" / MARKET / "sec_times" / "2026" / "10"
    d.mkdir(parents=True)
    rows = [{"accession": acc, "cik": "320193", "accepted_at": at, "json_accepted_at": "2026-10-06T02:42:45.000Z",
             "source": "sgml_header", "checked_at": chk}
            for at, chk in (("2026-10-05T21:00:00Z", "2026-10-06T01:00:00Z"),        # older check
                            (TRUE[acc], "2026-10-07T01:00:00Z"),                       # newest check wins
                            ("2026-10-05T20:00:00Z", "2026-10-06T02:00:00Z"))]
    (d / "2026-10-07.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    got = query(root, cfg, "SELECT id, accepted_at FROM filings")
    assert len(got) == n and utc(dict(got)[acc]) == utc(TRUE[acc])
    assert len(query(root, cfg, "SELECT id FROM filings WHERE id = '0001628280-26-064366'")) == 1


def test_ai_replay_filters_sec_rows_by_the_header_time(tmp_path):
    """The as-of copy keeps a filing stored 4h late (02:42Z) when its header time (22:42Z the day
    before) is before the cutoff, and copies only the sec_times rows accepted by the cutoff."""
    import ai_replay
    src = tmp_path / "src"
    base = src / "data" / "us"
    acc = "0001140361-26-038674"
    (base / "filings" / "2026" / "10").mkdir(parents=True)
    (base / "filings" / "2026" / "10" / "2026-10-06.jsonl").write_text(
        json.dumps({"id": acc, "ticker": "AAPL", "cik": "320193", "form": "4", "filing_date": "2026-10-05",
                    "accepted_at": "2026-10-06T02:42:45.000Z", "first_seen_at": "2026-10-06T03:00:00+00:00"}) + "\n")
    cutoff = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
    out = ai_replay.copy_asof("us", src, tmp_path / "no_fix", date(2026, 10, 5), cutoff)
    assert out["kinds"]["filings"]["rows_kept"] == 0                                    # raw time: after the cutoff
    (base / "sec_times" / "2026" / "10").mkdir(parents=True)
    (base / "sec_times" / "2026" / "10" / "2026-10-07.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"accession": acc, "cik": "320193", "accepted_at": TRUE[acc], "json_accepted_at": "2026-10-06T02:42:45.000Z",
         "source": "sgml_header", "checked_at": "2026-10-07T01:00:00Z"},
        {"accession": "9999999999-26-000001", "cik": "1", "accepted_at": "2026-10-06T13:00:00.000Z",
         "json_accepted_at": "2026-10-06T17:00:00.000Z", "source": "sgml_header", "checked_at": "2026-10-07T01:00:00Z"}]))
    dst = tmp_path / "fixed"
    out = ai_replay.copy_asof("us", src, dst, date(2026, 10, 5), cutoff)
    assert out["kinds"]["filings"]["rows_kept"] == 1 and "sec_times" not in out["excluded"]
    assert out["kinds"]["sec_times"]["rows_kept"] == 1                                  # a later filing's time is not copied
    copied = [json.loads(x) for f in (dst / "data" / "us" / "sec_times").glob("**/*.jsonl") for x in f.read_text().splitlines()]
    assert [r["accession"] for r in copied] == [acc]
    assert "SGML header" in out["kinds"]["filings"]["rule"]
    # the correction can also move a row out: a header time after the cutoff wins over an earlier stored one
    assert ai_replay.keep_row("filings", {"id": acc, "accepted_at": "2026-10-05T12:00:00Z"}, date(2026, 10, 4),
                              pd.Timestamp("2026-10-05T13:00:00Z"), {acc: TRUE[acc]}) is False
