"""AI replay harness (scripts/ai_replay.py): the sample dates, prepare's strict as-of copy (the
context pack and ranges do not change when every row after the cutoff is perturbed), record's
validation of forecaster calls, and scoring on a synthetic case.
Run: pytest -q"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.replay.ai_replay import ai_html
from marketbrief.replay.ai_replay import backfill
from marketbrief.replay.ai_replay import copy_asof
from marketbrief.replay.ai_replay import cutoff
from marketbrief.replay.ai_replay import summaries  # noqa: E402
from marketbrief.utils.numbers import round_or_none  # noqa: E402
from marketbrief.core.clock import freeze_sql, utc_now, utc_today  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core import calendar as ev  # noqa: E402
from marketbrief.core.horizons import horizons  # noqa: E402
from marketbrief.replay.rule_replay import replay_statistics  # noqa: E402
from test_pipeline import MARKET, SCRIPTS, fat_tailed_walk, setup, write_bars  # noqa: E402

XNYS = {"market": MARKET, "calendar": "XNYS", "timezone": "America/New_York"}
D = date(2026, 8, 14)                 # a Friday; the next session is Monday 2026-08-17
CUT = "2026-08-17T12:15:00+00:00"     # testmkt: 75 min before the 09:30 ET open


def sessions(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if ev.is_session(XNYS, d):
            out.append(d)
        d += timedelta(days=1)
    return out


def jl(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    p = root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def filing(i: str, ticker: str, accepted: str | None, filing_date: str, desc: str) -> dict:
    return {"id": i, "ticker": ticker, "cik": "1", "form": "8-K", "filing_date": filing_date, "accepted_at": accepted,
            "description": desc, "url": f"https://www.sec.gov/{i}", "first_seen_at": "2026-10-05T14:00:00+00:00"}


def insider(i: str, accepted: str, tdate: str, code: str, shares: float) -> dict:
    return {"id": i, "accession": i, "line": 1, "ticker": "MSFT", "issuer_cik": "1", "form": "4",
            "filing_date": accepted[:10], "accepted_at": accepted, "insider_name": "A. Person", "role": "CEO",
            "is_director": False, "is_officer": True, "is_ten_pct_owner": False, "derivative": False,
            "security": "Common", "transaction_date": tdate, "code": code, "acquired_disposed": "D" if code == "S" else "A",
            "shares": shares, "price": 100.0, "value": shares * 100.0, "shares_after": 1e6, "ownership": "D",
            "plan_10b5_1": False, "url": "https://www.sec.gov/x", "first_seen_at": "2026-10-05T14:00:00+00:00"}


def fund(i: str, accepted: str, value: float) -> dict:
    return {"id": i, "ticker": "MSFT", "cik": "1", "concept": "shares_outstanding", "tag": "dei:Shares", "tag_rank": 0,
            "unit": "shares", "period_start": None, "period_end": "2026-06-30", "period": "instant",
            "fiscal_year": 2026, "fiscal_period": "Q2", "form": "10-Q", "accession": i, "filing_date": accepted[:10],
            "accepted_at": accepted, "value": value, "prev_value": None, "first_seen_at": "2026-10-05T14:00:00+00:00"}


def build_source(tmp: Path, perturb: bool = False, perturb_before: bool = False) -> tuple[Path, Path]:
    """A source root with every kind of row on both sides of the cutoff. perturb=True changes every
    row that became public after the cutoff (prices after D, late filings, quotes, events, ...) and adds
    more such rows; perturb_before=True changes a row that was public before it (a negative control)."""
    root, cfg = setup(tmp)
    mk = cfg / "markets" / f"{MARKET}.yaml"
    mk.write_text(mk.read_text().replace("  MSFT: {name: Microsoft}\n",
                                         "  MSFT: {name: Microsoft}\n  NFLX: {name: Netflix}\n") + "filings: sec\n")
    rng = np.random.default_rng(11)
    days = sessions(date(2025, 9, 2), date(2026, 9, 30))
    n = len(days)
    bench = fat_tailed_walk(rng, n, 100, 0.01)
    series = {"BENCH": bench, "VOLX": list(18 + 3 * np.abs(np.array(fat_tailed_walk(rng, n, 1, 0.05)) - 1)),
              "AAPL": list(1.5 * np.array(bench) * np.array(fat_tailed_walk(rng, n, 1, 0.011))),
              "MSFT": list(2.0 * np.array(bench) * np.array(fat_tailed_walk(rng, n, 1, 0.012)))}
    k = days.index(D)
    if perturb:   # every bar after D: a different path
        for t in series:
            series[t] = series[t][:k + 1] + [v * float(f) for v, f in
                                            zip(series[t][k + 1:], rng.uniform(0.5, 1.5, n - k - 1))]
    if perturb_before:
        series["MSFT"] = series["MSFT"][:k] + [series["MSFT"][k] * 1.07] + series["MSFT"][k + 1:]
    write_bars(root, series, days)
    late = "LATE-CHANGED" if perturb else "late"
    jl(root, "filings", "2026-10-05", [
        filing("0001-26-000001", "MSFT", "2026-08-14T20:30:00.000Z", "2026-08-14", "after the close on D"),
        filing("0001-26-000002", "AAPL", "2026-08-17T12:00:00.000Z", "2026-08-17", "pre-open, before the cutoff"),
        filing("0001-26-000003", "MSFT", None, "2026-08-16", "no acceptance time, filed the day before"),
        filing("0001-26-000004", "MSFT", "2026-08-17T13:00:00.000Z", "2026-08-17", late),
        filing("0001-26-000005", "AAPL", None, "2026-08-17", late),
        filing("0001-26-000006", "MSFT", "2026-09-02T13:00:00.000Z", "2026-09-02", late)]
        + ([filing("0001-26-000099", "MSFT", "2026-08-17T12:16:00.000Z", "2026-08-17", "added late")] if perturb else []))
    jl(root, "announcements", "2026-10-05", [
        {"id": "nse-ann-1", "ticker": "MSFT", "company": "M", "published_at": "2026-08-16T10:00:00+00:00",
         "category": "General", "subject": "before", "url": "u", "source": "nse", "first_seen_at": "2026-10-05T14:00:00+00:00"},
        {"id": "nse-ann-2", "ticker": "MSFT", "company": "M", "published_at": "2026-08-17T13:00:00+00:00",
         "category": "General", "subject": late, "url": "u", "source": "nse", "first_seen_at": "2026-10-05T14:00:00+00:00"}])
    jl(root, "events", "2026-08-01", [
        {"id": "AAPL-earnings-2026-08-18", "date": "2026-08-18", "type": "earnings", "ticker": "AAPL",
         "name": "Apple earnings", "source": "yfinance", "first_seen_at": "2026-08-01T12:00:00+00:00"}])
    jl(root, "events", "2026-10-05", [
        {"id": "MSFT-earnings-x", "date": "2026-08-17" if perturb else "2026-08-25", "type": "earnings", "ticker": "MSFT",
         "name": "Microsoft earnings", "source": "yfinance", "first_seen_at": "2026-10-05T14:00:00+00:00"},
        {"id": "AAPL-earnings-h1", "date": "2026-07-30", "type": "earnings", "ticker": "AAPL", "name": "Apple earnings",
         "source": "yfinance_history", "first_seen_at": "2026-10-05T14:00:00+00:00", "timing": "after_close"},
        {"id": "AAPL-earnings-h2", "date": "2026-08-20" if not perturb else "2026-08-18", "type": "earnings",
         "ticker": "AAPL", "name": "Apple earnings", "source": "yfinance_history",
         "first_seen_at": "2026-10-05T14:00:00+00:00", "timing": "before_open"},
        {"id": "MSFT-div-h", "date": "2026-08-19", "type": "ex_dividend", "ticker": "MSFT", "name": "MSFT ex-div",
         "source": "yfinance_history", "first_seen_at": "2026-10-05T14:00:00+00:00", "amount": 9.0 if perturb else 0.8}])
    jl(root, "quotes", "2026-08-17", [
        {"symbol": "VOLX", "yahoo": "^V", "ts": "2026-08-17T11:00:00+00:00", "price": 21.0, "prev_close": 20.0,
         "change_pct": 0.05, "collected_at": "2026-08-17T11:00:00+00:00"},
        {"symbol": "VOLX", "yahoo": "^V", "ts": "2026-08-17T14:00:00+00:00", "price": 80.0 if perturb else 40.0,
         "prev_close": 20.0, "change_pct": 3.0 if perturb else 1.0, "collected_at": "2026-08-17T14:00:00+00:00"},
        {"symbol": "MSFT", "yahoo": "MSFT", "ts": "2026-08-17T13:31:00+00:00", "price": 1.0, "prev_close": 2.0,
         "change_pct": -0.5 if perturb else -0.2, "collected_at": "2026-08-17T13:31:00+00:00"}])
    jl(root, "insiders", "2026-10-05", [insider("ins-1", "2026-08-12T21:00:00+00:00", "2026-08-10", "P", 1000),
                                        insider("ins-2", "2026-08-17T20:00:00+00:00", "2026-08-14", "S",
                                                900000 if perturb else 5000)])
    jl(root, "fundamentals", "2026-10-05", [fund("acc-1", "2026-07-30T20:00:00+00:00", 7.4e9),
                                            fund("acc-2", "2026-08-20T20:00:00+00:00", 9.9e9 if perturb else 7.5e9)])
    jl(root, "deals", "2026-10-05", [
        {"id": "nse-bulk-d", "date": str(D), "ticker": "MSFT", "deal_type": "bulk", "client": "A", "side": "buy",
         "shares": 1e6, "price": 10.0, "value": 1e7, "remarks": None, "source": "nse_historical",
         "first_seen_at": "2026-10-05T14:00:00+00:00"},
        {"id": "nse-bulk-late", "date": "2026-08-17", "ticker": "MSFT", "deal_type": "bulk", "client": "B",
         "side": "sell", "shares": 9e6 if perturb else 2e6, "price": 10.0, "value": 2e7, "remarks": None,
         "source": "nse_historical", "first_seen_at": "2026-10-05T14:00:00+00:00"}])
    jl(root, "news", "2026-08-14", [{"id": "n1", "title": "Apple news" + (" X" if perturb else ""), "url": "u",
                                     "source": "s", "published_at": "2026-08-14T15:00:00+00:00",
                                     "first_seen_at": "2026-08-14T15:05:00+00:00", "feed": "f", "category": "general",
                                     "tickers": ["AAPL"]}])
    jl(root, "predictions", "2026-08-10", [
        {"id": "2026-08-07-MSFT-5d", "made_at": "2026-08-10T12:00:00+00:00", "as_of_date": "2026-08-07", "ticker": "MSFT",
         "horizon_days": 5, "direction": "up", "confidence": 0.6, "rationale": "r", "evidence_ids": ["x"],
         "prompt_version": "forecast-v7", "range_widen": None}])
    jl(root, "outcomes", "2026-08-15", [
        {"prediction_id": "2026-08-07-MSFT-5d", "scored_at": "2026-08-15T10:00:00+00:00", "base_date": "2026-08-07",
         "base_close": 1.0, "target_date": "2026-08-14", "target_close": 1.1, "actual_return": 0.1, "hit": True}])
    jl(root, "predictions", "2026-08-17", [
        {"id": "2026-08-14-AAPL-5d", "made_at": "2026-08-17T12:40:00+00:00", "as_of_date": "2026-08-14", "ticker": "AAPL",
         "horizon_days": 5, "direction": "down" if perturb else "up", "confidence": 0.7, "rationale": "r",
         "evidence_ids": ["x"], "prompt_version": "forecast-v7", "range_widen": 0.5 if perturb else 0.0}])
    jl(root, "outcomes", "2026-08-21", [
        {"prediction_id": "2026-08-14-AAPL-5d", "scored_at": "2026-08-21T22:00:00+00:00", "base_date": "2026-08-14",
         "base_close": 1.0, "target_date": "2026-08-21", "target_close": 0.9, "actual_return": -0.1, "hit": perturb}])
    return root, cfg


def prepare(src: Path, cfg: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(src), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET}
    env.pop("MB_NOW", None)
    return subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "prepare", "--market", MARKET,
                           "--date", str(D), "--root", str(out), *extra],
                          cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)


def outputs(root: Path) -> dict:
    def rows(kind: str) -> list[dict]:
        out = []
        for f in sorted((root / "data" / MARKET / kind).glob("**/*.jsonl")):
            out += [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
        return sorted(out, key=lambda r: r["id"])
    meta = json.loads((root / "ai_replay.json").read_text())
    return {"context": (root / "work" / "context.md").read_text(), "ranges": rows("ranges"),
            "features": rows("features"), "regime": rows("regime"), "calibration": rows("calibration"),
            "kept": {k: v["rows_kept"] for k, v in meta["included"].items()},
            "evidence": meta["citable_evidence"]}


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ai_replay")
    res = {}
    from concurrent.futures import ThreadPoolExecutor
    built = {name: build_source(tmp / f"src_{name}", **kw)
             for name, kw in (("base", {}), ("perturbed", {"perturb": True}), ("control", {"perturb_before": True}))}
    with ThreadPoolExecutor(len(built)) as pool:       # the three independent prepare runs side by side
        runs = {name: pool.submit(prepare, src, cfg, tmp / f"r_{name}") for name, (src, cfg) in built.items()}
    for name, (src, cfg) in built.items():
        p = runs[name].result()
        assert p.returncode == 0, p.stderr
        res[name] = {"src": src, "cfg": cfg, "root": tmp / f"r_{name}", "summary": json.loads(p.stdout)}
    res["tmp"] = tmp
    return res


def test_prepare_no_look_ahead(prepared):
    base, pert = outputs(prepared["base"]["root"]), outputs(prepared["perturbed"]["root"])
    # the perturbation really changed the source after the cutoff ...
    assert prepared["base"]["summary"]["included"]["filings"]["rows_in"] + 1 == \
        prepared["perturbed"]["summary"]["included"]["filings"]["rows_in"]
    # ... yet the context pack, ranges, indicators, regime and calibration are byte-for-byte the same
    assert base["context"] == pert["context"]
    assert base["ranges"] == pert["ranges"] and len(base["ranges"]) == 2 * len(horizons())   # AAPL, MSFT x N+k
    assert base["features"] == pert["features"] and base["regime"] == pert["regime"]
    assert base["calibration"] == pert["calibration"]
    assert base["kept"] == pert["kept"] and base["evidence"] == pert["evidence"]
    # negative control: changing D's own close (known before the cutoff) does change them
    ctrl = outputs(prepared["control"]["root"])
    assert ctrl["context"] != base["context"] and ctrl["ranges"] != base["ranges"]


def test_prepare_keeps_exactly_what_was_public(prepared):
    s, root = prepared["base"]["summary"], prepared["base"]["root"]
    assert s["cutoff_utc"] == CUT and s["session_date"] == "2026-08-17" and s["as_of_date"] == str(D)
    ctx = (root / "work" / "context.md").read_text()
    assert ctx.startswith("# Context pack: Test market, 2026-08-17 (UTC)")
    # filings: accepted before the cutoff (or filed the day before, no acceptance time) are kept
    for i in ("0001-26-000001", "0001-26-000002", "0001-26-000003", "nse-ann-1"):
        assert i in ctx
    for i in ("0001-26-000004", "0001-26-000005", "0001-26-000006", "nse-ann-2"):
        assert i not in ctx
    inc = s["included"]
    assert inc["filings"]["rows_kept"] == 3 and inc["announcements"]["rows_kept"] == 1
    assert inc["events"]["rows_kept"] == 2         # the live AAPL row seen 08-01 and the past (history) one
    assert inc["quotes"]["rows_kept"] == 1 and inc["insiders"]["rows_kept"] == 1
    assert inc["fundamentals"]["rows_kept"] == 1 and inc["predictions"]["rows_kept"] == 1
    assert inc["outcomes"]["rows_kept"] == 1
    assert inc["deals"]["rows_kept"] == 1 and any("deals" in a for a in s["assumptions"])   # dated <= D only
    assert s["upcoming_earnings"] == {"with_days_to_earnings": {"AAPL": 1}, "earnings_within_1_day": ["AAPL"],
                                      "blocked": ["NFLX"]}
    assert "news" in s["excluded"] and "news" not in inc and not (root / "data" / MARKET / "news").exists()
    assert s["citable_evidence"]["total"] == 4
    last = max(f.stem for f in (root / "data" / MARKET / "prices").glob("**/*.csv"))
    assert last == str(D)
    feats = {r["ticker"]: r for r in outputs(root)["features"]}
    assert feats["AAPL"]["days_to_earnings"] == 1 and feats["MSFT"]["days_to_earnings"] is None
    assert feats["NFLX"]["quality"] == "BLOCKED"
    assert all(r["made_at"] == CUT for r in outputs(root)["ranges"])
    kept = (root / "data" / MARKET / "fundamentals" / "2026" / "10" / "2026-10-05.jsonl").read_text()
    assert "acc-1" in kept and "acc-2" not in kept     # the restated value was accepted later
    assert "| MSFT | 2026-08-10 | A. Person | CEO | P |" in ctx and "| S |" not in ctx   # insider sale filed later


def test_prepare_refuses_unsafe_roots_and_training_period(prepared, tmp_path):
    src, cfg = prepared["base"]["src"], prepared["base"]["cfg"]
    p = prepare(src, cfg, prepared["base"]["root"])
    assert p.returncode != 0 and "--force" in p.stderr
    other = tmp_path / "busy"
    other.mkdir()
    (other / "x.txt").write_text("keep me")
    p = prepare(src, cfg, other)
    assert p.returncode != 0 and (other / "x.txt").exists()
    env = {**os.environ, "MB_ROOT": str(src), "MB_CONFIG": str(cfg)}
    p = subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "prepare", "--market", MARKET, "--date",
                        "2026-06-30", "--root", str(tmp_path / "early")], cwd=SCRIPTS, env=env,
                       capture_output=True, text=True, check=False)
    assert p.returncode != 0 and "training" in p.stderr


def call(ticker="MSFT", h=5, conf=0.6, ev_ids=("0001-26-000001",), **kw) -> dict:
    r = {"id": f"{D}-{ticker}-{h}d", "made_at": "2026-10-06T08:00:00+00:00", "as_of_date": str(D), "ticker": ticker,
         "horizon_days": h, "direction": "up", "confidence": conf, "rationale": "Filing after the close.",
         "evidence_ids": list(ev_ids), "prompt_version": "forecast-v7", "range_widen": None}
    r.update(kw)
    return r


def record(prepared, rows: list, results: Path, root: Path | None = None) -> subprocess.CompletedProcess:
    f = results.parent / "calls.jsonl"
    f.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in rows))
    env = {**os.environ, "MB_ROOT": str(prepared["base"]["src"]), "MB_CONFIG": str(prepared["base"]["cfg"])}
    root = root or prepared["base"]["root"]
    return subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "record", "--market", MARKET, "--date",
                           str(D), "--root", str(root), "--calls", str(f), "--results", str(results)],
                          cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)


def test_record_applies_the_news_status_rules_as_of_the_cutoff(prepared, tmp_path):
    """Issue #39: with status rows in the replay root by the cutoff, record applies the daily gate's
    news-verification rules: a filing that confirms the ticker's event is main evidence, an announcement no
    status row confirms is unverified (NEWS_STATUS_MAIN); a status row after the cutoff is not seen."""
    root = tmp_path / "root"
    shutil.copytree(prepared["base"]["root"], root)
    base = {"cluster_row_id": "r", "claim_id": None, "level": "cluster", "ticker": "MSFT", "outlet_ids": [],
            "mismatch_ids": [], "status_ids": [], "id_statuses": [], "independent_origins": 1,
            "unread_vetted_origins": 0, "origins": [], "conflicts": [], "flags": [], "confirmed_at": None,
            "state_hash": "h", "method_version": "nv-b1"}
    rows = [{**base, "id": "MSFT-a|*@1", "as_of": "2026-08-17T10:00:00+00:00", "cluster_id": "MSFT-a",
             "status": "confirmed_primary", "primary_ids": ["0001-26-000001"],
             "first_reported_at": "2026-08-17T10:00:00+00:00", "inputs_until": "2026-08-17T10:00:00+00:00"},
            {**base, "id": "MSFT-b|*@2", "as_of": "2026-08-17T13:00:00+00:00", "cluster_id": "MSFT-b",
             "status": "confirmed_primary", "primary_ids": ["nse-ann-1"],             # after the cutoff
             "first_reported_at": "2026-08-17T13:00:00+00:00", "inputs_until": "2026-08-17T13:00:00+00:00"}]
    path = root / "data" / MARKET / "news_verified" / "2026" / "08" / "2026-08-17.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    results = tmp_path / "results"
    p = record(prepared, [call(), call(h=1, ev_ids=("nse-ann-1",), direction="down", conf=0.55)], results, root)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["recorded"] == 1
    [rejected] = out["rejected"]
    assert rejected["line"] == 2 and rejected["reasons"][0].startswith("NEWS_STATUS_MAIN: main evidence nse-ann-1 is "
                                                                       "unverified")
    day = json.loads((results / MARKET / "days.jsonl").read_text())
    assert day["news_status_rules"] is True and day["n_calls"] == 1


def test_record_validation(prepared, tmp_path):
    results = tmp_path / "results"
    good = call()
    rows = [good,
            call(h=1, ev_ids=("nse-ann-1",), direction="down", conf=0.55),            # valid too
            dict(good),                                                               # duplicate id
            call(id=f"{D}-MSFT-5", h=5),                                              # bad id
            call(ticker="MSFT", h=max(horizons()) + 1, id=f"{D}-MSFT-{max(horizons()) + 1}d"),   # not configured
            call(ticker="AAPL", conf=0.95),                                           # confidence too high
            call(ticker="AAPL", conf=0.45),                                           # too low
            call(ticker="AAPL", ev_ids=("0001-26-000004",)),                          # filed after the cutoff
            call(ticker="AAPL", ev_ids=("no-such-id",)),                              # unknown id
            call(ticker="AAPL", ev_ids=()),                                           # no evidence
            call(ticker="AAPL", h=1, id=f"{D}-AAPL-1d"),                              # earnings within 1 day
            call(ticker="NFLX"),                                                      # BLOCKED
            call(ticker="ZZZ"),                                                       # not in the watchlist
            call(as_of_date="2026-08-13", id="2026-08-13-MSFT-1d", h=1),              # wrong date
            call(ticker="MSFT", h=1, id=f"{D}-MSFT-1d", direction="flat"),            # bad direction
            call(range_widen=0.7),                                                    # widen too large
            call(foo=1),                                                              # unknown field
            "{not json"]
    p = record(prepared, rows, results)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["recorded"] == 2
    reasons = {r["line"]: " ".join(r["reasons"]) for r in out["rejected"]}
    expect = {3: "already recorded", 4: "id must be", 5: "horizon_days", 6: "confidence", 7: "confidence",
              8: "not in the replay root", 9: "not in the replay root", 10: "evidence_ids", 11: "earnings within 1 day",
              12: "BLOCKED", 13: "unknown ticker", 14: "not the replay date", 15: "direction", 16: "range_widen",
              17: "unknown field", 18: "not JSON"}
    assert set(reasons) == set(expect)
    for line, word in expect.items():
        assert word in reasons[line], (line, reasons[line])
    stored = [json.loads(x) for x in (results / MARKET / "calls.jsonl").read_text().splitlines()]
    assert [s["id"] for s in stored] == [f"{D}-MSFT-5d", f"{D}-MSFT-1d"]
    assert all(s["replay"] is True and s["prompt_version"] == "forecast-v7" and s["made_at"] == CUT for s in stored)
    day = json.loads((results / MARKET / "days.jsonl").read_text())
    assert day["eligible"] == ["MSFT"] and day["n_calls"] == 2 and day["n_rejected"] == 16
    assert day["news_status_rules"] is False                     # no status rows in the root: rules not applied
    # nothing went to the real predictions, and a day is recorded once
    assert not (prepared["base"]["root"] / "data" / MARKET / "predictions" / "2026" / "08" / "2026-08-17.jsonl").exists()
    assert not list((prepared["base"]["src"] / "data" / MARKET / "predictions").glob("**/2026-10-*.jsonl"))
    p = record(prepared, [], results)
    assert p.returncode != 0 and "already recorded" in p.stderr


def bars_from(closes: dict[str, list[float]], days: list[date]) -> dict:
    return {t: pd.DataFrame({"close": c}, index=pd.to_datetime(days)) for t, c in closes.items()}


def test_score_synthetic():
    days = sessions(date(2026, 7, 1), date(2026, 8, 31))
    n = len(days)
    up = [100 * 1.01 ** i for i in range(n)]            # rises every session
    down = [100 * 0.99 ** i for i in range(n)]          # falls every session
    flat = [100.0] * n                                  # never moves: every call misses
    bars = bars_from({"UP": up, "DN": down, "FL": flat}, days)
    cfg = {"market": "syn", "name": "Synthetic"}
    sample = days[20:40:5]                              # 4 as-of days
    calls, rec = [], []
    for d in sample:
        calls += [{"id": f"{d}-UP-5d", "as_of_date": str(d), "ticker": "UP", "horizon_days": 5, "direction": "up",
                   "confidence": 0.8, "prompt_version": "v", "evidence_ids": ["e"]},
                  {"id": f"{d}-DN-1d", "as_of_date": str(d), "ticker": "DN", "horizon_days": 1, "direction": "up",
                   "confidence": 0.55, "prompt_version": "v", "evidence_ids": ["e"]},
                  {"id": f"{d}-FL-5d", "as_of_date": str(d), "ticker": "FL", "horizon_days": 5, "direction": "down",
                   "confidence": 0.65, "prompt_version": "v", "evidence_ids": ["e"]}]
        rec.append({"date": str(d), "n_tickers": 4, "eligible": ["UP", "DN", "FL", "XX"], "n_calls": 3,
                    "n_rejected": 0, "citable_ids": 2})
    last = days[-1]                                     # a call whose 5-day target is not stored yet
    calls.append({"id": f"{last}-UP-5d", "as_of_date": str(last), "ticker": "UP", "horizon_days": 5, "direction": "up",
                  "confidence": 0.7, "prompt_version": "v", "evidence_ids": ["e"]})
    rec.append({"date": str(last), "n_tickers": 4, "eligible": ["UP", "DN", "FL", "XX"], "n_calls": 1,
                "n_rejected": 0, "citable_ids": 1})
    full = summaries.summarize(cfg, calls, rec, bars)
    s = full["fair"]                                    # every sample day is after the training cutoff
    assert full["contaminated"]["n_days"] == 0 and full["contaminated"]["n_calls"] == 0
    assert s["n_calls"] == 13 and s["n_scored"] == 12 and s["n_pending"] == 1
    o = s["overall"]
    assert o["n"] == 12 and o["hits"] == 4                       # only the UP calls hit
    assert o["ci95"] == [round_or_none(x) for x in replay_statistics.wilson(4, 12)]
    assert o["always_up"]["hits"] == 4                           # UP rises; DN falls; FL flat (a miss)
    assert s["by_horizon"]["5"]["n"] == 8 and s["by_horizon"]["5"]["hits"] == 4
    assert s["by_horizon"]["1"]["hit_rate"] == 0.0
    bands = {b["band"]: b for b in s["by_band"]}
    assert bands["0.70-0.90"]["hit_rate"] == 1.0 and bands["0.50-0.59"]["hit_rate"] == 0.0
    assert bands["0.60-0.69"]["n"] == 4 and bands["0.60-0.69"]["hits"] == 0
    assert math.isclose(o["mean_confidence"], (4 * 0.8 + 4 * 0.55 + 4 * 0.65) / 12, abs_tol=1e-4)
    m5 = o["rules"]["momentum_5d"]                               # sign of the last 5 days: UP up, DN down, FL none
    assert m5["n"] == 8 and m5["hits"] == 8 and m5["ai_hit_rate_same_rows"] == 0.5
    ab = s["abstention"]                                         # 5 days x 4 eligible tickers = 20 slots
    assert ab["5d"] == {"slots": 20, "calls": 9, "abstention_rate": round_or_none(11 / 20)}
    assert ab["1d"]["calls"] == 4 and ab["any"]["ticker_days_with_a_call"] == 13
    page = ai_html.html_page(full)
    assert page.count("<svg") == 2 and page.count("<details") >= 5 and len(s["top"]) == 3
    assert "http" not in page.replace("http-equiv", "")          # self-contained


def test_score_cli_on_recorded_calls(prepared, tmp_path):
    results = tmp_path / "results"
    p = record(prepared, [call(), call(ticker="MSFT", h=1, direction="down", ev_ids=("0001-26-000002",))], results)
    assert p.returncode == 0, p.stderr
    env = {**os.environ, "MB_ROOT": str(prepared["base"]["src"]), "MB_CONFIG": str(prepared["base"]["cfg"])}
    out = tmp_path / "page" / "ai-replay.html"
    p = subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "score", "--market", MARKET, "--results",
                        str(results), "--out", str(out)], cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    s = json.loads(out.with_suffix(".json").read_text())["fair"]
    # scored against the source's real closes (the as-of root has no bars after D)
    bars = pd.concat([pd.read_csv(f) for f in sorted((prepared["base"]["src"] / "data" / MARKET / "prices")
                                                     .glob("**/*.csv"))])
    msft = bars[bars["ticker"] == "MSFT"].set_index("date")["close"]
    i = list(msft.index).index(str(D))
    exp5 = msft.iloc[i + 6] > msft.iloc[i]          # N+5: the close of D+5, 6 bars after the as-of close
    exp1 = msft.iloc[i + 2] < msft.iloc[i]          # N+1: the close of D+1
    got = {c["id"]: c["hit"] for c in s["calls"]}
    assert got == {f"{D}-MSFT-5d": bool(exp5), f"{D}-MSFT-1d": bool(exp1)}
    assert s["n_scored"] == 2 and out.exists() and "AI forecaster replay" in out.read_text()


def test_sample_dates_cli():
    for market in ("us", "india"):
        p = subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "dates", "--market", market], cwd=SCRIPTS,
                           capture_output=True, text=True, check=False,
                           env={k: v for k, v in os.environ.items() if k not in ("MB_ROOT", "MB_CONFIG", "MB_NOW")})
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout)
        cfg = load_market(market)
        ds = [date.fromisoformat(x["as_of_date"]) for x in out["dates"]]
        all_sessions = [d for d in (date(2026, 7, 1) + timedelta(days=i) for i in range(87)) if ev.is_session(cfg, d)]
        assert ds == all_sessions[::5] and ds[0] == date(2026, 7, 1) and ds[-1] <= date(2026, 9, 25)
        assert 12 <= len(ds) <= 13 and all(d > cutoff.training_cutoff() for d in ds)
        for x in out["dates"]:       # cutoff: before the next session's open, on that session's date
            s = date.fromisoformat(x["session_date"])
            assert datetime.fromisoformat(x["cutoff_utc"]) < ev.session_open_utc(cfg, s)
            assert s == ev.next_session(cfg, date.fromisoformat(x["as_of_date"]), include=False)
    assert cutoff.cutoff_for(load_market("us"), date(2026, 7, 1)).isoformat() == "2026-07-02T12:15:00+00:00"
    assert cutoff.cutoff_for(load_market("india"), date(2026, 7, 1)).isoformat() == "2026-07-02T02:40:00+00:00"


def test_frozen_clock_sql(monkeypatch):
    at = datetime(2026, 8, 17, 12, 15, tzinfo=timezone.utc)
    sql = "SELECT current_date - 7, CURRENT_DATE, now(), current_timestamp FROM t WHERE x_current_date = 1"
    out = freeze_sql(sql, at)
    assert out.count("DATE '2026-08-17'") == 2 and out.count("TIMESTAMPTZ '2026-08-17T12:15:00+00:00'") == 2
    assert "x_current_date" in out
    monkeypatch.setenv("MB_NOW", "2026-08-17T12:15:00+00:00")
    assert utc_today() == date(2026, 8, 17) and utc_now() == "2026-08-17T12:15:00+00:00"
    con = connect("nomarket")
    assert con.execute("SELECT current_date").fetchone()[0] == date(2026, 8, 17)
    monkeypatch.delenv("MB_NOW")


# ---------- round 2: --source, the earnings assumption, backfill guards, collector --since ----------

REPO = Path(__file__).resolve().parents[1]
REAL_NSE = REPO / "tests" / "fixtures" / "nse" / "real"


def test_prepare_reads_source(prepared, tmp_path):
    """--source S: the data comes from S, whatever MB_ROOT says (here an empty root)."""
    empty = tmp_path / "empty"
    (empty / "data").mkdir(parents=True)
    out = tmp_path / "r_source"
    p = prepare(empty, prepared["base"]["cfg"], out, "--source", str(prepared["base"]["src"]))
    assert p.returncode == 0, p.stderr
    a, b = outputs(prepared["base"]["root"]), outputs(out)
    assert a["context"] == b["context"] and a["ranges"] == b["ranges"] and a["kept"] == b["kept"]
    assert json.loads(p.stdout)["source_root"] == str(prepared["base"]["src"])
    p = prepare(empty, prepared["base"]["cfg"], tmp_path / "r_empty")       # no --source: MB_ROOT's empty data
    assert p.returncode != 0 and "no BENCH bar" in p.stderr


def test_assumed_earnings_are_opt_in_and_labelled(prepared, tmp_path):
    out = tmp_path / "r_assumed"
    p = prepare(prepared["base"]["src"], prepared["base"]["cfg"], out, "--assume-earnings-known", "14")
    assert p.returncode == 0, p.stderr
    s = json.loads(p.stdout)
    assert s["assumptions"][0].startswith("ASSUMED") and "MSFT 2026-08-25" in s["assumptions"][0]
    assert s["upcoming_earnings"]["with_days_to_earnings"]["MSFT"] == 8      # 2026-08-25 - session 2026-08-17
    assert "ASSUMED known in advance" in (out / "work" / "context.md").read_text()
    assert not any("earnings" in a for a in prepared["base"]["summary"]["assumptions"])   # off by default


def test_backfill_refuses_real_data(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("MB_ROOT", "MB_CONFIG", "MB_NOW")}
    checkout = tmp_path / "checkout"                     # another market-brief checkout (e.g. a worktree's main clone)
    for d in ("config/markets", "scripts", "data/us"):
        (checkout / d).mkdir(parents=True)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("x")
    for bad in (REPO, REPO / "data", REPO / "data" / "us" / "x", REPO.parent, checkout / "data" / "x", busy):
        p = subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "backfill", "--market", "us", "--source",
                            str(bad), "--since", "2026-06-01"], cwd=SCRIPTS, env=env, capture_output=True, text=True,
                           check=False)
        assert p.returncode != 0 and "--source" in p.stderr, (bad, p.stderr)
    assert not (REPO / "data" / "us" / "x").exists() and not (checkout / "data" / "x").exists()
    assert sorted(x.name for x in busy.iterdir()) == ["keep.txt"]


def test_backfill_config_overrides_scratch_copy_only(tmp_path):
    import yaml
    shutil.copytree(REPO / "config", tmp_path / "config")
    before = (REPO / "config" / "markets" / "us.yaml").read_text()
    changed = backfill.backfill_config(tmp_path / "config", "us", date(2026, 6, 1), date(2026, 10, 5))
    assert changed == {"filing_lookback_days": 127, "relationships.insiders.lookback_days": 127,
                       "relationships.stakes.lookback_days": 127}
    cfg = yaml.safe_load((tmp_path / "config" / "markets" / "us.yaml").read_text())
    assert cfg["filing_lookback_days"] == 127 and cfg["relationships"]["stakes"]["lookback_days"] == 127
    assert (REPO / "config" / "markets" / "us.yaml").read_text() == before
    assert backfill.backfill_config(tmp_path / "config", "india", date(2026, 6, 1), date(2026, 10, 5)) == {}


class FakeNse:
    def __init__(self):
        self.calls = []

    def json(self, endpoint, params=None):
        self.calls.append((endpoint, dict(params or {})))
        return []


def test_collector_since_windows_and_default_unchanged():
    from marketbrief.collectors.collector_store import Problems
    from marketbrief.collectors.nse_announcements import announcements
    from marketbrief.collectors.nse_insiders import insiders
    from marketbrief.collectors.nse_runner import NseRun
    today = date(2026, 10, 5)
    for fn, lookback in ((lambda n, s: announcements(NseRun(n, {}, today, "now", "nomarket", Problems()), 2, s), 2),
                         (lambda n, s: insiders(NseRun(n, {}, today, "now", "nomarket", Problems()), 14, s), 14)):
        n = FakeNse()
        fn(n, None)                                       # default: one call over the configured lookback
        assert len(n.calls) == 1
        assert (n.calls[0][1]["from_date"], n.calls[0][1]["to_date"]) == \
            (f"{today - timedelta(days=lookback):%d-%m-%Y}", "05-10-2026")
        n = FakeNse()
        fn(n, date(2026, 6, 1))                           # --since: one call per week, gap-free, up to today
        spans = [(datetime.strptime(p["from_date"], "%d-%m-%Y").date(),
                  datetime.strptime(p["to_date"], "%d-%m-%Y").date()) for _, p in n.calls]
        assert spans[0][0] == date(2026, 6, 1) and spans[-1][1] == today and len(spans) == 19
        assert all((b - a).days <= 6 for a, b in spans)
        assert all(spans[i + 1][0] == spans[i][1] + timedelta(days=1) for i in range(len(spans) - 1))


def nse_run(script: str, root: Path, cfg: Path, *args: str) -> dict:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": "india"}
    env.pop("MB_NOW", None)
    p = subprocess.run([sys.executable, str(SCRIPTS / script), "--replay", str(REAL_NSE), "--today", "2026-10-05",
                        *args], cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout)


def test_collector_since_on_real_responses(tmp_path):
    """--since end to end on the saved NSE responses (the replay ignores dates, so every weekly call
    returns the same file and the ids are de-duplicated); without it the output is what it was."""
    from test_nse_india import setup as nse_setup
    root, cfg = nse_setup(tmp_path / "a")
    out = nse_run("collect_nse_india.py", root, cfg, "--only", "announcements", "--since", "2026-09-01")
    assert out["new"] == {"announcements": 7}
    assert any("announcements (since 2026-09-01, 5 weekly calls): 50 rows returned" in x for x in out["notes"])
    root, cfg = nse_setup(tmp_path / "b")
    out = nse_run("collect_nse_india.py", root, cfg, "--only", "announcements")
    assert out["new"] == {"announcements": 7} and any("announcements (2 days): 10 rows" in x for x in out["notes"])
    root, cfg = nse_setup(tmp_path / "c", {"AARTIPHARM": {"yahoo": "AARTIPHARM.NS", "name": "Aarti Pharmalabs"}})
    out = nse_run("collect_relations_india.py", root, cfg, "--only", "deals", "--since", "2026-07-07")
    assert out["new"] == {"deals": 10}                    # as --deals-backfill 90 (2026-07-07 is 90 days back)
    assert any("since 2026-07-07" in x for x in out["notes"])



def test_fair_and_contaminated_scored_separately():
    """ForecastBench leakage rule: as-of dates on or before the training cutoff are 'contaminated',
    labelled on every row and scored on their own; the fair result never includes them."""
    days = sessions(date(2026, 6, 1), date(2026, 8, 31))
    n = len(days)
    bars = bars_from({"UP": [100 * 1.01 ** i for i in range(n)], "DN": [100 * 0.99 ** i for i in range(n)]}, days)
    cfg = {"market": "syn", "name": "Synthetic"}
    cut = date(2026, 6, 30)
    early, late = [d for d in days[:20:5] if d <= cut], [d for d in days[30:50:5] if d > cut]
    calls, rec = [], []
    for d in early:   # contaminated: every call hits
        calls.append({"id": f"{d}-UP-5d", "as_of_date": str(d), "ticker": "UP", "horizon_days": 5, "direction": "up",
                      "confidence": 0.8, "prompt_version": "v", "evidence_ids": ["e"]})
        rec.append({"date": str(d), "n_tickers": 2, "eligible": ["UP", "DN"], "n_calls": 1, "n_rejected": 0,
                    "citable_ids": 1})
    for d in late:    # fair: every call misses
        calls.append({"id": f"{d}-DN-5d", "as_of_date": str(d), "ticker": "DN", "horizon_days": 5, "direction": "up",
                      "confidence": 0.6, "prompt_version": "v", "evidence_ids": ["e"]})
        rec.append({"date": str(d), "n_tickers": 2, "eligible": ["UP", "DN"], "n_calls": 1, "n_rejected": 0,
                    "citable_ids": 1})
    s = summaries.summarize(cfg, calls, rec, bars, cutoff=cut)
    f, c = s["fair"], s["contaminated"]
    assert s["model_training_cutoff"] == "2026-06-30" and "never pooled" in s["rule"]
    assert (f["n_days"], f["n_calls"], f["overall"]["hits"]) == (len(late), len(late), 0)
    assert (c["n_days"], c["n_calls"], c["overall"]["hits"]) == (len(early), len(early), len(early))
    assert f["overall"]["hit_rate"] == 0.0 and c["overall"]["hit_rate"] == 1.0   # not pooled (pooled would be between)
    assert f["fair_test"] is True and c["fair_test"] is False
    assert {x["test"] for x in f["calls"]} == {"fair"} and {x["test"] for x in c["calls"]} == {"contaminated"}
    assert {x["test"] for x in f["per_day"]} == {"fair"} and {x["test"] for x in c["per_day"]} == {"contaminated"}
    assert f["abstention"]["any"]["slots"] == 2 * len(late) and c["abstention"]["any"]["slots"] == 2 * len(early)
    page = ai_html.html_page(s)
    assert "Contaminated dates (on or before 2026-06-30): not a fair test" in page
    assert page.count("<td>contaminated</td>") == 2 * len(early)          # per-day and per-call rows
    assert page.count("<td>fair</td>") == 2 * len(late)
    assert page.index("<b>Group: fair</b>") < page.index("<b>Group: contaminated</b>")
    # only contaminated days: no fair result at all
    only = summaries.summarize(cfg, calls[:len(early)], rec[:len(early)], bars, cutoff=cut)
    assert only["fair"]["n_days"] == 0 and "No fair-test day" in ai_html.html_page(only)
    assert cutoff.leakage_label("2026-06-30", cut) == "contaminated"
    assert cutoff.leakage_label(date(2026, 7, 1), cut) == "fair"


def test_training_cutoff_comes_from_config(prepared, tmp_path):
    """Moving model_training_cutoff past D makes D contaminated: prepare refuses it without
    --allow-training-period and, with it, labels the root, the recorded calls and the day."""
    src = prepared["base"]["src"]
    cfg = tmp_path / "config"
    shutil.copytree(prepared["base"]["cfg"], cfg)
    st = cfg / "settings.yaml"
    assert "model_training_cutoff: 2026-06-30" in st.read_text()
    st.write_text(st.read_text().replace("model_training_cutoff: 2026-06-30", "model_training_cutoff: 2026-08-20"))
    p = prepare(src, cfg, tmp_path / "r")
    assert p.returncode != 0 and "2026-08-20" in p.stderr and "contaminated" in p.stderr
    p = prepare(src, cfg, tmp_path / "r", "--allow-training-period")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["test"] == "contaminated" and out["fair_test"] is False and out["model_training_cutoff"] == "2026-08-20"
    assert prepared["base"]["summary"]["test"] == "fair"
    results, calls = tmp_path / "results", tmp_path / "calls.jsonl"
    calls.write_text(json.dumps(call()) + "\n")
    env = {**os.environ, "MB_ROOT": str(src), "MB_CONFIG": str(cfg)}
    p = subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "record", "--market", MARKET, "--date", str(D),
                        "--root", str(tmp_path / "r"), "--calls", str(calls), "--results", str(results)],
                       cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    stored = json.loads((results / MARKET / "calls.jsonl").read_text())
    day = json.loads((results / MARKET / "days.jsonl").read_text())
    assert stored["test"] == day["test"] == "contaminated" and stored["model_training_cutoff"] == "2026-08-20"
    page = tmp_path / "page.html"
    p = subprocess.run([sys.executable, str(SCRIPTS / "ai_replay.py"), "score", "--market", MARKET, "--results",
                        str(results), "--out", str(page)], cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout)
    assert res["fair"]["n_calls"] == 0 and res["contaminated"]["n_calls"] == 1
    assert "CONTAMINATED" in page.read_text()


def test_keep_row_price_sources_by_bar_date():
    """An NSE-fill provenance row (data/<market>/price_sources/) is kept like its bar: by bar date."""
    cut = pd.Timestamp(CUT)
    row = {"id": f"{D}-INFY", "date": str(D), "ticker": "INFY", "source": "nse_bhavcopy",
           "filled_at": "2026-08-20T06:00:00+00:00"}
    assert copy_asof.keep_row("price_sources", row, D, cut)
    assert not copy_asof.keep_row("price_sources", {**row, "date": str(D + timedelta(days=1))}, D, cut)
    assert copy_asof.rule_text("price_sources") == "bar date <= D"
