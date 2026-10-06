"""collect_prices.py fills India watchlist bars Yahoo lacks from NSE's security-wise bhavcopy
(the 2026-10-05 gap: Yahoo jumped from 10-01 to 10-06 for SBILIFE, HDFCLIFE, DRREDDY, MARUTI and
ULTRACEMCO). Offline: a fake yfinance plus trimmed REAL bhavcopies replayed through scripts/nse.py
(tests/fixtures/nse/prices/sec_bhavdata_full_05102026.csv and real/sec_bhavdata_full_01102026.csv;
provenance in tests/fixtures/nse/README)."""
from __future__ import annotations

import csv
import json
import shutil
import sys
import types
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import collect_prices  # noqa: E402
import common  # noqa: E402
from nse import Nse  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "nse"
TODAY = date(2026, 10, 6)              # Tuesday; previous XBOM session Monday 2026-10-05
NOW = "2026-10-06T06:00:00+00:00"
GAP = ["SBILIFE", "HDFCLIFE", "DRREDDY", "MARUTI", "ULTRACEMCO"]
SESSIONS = [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 5)]
# NSE's published 2026-10-05 bars (sec_bhavdata_full_05102026.csv): open, high, low, close, volume
NSE_0510 = {
    "SBILIFE": (1721.6, 1741.4, 1709.5, 1709.5, 1322426),
    "HDFCLIFE": (536.85, 539.05, 524.55, 531.0, 3381490),
    "DRREDDY": (1198.0, 1206.6, 1189.0, 1203.0, 3075974),
    "MARUTI": (11386.0, 11544.0, 11305.0, 11532.0, 757171),
    "ULTRACEMCO": (10736.0, 10940.0, 10731.0, 10850.0, 314538),
}


class FakeTicker:
    frames: dict[str, pd.DataFrame] = {}

    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, **_):
        return self.frames.get(self.symbol, pd.DataFrame()).copy()


