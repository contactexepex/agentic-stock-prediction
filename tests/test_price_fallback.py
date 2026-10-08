"""collect_prices.py fills India watchlist bars Yahoo lacks from NSE's security-wise bhavcopy
(the 2026-10-05 gap: Yahoo jumped from 10-01 to 10-06 for SBILIFE, HDFCLIFE, DRREDDY, MARUTI and
ULTRACEMCO), guarded against a different price basis (stored Yahoo bars are split/bonus-adjusted
as of collection; the bhavcopy is as traded). Offline: a fake yfinance plus trimmed REAL
bhavcopies replayed through marketbrief/sources/nse_client.py (tests/fixtures/nse/prices/ and
real/sec_bhavdata_full_01102026.csv; provenance in tests/fixtures/nse/README)."""
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

from marketbrief.collectors import nse_session, price_nse_fallback  # noqa: E402
from marketbrief.collectors import prices as collect_prices  # noqa: E402
import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.sources.nse_client import Nse  # noqa: E402

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
# Real closes (stored Yahoo bars = NSE closes) that the bhavcopies' PREV_CLOSE refers to
CLOSE_0110 = {"SBILIFE": 1721.6, "HDFCLIFE": 534.2, "DRREDDY": 1206.2, "MARUTI": 11386.0, "ULTRACEMCO": 10710.0}
INFY_0930 = 994.1


class FakeTicker:
    frames: dict[str, pd.DataFrame] = {}

    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, **_):
        return self.frames.get(self.symbol, pd.DataFrame()).copy()


def daily(days: list[date], start: float = 100.0, last_close: dict | None = None,
          splits: dict | None = None) -> pd.DataFrame:
    """A yfinance-like frame; `last_close` pins the bar of given days to a close, `splits` sets
    the `Stock Splits` column (0 elsewhere, as yfinance gives)."""
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize("Asia/Kolkata") for d in days])
    c = np.linspace(start, start + 5, len(days))
    for i, d in enumerate(days):
        if last_close and d in last_close:
            c[i] = last_close[d]
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Adj Close": c, "Volume": 1000,
                       "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)
    for d, ratio in (splits or {}).items():
        df.loc[pd.Timestamp(d).tz_localize("Asia/Kolkata"), "Stock Splits"] = ratio
    return df


def make_env(tmp_path, monkeypatch, keep: list[str], today: date, sessions: int = 5):
    """Scratch root + the real india.yaml cut down to NIFTY50 and `keep`; a replay directory the
    NSE client reads instead of nsearchives."""
    root, cfg = tmp_path / "root", tmp_path / "config"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    doc = yaml.safe_load((REPO / "config" / "markets" / "india.yaml").read_text())
    doc["symbols"] = {"NIFTY50": doc["symbols"]["NIFTY50"]}
    doc["company_meta"] = {t: doc["company_meta"][t] for t in keep}
    doc["sectors"] = {"All": keep}
    doc["price_fallback"]["sessions"] = sessions
    (cfg / "markets" / "india.yaml").write_text(yaml.safe_dump(doc))
    for name in ("events.yaml", "settings.yaml", "ranges.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.setattr(common, "CONFIG", cfg)
    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(collect_prices, "utc_today", lambda: today)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: NOW)
    rdir = tmp_path / "replay"
    rdir.mkdir()
    calls = []

    def client(_cfg):
        calls.append(1)
        return Nse(replay=rdir, pause=0)

    monkeypatch.setattr(nse_session, "nse_client", client)
    FakeTicker.frames = {}
    return types.SimpleNamespace(root=root, replay=rdir, calls=calls)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, [*GAP, "INFY", "TCS"], TODAY)
    full = SESSIONS + [TODAY]                       # today's partial bar is never stored
    gap = SESSIONS[:-1] + [TODAY]                   # Yahoo: 10-01 then 10-06, no 10-05
    FakeTicker.frames = {
        "^NSEI": daily(full, 22000),
        "INFY.NS": daily([d for d in full if d != date(2026, 10, 1)], last_close={date(2026, 9, 30): INFY_0930}),
        "TCS.NS": daily(full),
        **{f"{t}.NS": daily(gap, last_close={date(2026, 10, 1): CLOSE_0110[t]}) for t in GAP}}
    return e


def run(monkeypatch, capsys) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["collect_prices", "--market", "india"])
    code = collect_prices.main()
    return code, json.loads(capsys.readouterr().out)


def bars(root: Path, day: date) -> dict[str, dict]:
    p = root / "data" / "india" / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
    return {r["ticker"]: r for r in csv.DictReader(p.open())} if p.exists() else {}