def daily(days: list[date], start: float = 100.0) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize("Asia/Kolkata") for d in days])
    c = np.linspace(start, start + 5, len(days))
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Adj Close": c, "Volume": 1000},
                        index=idx)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Scratch root + the real india.yaml cut down to NIFTY50 and seven stocks; a replay
    directory the NSE client reads instead of nsearchives."""
    root, cfg = tmp_path / "root", tmp_path / "config"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    doc = yaml.safe_load((REPO / "config" / "markets" / "india.yaml").read_text())
    keep = [*GAP, "INFY", "TCS"]
    doc["symbols"] = {"NIFTY50": doc["symbols"]["NIFTY50"]}
    doc["tickers"] = {t: doc["tickers"][t] for t in keep}
    doc["sectors"] = {"All": keep}
    (cfg / "markets" / "india.yaml").write_text(yaml.safe_dump(doc))
    for name in ("events.yaml", "settings.yaml", "ranges.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.setattr(common, "CONFIG", cfg)
    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(collect_prices, "utc_today", lambda: TODAY)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: NOW)
    rdir = tmp_path / "replay"
    rdir.mkdir()
    calls = []

    def client(_cfg):
        calls.append(1)
        return Nse(replay=rdir, pause=0)

    monkeypatch.setattr(collect_prices, "nse_client", client)
    full = SESSIONS + [TODAY]                       # today's partial bar is never stored
    gap = SESSIONS[:-1] + [TODAY]                   # Yahoo: 10-01 then 10-06, no 10-05
    FakeTicker.frames = {"^NSEI": daily(full, 22000), "INFY.NS": daily([d for d in full if d != date(2026, 10, 1)]),
                         "TCS.NS": daily(full), **{f"{t}.NS": daily(gap) for t in GAP}}
    return types.SimpleNamespace(root=root, replay=rdir, calls=calls)


def run(monkeypatch, capsys) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["collect_prices", "--market", "india"])
    code = collect_prices.main()
    return code, json.loads(capsys.readouterr().out)


def bars(root: Path, day: date) -> dict[str, dict]:
    p = root / "data" / "india" / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
    return {r["ticker"]: r for r in csv.DictReader(p.open())} if p.exists() else {}


def test_yahoo_gap_filled_from_bhavcopy(env, monkeypatch, capsys):
    shutil.copy(FIX / "prices" / "sec_bhavdata_full_05102026.csv", env.replay)
    shutil.copy(FIX / "real" / "sec_bhavdata_full_01102026.csv", env.replay)
    code, out = run(monkeypatch, capsys)
    assert code == 0
    assert out["failed"] == []                                 # the stale stocks were made whole
    assert {f["ticker"]: f["filled_dates"] for f in out["resolved_by_nse"]} == {t: ["2026-10-05"] for t in GAP}
    assert all(f["error"] == "stale: newest bar 2026-10-01, expected 2026-10-05 or later"
               for f in out["resolved_by_nse"])
    filled = {(b["date"], b["ticker"]): b for b in out["filled_from_nse"]}
    # the five 10-05 bars, plus INFY's 10-01 bar that Yahoo skipped (a gap Yahoo did not flag)
    assert set(filled) == {("2026-10-05", t) for t in GAP} | {("2026-10-01", "INFY")}
    assert all(b["source"] == "nse_bhavcopy" for b in filled.values())
    stored = bars(env.root, date(2026, 10, 5))
    for t, (o, h, lo, c, v) in NSE_0510.items():
        row = stored[t]
        assert (float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
                float(row["adj_close"]), int(row["volume"])) == (o, h, lo, c, c, v)
        assert row["collected_at"] == NOW
        assert (filled[("2026-10-05", t)]["close"], filled[("2026-10-05", t)]["volume"]) == (c, v)
    assert float(stored["INFY"]["close"]) == 103.75             # Yahoo's bar kept, not replaced
    assert float(bars(env.root, date(2026, 10, 1))["INFY"]["close"]) == 1035.0   # NSE's 10-01 close
    assert "NIFTY50" in stored and len(stored) == 8             # indices never come from the bhavcopy
    con = common.connect("india")
    n, distinct = con.execute("SELECT count(*), count(DISTINCT (ticker, date)) FROM prices").fetchone()
    assert n == distinct                                       # one bar per (ticker, date)
    assert con.execute("SELECT close FROM ohlc WHERE ticker='MARUTI' AND date='2026-10-05'").fetchone()[0] == 11532.0

    # second run: nothing missing, so no NSE call and no new rows (a bar is written once)
    before = {d: bars(env.root, d) for d in SESSIONS}
    env.calls.clear()
    code, out = run(monkeypatch, capsys)
    assert code == 0 and out["filled_from_nse"] == [] and env.calls == []
    assert {d: bars(env.root, d) for d in SESSIONS} == before
    assert out["failed"] == []                                 # Yahoo still stale, but no session is missing
    assert {f["ticker"]: f["filled_dates"] for f in out["resolved_by_nse"]} == {t: [] for t in GAP}


def test_existing_bar_is_never_overwritten(env, monkeypatch, capsys):
    shutil.copy(FIX / "prices" / "sec_bhavdata_full_05102026.csv", env.replay)
    shutil.copy(FIX / "real" / "sec_bhavdata_full_01102026.csv", env.replay)
    p = env.root / "data" / "india" / "prices" / "2026" / "10" / "2026-10-05.csv"
    p.parent.mkdir(parents=True)
    p.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
                 "2026-10-05,MARUTI,1,2,0.5,1.5,1.5,7,2026-10-05T12:00:00+00:00\n")
    _, out = run(monkeypatch, capsys)
    assert ("2026-10-05", "MARUTI") not in {(b["date"], b["ticker"]) for b in out["filled_from_nse"]}
    assert [r for r in p.read_text().splitlines() if ",MARUTI," in r] == \
        ["2026-10-05,MARUTI,1,2,0.5,1.5,1.5,7,2026-10-05T12:00:00+00:00"]


def test_holiday_file_or_no_file_leaves_stocks_failed(env, monkeypatch, capsys):
    # NSE serves the previous session's file under a holiday's name (real 02-10 file, which holds
    # 01-Oct rows); offered here as the 05-10 file it must be refused, so nothing is filled.
    shutil.copy(FIX / "real" / "sec_bhavdata_full_02102026.csv", env.replay / "sec_bhavdata_full_05102026.csv")
    shutil.copy(FIX / "real" / "sec_bhavdata_full_01102026.csv", env.replay)
    _, out = run(monkeypatch, capsys)
    assert [b for b in out["filled_from_nse"] if b["date"] == "2026-10-05"] == []
    assert out["resolved_by_nse"] == []
    assert {f["ticker"]: f["missing_after_nse"] for f in out["failed"]} == {t: ["2026-10-05"] for t in GAP}
    assert any("bhavcopy for 2026-10-05 holds 2026-10-01; not used" in n for n in out["nse_notes"])
    assert all(t not in bars(env.root, date(2026, 10, 5)) for t in GAP)

    (env.replay / "sec_bhavdata_full_05102026.csv").unlink()  # file not published / not reachable
    _, out = run(monkeypatch, capsys)
    assert {f["ticker"] for f in out["failed"]} == set(GAP)
    assert any(n.startswith("nse bhavcopy 2026-10-05: no replay file") for n in out["nse_notes"])


def test_bhavcopy_parse_matches_stored_yahoo_bars():
    """The real 01-10 bhavcopy against the Yahoo bars stored for 2026-10-01
    (data/india/prices/2026/10/2026-10-01.csv, collected 2026-10-05): identical OHLC and volume."""
    from nse import nse_symbols
    cfg = yaml.safe_load((REPO / "config" / "markets" / "india.yaml").read_text())
    got, problem = collect_prices.bhavcopy_bars((FIX / "real" / "sec_bhavdata_full_01102026.csv").read_text(),
                                                date(2026, 10, 1), nse_symbols(cfg))
    assert problem is None and len(got) == 20
    yahoo_0110 = {   # stored Yahoo bars: open, high, low, close, volume
        "SBILIFE": (1676.3, 1730.3, 1674.8, 1721.6, 3329860),
        "HDFCLIFE": (518.0, 538.9, 517.4, 534.2, 4008935),
        "DRREDDY": (1233.0, 1233.9, 1194.9, 1206.2, 2607818),
        "MARUTI": (11900.0, 11907.0, 11305.0, 11386.0, 885820),
        "ULTRACEMCO": (10810.0, 10879.0, 10612.0, 10710.0, 570684),
    }
    for t, v in yahoo_0110.items():
        b = got[t]
        assert (b["open"], b["high"], b["low"], b["close"], b["volume"]) == v
    _, problem = collect_prices.bhavcopy_bars((FIX / "real" / "sec_bhavdata_full_02102026.csv").read_text(),
                                              date(2026, 10, 2), nse_symbols(cfg))
    assert problem == "bhavcopy for 2026-10-02 holds 2026-10-01; not used"