def sources(root: Path) -> list[dict]:
    return [json.loads(line) for f in sorted((root / "data" / "india" / "price_sources").glob("**/*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]


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

    # provenance sidecar, one row per filled bar, filed under the bar's date
    rows = sources(env.root)
    assert sorted((r["date"], r["ticker"]) for r in rows) == sorted(filled)
    assert all(r["source"] == "nse_bhavcopy" and r["filled_at"] == NOW and r["id"] == f"{r['date']}-{r['ticker']}"
               and r["url"].endswith(f"sec_bhavdata_full_{date.fromisoformat(r['date']):%d%m%Y}.csv") for r in rows)
    assert (env.root / "data" / "india" / "price_sources" / "2026" / "10" / "2026-10-05.jsonl").exists()
    con = connect("india")
    n, distinct = con.execute("SELECT count(*), count(DISTINCT (ticker, date)) FROM prices").fetchone()
    assert n == distinct                                       # one bar per (ticker, date)
    assert con.execute("SELECT close FROM ohlc WHERE ticker='MARUTI' AND date='2026-10-05'").fetchone()[0] == 11532.0
    src = dict(((t, str(d)), s) for t, d, s in con.execute("SELECT ticker, date, source FROM bar_sources").fetchall())
    assert {k for k, s in src.items() if s == "nse_bhavcopy"} == {(t, d) for d, t in filled}
    assert src[("INFY", "2026-10-05")] == "yahoo" and src[("NIFTY50", "2026-10-05")] == "yahoo"

    # second run: nothing missing, so no NSE call and no new rows (a bar is written once)
    before = {d: bars(env.root, d) for d in SESSIONS}
    env.calls.clear()
    code, out = run(monkeypatch, capsys)
    assert code == 0 and out["filled_from_nse"] == [] and env.calls == []
    assert {d: bars(env.root, d) for d in SESSIONS} == before
    assert len(sources(env.root)) == len(rows)
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
    reason = "nse bhavcopy for 2026-10-05 holds 2026-10-01; not used"
    assert {f["ticker"]: f["missing_after_nse"] for f in out["failed"]} == \
        {t: [{"date": "2026-10-05", "reason": reason}] for t in GAP}
    assert reason in out["nse_notes"]
    assert all(t not in bars(env.root, date(2026, 10, 5)) for t in GAP)

    (env.replay / "sec_bhavdata_full_05102026.csv").unlink()  # file not published / not reachable
    _, out = run(monkeypatch, capsys)
    assert {f["ticker"] for f in out["failed"]} == set(GAP)
    assert any(n.startswith("nse bhavcopy 2026-10-05: no replay file") for n in out["nse_notes"])


def test_split_like_basis_mismatch_is_not_filled(tmp_path, monkeypatch, capsys):
    """HDFCBANK's real 1:1 bonus (ex-date 2025-08-26): our stored 2025-08-21 close is the
    bonus-adjusted 995.6 (collected 2026-10-05), NSE's 22-Aug-2025 bhavcopy is as traded (PREV_CLOSE
    1991.20, close 1964.60). The 22-Aug bar must not be filled; INFY (no corporate action, stored
    close 1496.4 = PREV_CLOSE) is filled from the same file."""
    e = make_env(tmp_path, monkeypatch, ["HDFCBANK", "INFY"], date(2025, 8, 25))
    shutil.copy(FIX / "prices" / "sec_bhavdata_full_22082025.csv", e.replay)
    days = [date(2025, 8, 18), date(2025, 8, 19), date(2025, 8, 20), date(2025, 8, 21)]
    stored_0821 = {"HDFCBANK": 995.6, "INFY": 1496.4}          # the real stored Yahoo closes
    FakeTicker.frames = {"^NSEI": daily(days + [date(2025, 8, 22)], 24000),
                         **{f"{t}.NS": daily(days, last_close={days[-1]: c}) for t, c in stored_0821.items()}}
    _, out = run(monkeypatch, capsys)
    assert [(b["ticker"], b["date"], b["close"], b["volume"]) for b in out["filled_from_nse"]] == \
        [("INFY", "2025-08-22", 1487.5, 5543397)]
    hd = {f["ticker"]: f for f in out["failed"]}["HDFCBANK"]
    assert hd["error"] == "stale: newest bar 2025-08-21, expected 2025-08-22 or later"
    assert hd["missing_after_nse"] == [{"date": "2025-08-22", "reason":
        "price basis mismatch: bhavcopy PREV_CLOSE 1991.2 vs stored close 995.6 on 2025-08-21 (+100.0%); "
        "split, bonus or other corporate action"}]
    assert not any("HDFCBANK" in n for n in out["nse_notes"])        # listed once, in failed (issue #35)
    assert "HDFCBANK" not in bars(e.root, date(2025, 8, 22))
    assert [r["ticker"] for r in sources(e.root)] == ["INFY"]
    assert [f["ticker"] for f in out["resolved_by_nse"]] == ["INFY"]


def test_yahoo_split_blocks_the_fill(env, monkeypatch, capsys):
    """A split/bonus in Yahoo's frame after the previous session: the bar is not filled even
    though PREV_CLOSE matches the stored close."""
    shutil.copy(FIX / "prices" / "sec_bhavdata_full_05102026.csv", env.replay)
    gap = SESSIONS[:-1] + [TODAY]
    FakeTicker.frames["MARUTI.NS"] = daily(gap, last_close={date(2026, 10, 1): CLOSE_0110["MARUTI"]},
                                           splits={TODAY: 2.0})
    _, out = run(monkeypatch, capsys)
    assert ("2026-10-05", "MARUTI") not in {(b["date"], b["ticker"]) for b in out["filled_from_nse"]}
    assert {f["ticker"]: f["missing_after_nse"] for f in out["failed"] if f["ticker"] == "MARUTI"} == \
        {"MARUTI": [{"date": "2026-10-05", "reason": "Yahoo reports a split/bonus on 2026-10-06; price basis may differ"}]}
    assert "MARUTI" not in bars(env.root, date(2026, 10, 5))
    assert {f["ticker"] for f in out["resolved_by_nse"]} == set(GAP) - {"MARUTI"}


def test_stock_stale_beyond_the_window_stays_failed(tmp_path, monkeypatch, capsys):
    """With 2 checked sessions (10-01, 10-05), a stock whose newest stored bar is 09-29 (3 sessions
    behind) stays in `failed` with its age. Neither of its bars is filled: 09-30 and 10-01 are not
    stored, so there is no previous close to check the basis against. INFY's 10-05 bar is filled."""
    e = make_env(tmp_path, monkeypatch, ["TCS", "INFY"], TODAY, sessions=2)
    shutil.copy(FIX / "prices" / "sec_bhavdata_full_05102026.csv", e.replay)
    shutil.copy(FIX / "real" / "sec_bhavdata_full_01102026.csv", e.replay)
    old = [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29)]
    FakeTicker.frames = {"^NSEI": daily(SESSIONS + [TODAY], 22000),
                         "TCS.NS": daily(old, last_close={date(2026, 9, 29): 2032.4}),
                         "INFY.NS": daily(SESSIONS[:-1], last_close={date(2026, 10, 1): 1035.0})}
    _, out = run(monkeypatch, capsys)
    # TCS 10-01: PREV_CLOSE 2050.6 (its 09-30 close) but 09-30 is not stored -> no basis check, not filled
    assert sorted((b["ticker"], b["date"]) for b in out["filled_from_nse"]) == [("INFY", "2026-10-05")]
    tcs = {f["ticker"]: f for f in out["failed"]}["TCS"]
    assert tcs["newest_stored_bar"] == "2026-09-29" and tcs["sessions_behind"] == 3
    assert tcs["beyond_nse_window"] == "the fallback checks only sessions from 2026-10-01"
    assert [m["date"] for m in tcs["missing_after_nse"]] == ["2026-10-01", "2026-10-05"]
    assert tcs["missing_after_nse"][0]["reason"] == \
        "no stored close for the previous session 2026-09-30 to check the price basis"
    assert [f["ticker"] for f in out["resolved_by_nse"]] == ["INFY"]


def test_bhavcopy_parse_matches_stored_yahoo_bars():
    """The real 01-10 bhavcopy against the Yahoo bars stored for 2026-10-01
    (data/india/prices/2026/10/2026-10-01.csv, collected 2026-10-05): identical OHLC and volume."""
    from marketbrief.sources.nse_parsing import nse_symbols
    cfg = {("tickers" if key == "company_meta" else key): value   # the raw config as a cfg
           for key, value in yaml.safe_load((REPO / "config" / "markets" / "india.yaml").read_text()).items()}
    got, problem = price_nse_fallback.bhavcopy_bars((FIX / "real" / "sec_bhavdata_full_01102026.csv").read_text(),
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
    _, problem = price_nse_fallback.bhavcopy_bars((FIX / "real" / "sec_bhavdata_full_02102026.csv").read_text(),
                                              date(2026, 10, 2), nse_symbols(cfg))
    assert problem == "bhavcopy for 2026-10-02 holds 2026-10-01; not used"
    got, _ = price_nse_fallback.bhavcopy_bars((FIX / "prices" / "sec_bhavdata_full_22082025.csv").read_text(),
                                          date(2025, 8, 22), nse_symbols(cfg))
    assert (got["TATASTEEL"]["open"], got["TATASTEEL"]["volume"]) == (161.25, 16063984)   # EQ row, not T0
    assert (got["HDFCBANK"]["close"], got["HDFCBANK"]["prev_close"]) == (1964.6, 1991.2)
