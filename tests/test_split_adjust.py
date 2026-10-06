"""Splits and bonus issues (issue #31): detected by collect_prices.py, recorded once in
data/<market>/adjustments/, applied on read by the ohlc/bars views, and handled by scoring and the
as-of replay. Offline: a fake yfinance, synthetic stored bars, and for India the REAL NSE bhavcopy
of HDFCBANK's 1:1 bonus ex-date (tests/fixtures/nse/prices/sec_bhavdata_full_26082025.csv)."""
from __future__ import annotations

import json
import math
import shutil
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

from marketbrief.analytics import price_adjustments as adjust  # noqa: E402
import ai_replay as ar  # noqa: E402
from marketbrief.collectors import price_nse_fallback, price_rebase  # noqa: E402
from marketbrief.collectors import prices as collect_prices  # noqa: E402
import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.storage import append_jsonl, day_file  # noqa: E402
from marketbrief.analytics import indicators as ind  # noqa: E402
import score_predictions  # noqa: E402
from marketbrief.analytics.features import load_bars  # noqa: E402
from test_price_fallback import FakeTicker, make_env  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "nse"
HEADER = "date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"   # csv.writer line ends, as stored
EARLY = "2026-09-01T22:00:00+00:00"
# US sessions 2026-08-31 .. 2026-09-17 (Labor Day 09-07 closed); split ex-date Monday 09-14
US_DAYS = [date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4),
           date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11),
           date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)]
EX = date(2026, 9, 14)
US_TODAY = date(2026, 9, 18)
US_NOW = "2026-09-18T12:00:00+00:00"


def traded(n: int = len(US_DAYS)) -> list[float]:
    """As-traded closes: about 200, then halved from the 2:1 split's ex-date (plus a small drift)."""
    out = []
    for i, d in enumerate(US_DAYS[:n]):
        c = 200.0 + i
        out.append(round(c / 2 if d >= EX else c, 4))
    return out


def write_stored(root: Path, market: str, ticker: str, rows: dict[date, float], volume: int = 1000):
    for d, c in rows.items():
        p = root / "data" / market / "prices" / f"{d:%Y}" / f"{d:%m}" / f"{d}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with p.open("a", newline="") as f:
            if new:
                f.write(HEADER)
            f.write(f"{d},{ticker},{c},{c + 1},{c - 1},{c},{c},{volume},{EARLY}\r\n")


def frame(days: list[date], closes: list[float], tz: str, splits: dict | None = None, volume: int = 1000):
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(tz) for d in days])
    c = np.array(closes, dtype=float)
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Adj Close": c, "Volume": volume,
                       "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)
    for d, r in (splits or {}).items():
        df.loc[pd.Timestamp(d).tz_localize(tz), "Stock Splits"] = r
    return df


def adj_rows(root: Path, market: str) -> list[dict]:
    return [json.loads(line) for f in sorted((root / "data" / market / "adjustments").glob("**/*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]


def run(monkeypatch, capsys, market: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["collect_prices", "--market", market])
    collect_prices.main()
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def us(tmp_path, monkeypatch):
    """Scratch root + the real us.yaml cut down to SPY, NVDA and JPM."""
    root, cfg = tmp_path / "root", tmp_path / "config"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    doc = yaml.safe_load((REPO / "config" / "markets" / "us.yaml").read_text())
    doc["symbols"] = {"SPY": doc["symbols"]["SPY"]}
    doc["tickers"] = {t: doc["tickers"][t] for t in ("NVDA", "JPM")}
    doc["sectors"] = {"All": ["NVDA", "JPM"]}
    (cfg / "markets" / "us.yaml").write_text(yaml.safe_dump(doc))
    for name in ("events.yaml", "settings.yaml", "ranges.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.setattr(common, "CONFIG", cfg)
    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(collect_prices, "utc_today", lambda: US_TODAY)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: US_NOW)
    flat = [500.0 + i for i in range(len(US_DAYS))]
    FakeTicker.frames = {"SPY": frame(US_DAYS, flat, "America/New_York"),
                         "JPM": frame(US_DAYS, [300.0 + i for i in range(len(US_DAYS))], "America/New_York")}
    write_stored(root, "us", "SPY", dict(zip(US_DAYS[:9], flat[:9])))
    write_stored(root, "us", "JPM", {d: 300.0 + i for i, d in enumerate(US_DAYS[:9])})
    return types.SimpleNamespace(root=root)


def test_two_for_one_split_recorded_once_and_applied_on_read(us, monkeypatch, capsys):
    """2:1 split, ex 2026-09-14: our bars up to 09-11 were stored before it (old basis, 09-09 missing);
    Yahoo now serves all history halved with a `Stock Splits` row of 2.0 on the ex-date."""
    tr = traded()
    stored = {d: c for d, c in zip(US_DAYS[:9], tr[:9]) if d != date(2026, 9, 9)}
    write_stored(us.root, "us", "NVDA", stored)
    yahoo = [c / 2 if d < EX else c for d, c in zip(US_DAYS, tr)]          # today's basis
    FakeTicker.frames["NVDA"] = frame(US_DAYS, yahoo, "America/New_York", splits={EX: 2.0}, volume=4000)
    out = run(monkeypatch, capsys, "us")
    assert out["warnings"] == [] and out["failed"] == []
    assert len(out["adjustments"]) == 1
    rec = out["adjustments"][0]
    assert {k: rec[k] for k in ("id", "ticker", "ex_date", "factor", "volume_factor", "source", "yahoo_ratio",
                                "check_date", "stored_close", "yahoo_close", "measured_factor", "detected_at")} == {
        "id": "NVDA-2026-09-14", "ticker": "NVDA", "ex_date": "2026-09-14", "factor": 0.5, "volume_factor": 2.0,
        "source": "yahoo_splits", "yahoo_ratio": 2.0, "check_date": "2026-09-11", "stored_close": 208.0,
        "yahoo_close": 104.0, "measured_factor": 0.5, "detected_at": US_NOW}
    assert adj_rows(us.root, "us") == [rec]
    assert (us.root / "data" / "us" / "adjustments" / "2026" / "09" / "2026-09-14.jsonl").exists()
    # the missing 09-09 bar Yahoo serves on today's basis is written on the stored (old) basis
    assert out["rebased_bars"] == [{"ticker": "NVDA", "date": "2026-09-09", "factor": 0.5}]
    raw0909 = (us.root / "data" / "us" / "prices" / "2026" / "09" / "2026-09-09.csv").read_text()
    assert "2026-09-09,NVDA,206.0,208.0,204.0,206.0,206.0,2000," in raw0909

    con = connect("us")
    adjd = dict(con.execute("SELECT date, close FROM ohlc WHERE ticker = 'NVDA' ORDER BY date").fetchall())
    assert [adjd[d] for d in US_DAYS] == pytest.approx(yahoo, abs=1e-9)    # one basis, Yahoo's
    raw = dict(con.execute("SELECT date, close FROM ohlc_raw WHERE ticker = 'NVDA'").fetchall())
    assert raw[date(2026, 9, 11)] == 208.0 and raw[EX] == 104.5             # stored bars untouched
    vols = dict(con.execute("SELECT date, volume FROM ohlc WHERE ticker = 'NVDA'").fetchall())
    assert vols[date(2026, 9, 11)] == 2000 and vols[EX] == 4000             # 1000 stored x 2; new bar as is
    r1 = con.execute("SELECT max(abs(ret_1d)) FROM returns WHERE ticker = 'NVDA'").fetchone()[0]
    assert r1 < 0.01                                                        # no fake -50% day
    jump = con.execute("SELECT close FROM bars_raw WHERE ticker = 'NVDA' AND date = ?", [EX]).fetchone()[0] / 208.0 - 1
    assert jump == pytest.approx(-0.4976, abs=1e-3)                         # what the raw bars would show
    rn = con.execute("SELECT count(*) FROM bars b JOIN bars_raw r USING (ticker, date) WHERE b.rn <> r.rn").fetchone()[0]
    assert rn == 0
    assert con.execute("SELECT count(*) FROM ohlc o JOIN ohlc_raw r USING (ticker, date) "
                       "WHERE o.ticker <> 'NVDA' AND (o.close <> r.close OR o.volume <> r.volume)").fetchone()[0] == 0
    # indicators on the adjusted bars: no jump
    df = load_bars(con)["NVDA"]
    assert ind.realized_vol(df["close"]) < 0.05
    rawdf = con.execute("SELECT date, open, high, low, close, volume FROM ohlc_raw WHERE ticker = 'NVDA' "
                        "ORDER BY date").df().set_index("date")
    assert ind.realized_vol(rawdf["close"]) > 0.5                           # the jump the views remove

    # second run: same frame, nothing new (a corporate action is recorded once)
    out2 = run(monkeypatch, capsys, "us")
    assert out2["adjustments"] == [] and out2["warnings"] == [] and out2["new_bars"] == 0
    assert adj_rows(us.root, "us") == [rec]


def test_unexplained_rebase_is_a_warning_and_holds_new_bars(us, monkeypatch, capsys):
    """Yahoo's closes for all stored dates are 20% lower (a re-base by 4/5) but no split row
    explains it: a warning, no record, and NVDA's new bars are held (listed in failed) so no
    new-basis bar lands next to the old-basis ones. JPM: a split row while our stored bars already
    sit on the new basis (collected after it): nothing to adjust, nothing to warn about."""
    tr = traded(9)
    write_stored(us.root, "us", "NVDA", dict(zip(US_DAYS[:9], tr)))
    FakeTicker.frames["NVDA"] = frame(US_DAYS, [c * 0.8 for c in tr] + [180.0, 181.0, 182.0, 183.0],
                                      "America/New_York")
    FakeTicker.frames["JPM"] = frame(US_DAYS, [300.0 + i for i in range(len(US_DAYS))], "America/New_York",
                                     splits={date(2026, 9, 2): 2.0})
    out = run(monkeypatch, capsys, "us")
    assert out["adjustments"] == [] and adj_rows(us.root, "us") == []
    assert len(out["warnings"]) == 1
    w = out["warnings"][0]
    assert w.startswith("NVDA: Yahoo's close differs from the stored close on 9 date(s) 2026-08-31..2026-09-11 "
                        "(Yahoo/stored 0.8000-0.8000)")
    assert w.endswith("a re-base by 4/5 that no Yahoo split row or NSE bhavcopy confirms (yet): "
                      "not recorded, new bars held")
    assert out["held"] == ["NVDA"]
    assert out["failed"] == [{"ticker": "NVDA", "yahoo": "NVDA",
                              "error": "price basis unconfirmed (split/bonus?): new bars held, see warnings"}]
    con = connect("us")
    assert con.execute("SELECT count(*) FROM ohlc o JOIN ohlc_raw r USING (ticker, date) "
                       "WHERE o.close <> r.close").fetchone()[0] == 0
    assert con.execute("SELECT max(date) FROM ohlc WHERE ticker = 'NVDA'").fetchone()[0] == date(2026, 9, 11)
    assert con.execute("SELECT max(date) FROM ohlc WHERE ticker = 'JPM'").fetchone()[0] == date(2026, 9, 17)


def test_isolated_mismatch_warns_but_keeps_collecting(us, monkeypatch, capsys):
    """One stored close Yahoo now reports 5% lower (a data correction, no re-base): a warning only;
    the new bars are written."""
    tr = traded(9)
    write_stored(us.root, "us", "NVDA", dict(zip(US_DAYS[:9], tr)))
    y = list(tr) + [190.0, 191.0, 192.0, 193.0]
    y[3] = tr[3] * 0.95
    FakeTicker.frames["NVDA"] = frame(US_DAYS, y, "America/New_York")
    out = run(monkeypatch, capsys, "us")
    assert out["adjustments"] == [] and "held" not in out and out["failed"] == []
    assert out["warnings"] == ["NVDA: Yahoo's close differs from the stored close on 1 date(s) 2026-09-03..2026-09-03 "
                               "(Yahoo/stored 0.9500-0.9500); not one re-base of the stored history, not recorded"]
    assert connect("us").execute("SELECT max(date) FROM ohlc WHERE ticker = 'NVDA'").fetchone()[0] == \
        date(2026, 9, 17)


def test_split_row_with_mixed_stored_basis_warns(us, monkeypatch, capsys):
    """A split row, but the stored closes before it are partly on the old basis and partly on the
    new one: no single factor fits, so nothing is recorded and the collector warns."""
    tr = traded(9)
    stored = {d: (c / 2 if d >= date(2026, 9, 8) else c) for d, c in zip(US_DAYS[:9], tr)}
    write_stored(us.root, "us", "NVDA", stored)
    FakeTicker.frames["NVDA"] = frame(US_DAYS, [c / 2 if d < EX else c for d, c in zip(US_DAYS, traded())],
                                      "America/New_York", splits={EX: 2.0})
    out = run(monkeypatch, capsys, "us")
    assert out["adjustments"] == [] and adj_rows(us.root, "us") == []
    assert out["warnings"] == ["NVDA: Yahoo reports a split/bonus on 2026-09-14 (ratio 2) but Yahoo/stored closes "
                               "before it range 0.5000-1.0000 (expected 0.5000 or 1); not recorded, new bars held"]
    assert out["held"] == ["NVDA"]


def test_split_row_with_a_step_in_yahoos_own_frame_warns(us, monkeypatch, capsys):
    """A split row whose stored closes match the factor, but Yahoo's own frame still steps by about
    the factor at the ex-date (its history is not consistently re-based): no record, held."""
    tr = traded(9)
    write_stored(us.root, "us", "NVDA", dict(zip(US_DAYS[:9], tr)))
    y = [c / 2 for c in tr] + [52.5, 53.0, 53.5, 54.0]          # 104 on 09-11, then 52.5: a -50% step
    FakeTicker.frames["NVDA"] = frame(US_DAYS, y, "America/New_York", splits={EX: 2.0})
    out = run(monkeypatch, capsys, "us")
    assert out["adjustments"] == [] and out["held"] == ["NVDA"]
    assert out["warnings"] == ["NVDA: Yahoo reports a split/bonus on 2026-09-14 (ratio 2) but its own frame steps by "
                               "0.5048 there (not re-based); not recorded, new bars held"]


def test_rebase_before_the_ex_date_bar_then_split_row(us, monkeypatch, capsys):
    """Timing: on the ex-date morning (run with today 09-14) Yahoo has already re-based history,
    including the 09-11 bar we have not stored yet, but shows no split row. Run 1 holds NVDA's bars
    (nothing written next to the old basis). Run 2 (09-15) sees the split row: it is recorded, the
    held 09-11 bar is written on the stored (old) basis and 09-14 as served: no fake jump."""
    tr = traded()
    write_stored(us.root, "us", "NVDA", dict(zip(US_DAYS[:8], tr[:8])))     # stored up to 09-10
    yahoo = [c / 2 if d < EX else c for d, c in zip(US_DAYS, tr)]
    i_ex = US_DAYS.index(EX)
    monkeypatch.setattr(collect_prices, "utc_today", lambda: EX)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: "2026-09-14T12:00:00+00:00")
    FakeTicker.frames = {"NVDA": frame(US_DAYS[:i_ex], yahoo[:i_ex], "America/New_York"),
                         "SPY": frame(US_DAYS[:i_ex], [500.0 + i for i in range(i_ex)], "America/New_York"),
                         "JPM": frame(US_DAYS[:i_ex], [300.0 + i for i in range(i_ex)], "America/New_York")}
    o1 = run(monkeypatch, capsys, "us")
    assert o1["adjustments"] == [] and o1["held"] == ["NVDA"] and len(o1["warnings"]) == 1
    assert ",NVDA," not in (us.root / "data" / "us" / "prices" / "2026" / "09" / "2026-09-11.csv").read_text()
    assert connect("us").execute("SELECT max(date) FROM ohlc WHERE ticker = 'NVDA'").fetchone()[0] == \
        date(2026, 9, 10)
    n = i_ex + 1
    monkeypatch.setattr(collect_prices, "utc_today", lambda: date(2026, 9, 15))
    monkeypatch.setattr(collect_prices, "utc_now", lambda: "2026-09-15T12:00:00+00:00")
    FakeTicker.frames = {"NVDA": frame(US_DAYS[:n], yahoo[:n], "America/New_York", splits={EX: 2.0}),
                         "SPY": frame(US_DAYS[:n], [500.0 + i for i in range(n)], "America/New_York"),
                         "JPM": frame(US_DAYS[:n], [300.0 + i for i in range(n)], "America/New_York")}
    o2 = run(monkeypatch, capsys, "us")
    assert o2["warnings"] == [] and "held" not in o2 and o2["failed"] == []
    assert [(a["id"], a["factor"], a["source"], a["check_date"]) for a in o2["adjustments"]] == \
        [("NVDA-2026-09-14", 0.5, "yahoo_splits", "2026-09-10")]
    assert o2["rebased_bars"] == [{"ticker": "NVDA", "date": "2026-09-11", "factor": 0.5}]
    con = connect("us")
    raw = dict(con.execute("SELECT date, close FROM ohlc_raw WHERE ticker = 'NVDA'").fetchall())
    assert raw[date(2026, 9, 11)] == 208.0 and raw[EX] == 104.5             # old basis, as traded
    closes = [c for _, c in con.execute("SELECT date, close FROM ohlc WHERE ticker = 'NVDA' ORDER BY date").fetchall()]
    assert closes == pytest.approx(yahoo[:n])
    assert con.execute("SELECT max(abs(ret_1d)) FROM returns WHERE ticker = 'NVDA'").fetchone()[0] < 0.01


def test_india_bonus_confirmed_by_nse_bhavcopy(tmp_path, monkeypatch, capsys):
    """HDFCBANK's real 1:1 bonus (ex 2025-08-26) without a Yahoo split row: our 08-22 and 08-25
    bars were stored as traded (NSE closes 1964.60 and 1964.10), Yahoo now serves them halved. NSE's
    26-Aug bhavcopy (real) confirms: PREV_CLOSE 1964.10 = our stored close, Yahoo/PREV_CLOSE = 0.5,
    and the traded close 973.40 stepped by about the factor. INFY: no corporate action."""
    e = make_env(tmp_path, monkeypatch, ["HDFCBANK", "INFY"], date(2025, 8, 27))
    shutil.copy(FIX / "prices" / "sec_bhavdata_full_26082025.csv", e.replay)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: "2025-08-27T02:30:00+00:00")
    days = [date(2025, 8, 20), date(2025, 8, 21), date(2025, 8, 22), date(2025, 8, 25)]
    hd = {date(2025, 8, 20): 1990.0, date(2025, 8, 21): 1991.2, date(2025, 8, 22): 1964.6, date(2025, 8, 25): 1964.1}
    infy = {d: 1500.0 + i for i, d in enumerate(days)}
    nifty = {d: 24000.0 + i for i, d in enumerate(days)}
    write_stored(e.root, "india", "HDFCBANK", hd)
    write_stored(e.root, "india", "INFY", infy)
    write_stored(e.root, "india", "NIFTY50", nifty)
    ex = date(2025, 8, 26)
    FakeTicker.frames = {
        "^NSEI": frame(days + [ex], [*nifty.values(), 24100.0], "Asia/Kolkata"),
        "INFY.NS": frame(days + [ex], [*infy.values(), 1529.6], "Asia/Kolkata"),
        "HDFCBANK.NS": frame(days + [ex], [c / 2 for c in hd.values()] + [973.4], "Asia/Kolkata")}
    out = run(monkeypatch, capsys, "india")
    assert out["warnings"] == [] and out["failed"] == []
    assert out["filled_from_nse"] == []                      # nothing missing: the fallback did not run
    assert len(out["adjustments"]) == 1
    rec = out["adjustments"][0]
    assert {k: rec[k] for k in ("id", "ex_date", "factor", "volume_factor", "source", "check_date", "stored_close",
                                "yahoo_close", "measured_factor", "nse_prev_close", "nse_ex_close", "url")} == {
        "id": "HDFCBANK-2025-08-26", "ex_date": "2025-08-26", "factor": 0.5, "volume_factor": 2.0,
        "source": "nse_prev_close", "check_date": "2025-08-25", "stored_close": 1964.1, "yahoo_close": 982.05,
        "measured_factor": 0.5, "nse_prev_close": 1964.1, "nse_ex_close": 973.4,
        "url": "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_26082025.csv"}
    assert "yahoo_ratio" not in rec
    con = connect("india")
    closes = dict(con.execute("SELECT date, close FROM ohlc WHERE ticker = 'HDFCBANK'").fetchall())
    assert closes[date(2025, 8, 25)] == pytest.approx(982.05) and closes[ex] == 973.4
    assert con.execute("SELECT max(abs(ret_1d)) FROM returns WHERE ticker = 'HDFCBANK'").fetchone()[0] < 0.02

    out2 = run(monkeypatch, capsys, "india")                 # idempotent
    assert out2["adjustments"] == [] and out2["warnings"] == [] and len(adj_rows(e.root, "india")) == 1


def test_india_missed_run_finds_the_ex_date(tmp_path, monkeypatch, capsys):
    """Timing: the 08-26 run was missed. On 08-27 our bars end at 08-22 (as traded) while Yahoo
    serves 08-25 re-based and 08-26 (no split row). The NSE check walks the frame's sessions after
    08-22: the real 25-Aug bhavcopy ties PREV_CLOSE 1964.60 to our stored close and shows a normal
    day, the real 26-Aug one steps by about 0.5 (PREV_CLOSE 1964.10 = Yahoo's 982.05 x 2): ex-date
    08-26. 08-25 is written on the stored basis (1964.10), 08-26 as served: no fake jump."""
    e = make_env(tmp_path, monkeypatch, ["HDFCBANK"], date(2025, 8, 27))
    for f in ("sec_bhavdata_full_25082025.csv", "sec_bhavdata_full_26082025.csv"):
        shutil.copy(FIX / "prices" / f, e.replay)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: "2025-08-27T02:30:00+00:00")
    days = [date(2025, 8, 20), date(2025, 8, 21), date(2025, 8, 22)]
    write_stored(e.root, "india", "HDFCBANK", dict(zip(days, [1990.0, 1991.2, 1964.6])))
    write_stored(e.root, "india", "NIFTY50", {d: 24000.0 for d in days})
    all_days = days + [date(2025, 8, 25), date(2025, 8, 26)]
    FakeTicker.frames = {"^NSEI": frame(all_days, [24000.0] * 5, "Asia/Kolkata"),
                         "HDFCBANK.NS": frame(all_days, [995.0, 995.6, 982.3, 982.05, 973.4], "Asia/Kolkata")}
    out = run(monkeypatch, capsys, "india")
    assert out["warnings"] == [] and "held" not in out and out["failed"] == []
    assert [(a["id"], a["factor"], a["source"], a["check_date"], a["nse_prev_close"], a["nse_ex_close"])
            for a in out["adjustments"]] == [("HDFCBANK-2025-08-26", 0.5, "nse_prev_close", "2025-08-22", 1964.1, 973.4)]
    assert out["rebased_bars"] == [{"ticker": "HDFCBANK", "date": "2025-08-25", "factor": 0.5}]
    con = connect("india")
    raw = dict(con.execute("SELECT date, close FROM ohlc_raw WHERE ticker = 'HDFCBANK'").fetchall())
    assert raw[date(2025, 8, 25)] == 1964.1 and raw[date(2025, 8, 26)] == 973.4
    assert con.execute("SELECT max(abs(ret_1d)) FROM returns WHERE ticker = 'HDFCBANK'").fetchone()[0] < 0.02
    out2 = run(monkeypatch, capsys, "india")
    assert out2["adjustments"] == [] and out2["warnings"] == [] and len(adj_rows(e.root, "india")) == 1


def test_india_mismatch_nse_unavailable_warns(tmp_path, monkeypatch, capsys):
    """The same re-based HDFCBANK closes, but no bhavcopy for the ex-date: a warning, no record."""
    e = make_env(tmp_path, monkeypatch, ["HDFCBANK"], date(2025, 8, 27))
    days = [date(2025, 8, 22), date(2025, 8, 25)]
    write_stored(e.root, "india", "HDFCBANK", {days[0]: 1964.6, days[1]: 1964.1})
    write_stored(e.root, "india", "NIFTY50", {days[0]: 24000.0, days[1]: 24001.0})
    ex = date(2025, 8, 26)
    FakeTicker.frames = {"^NSEI": frame(days + [ex], [24000.0, 24001.0, 24100.0], "Asia/Kolkata"),
                         "HDFCBANK.NS": frame(days + [ex], [982.3, 982.05, 973.4], "Asia/Kolkata")}
    out = run(monkeypatch, capsys, "india")
    assert out["adjustments"] == [] and adj_rows(e.root, "india") == []
    assert len(out["warnings"]) == 1
    assert out["warnings"][0].startswith("HDFCBANK: Yahoo's close differs from the stored close on 2 date(s) "
                                         "2025-08-22..2025-08-25 (Yahoo/stored 0.5000-0.5000); NSE check: "
                                         "bhavcopy 2025-08-26: no replay file")
    assert out["held"] == ["HDFCBANK"]
    hd = {f["ticker"]: f for f in out["failed"]}["HDFCBANK"]
    assert hd["error"] == "price basis unconfirmed (split/bonus?): new bars held, see warnings"
    assert "HDFCBANK" not in out["resolved_by_nse"]
    con = connect("india")
    assert con.execute("SELECT max(date) FROM ohlc WHERE ticker = 'HDFCBANK'").fetchone()[0] == date(2025, 8, 25)


def test_recorded_split_unblocks_the_bhavcopy_fill(tmp_path, monkeypatch):
    """basis_problem: a Yahoo split row after the previous session blocks a bhavcopy bar unless the
    split is recorded (then it is applied on read and the as-traded bar fits the views)."""
    e = make_env(tmp_path, monkeypatch, ["HDFCBANK"], date(2025, 8, 27))
    write_stored(e.root, "india", "HDFCBANK", {date(2025, 8, 25): 1964.1})
    cfg = load_market("india")
    bar = {"close": 973.4, "prev_close": 1964.1}
    blocked = price_nse_fallback.basis_problem(cfg, "HDFCBANK", date(2025, 8, 26), bar, [date(2025, 8, 26)])
    assert blocked == "Yahoo reports a split/bonus on 2025-08-26; price basis may differ"
    assert price_nse_fallback.basis_problem(cfg, "HDFCBANK", date(2025, 8, 26), bar, [date(2025, 8, 26)],
                                        {"HDFCBANK-2025-08-26"}) is None


# ---------- scoring across an ex-date ----------

def scoring_root(tmp_path, monkeypatch, detected_at: str, base: float, lo80: float, hi80: float):
    """NVDA stored as traded: 100 on 2026-09-08..09-11, then 51 from the 2:1 split's ex-date 09-14
    (a real +2% day). A call and a 1-day range made pre-open on 09-14 on the basis then known."""
    root = tmp_path / "root"
    monkeypatch.setattr(common, "ROOT", root)
    days = [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), EX, date(2026, 9, 15)]
    write_stored(root, "us", "NVDA", {d: (100.0 if d < EX else 51.0) for d in days})
    append_jsonl(day_file("us", "adjustments", EX), [
        adjust.adjustment_record("NVDA", EX, 0.5, "yahoo_splits", detected_at, yahoo_ratio=2.0)])
    made = "2026-09-14T12:00:00+00:00"                     # before the 13:30 UTC open
    append_jsonl(day_file("us", "predictions", date(2026, 9, 14)), [{
        "id": "2026-09-11-NVDA-1d", "made_at": made, "as_of_date": "2026-09-11", "ticker": "NVDA",
        "horizon_days": 1, "direction": "up", "confidence": 0.6, "rationale": "t", "evidence_ids": ["x"],
        "prompt_version": "t"}])
    append_jsonl(day_file("us", "ranges", date(2026, 9, 11)), [{
        "id": "2026-09-11-NVDA-1d", "made_at": made, "as_of_date": "2026-09-11", "session_date": "2026-09-14",
        "target_date": "2026-09-14", "ticker": "NVDA", "horizon_days": 1, "base_close": base, "center": 0.0,
        "sigma_h": 0.02, "lo50": base * 0.99, "hi50": base * 1.01, "lo80": lo80, "hi80": hi80,
        "naive_lo50": base * 0.99, "naive_hi50": base * 1.01, "naive_lo80": lo80, "naive_hi80": hi80,
        "direction": "up", "confidence": 0.6, "regime": "NORMAL", "calibration_id": "t", "notes": [], "inputs": []}])
    monkeypatch.setattr(score_predictions, "utc_now", lambda: "2026-09-16T12:00:00+00:00")
    monkeypatch.setattr(score_predictions, "utc_today", lambda: date(2026, 9, 16))
    return root


@pytest.mark.parametrize("detected_at, base, lo80, hi80", [
    # split recorded after the records were made: they are on the old basis (base 100)
    ("2026-09-15T12:00:00+00:00", 100.0, 97.5, 102.5),
    # split recorded before (same morning, 11:00 UTC): the records already used the new basis (base 50)
    ("2026-09-14T11:00:00+00:00", 50.0, 48.75, 51.25),
])
def test_call_and_range_made_before_ex_date_scored_after_it(tmp_path, monkeypatch, capsys, detected_at, base,
                                                           lo80, hi80):
    root = scoring_root(tmp_path, monkeypatch, detected_at, base, lo80, hi80)
    monkeypatch.setattr(sys, "argv", ["score_predictions", "--market", "us"])
    assert score_predictions.main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["scored"] == 1 and summary["ranges_scored"] == 1 and summary["late_skipped"] == {"calls": 0, "ranges": 0}
    out = [json.loads(x) for x in (root / "data" / "us" / "outcomes" / "2026" / "09" / "2026-09-16.jsonl")
           .read_text().splitlines()]
    assert len(out) == 1
    o = out[0]
    assert o["hit"] is True and o["actual_return"] == pytest.approx(0.02)   # +2%, not -49%
    assert (o["base_close"], o["target_close"]) == pytest.approx((base, base * 1.02))   # in the call's basis
    ro = [json.loads(x) for x in (root / "data" / "us" / "range_outcomes" / "2026" / "09" / "2026-09-16.jsonl")
          .read_text().splitlines()][0]
    assert ro["actual_close"] == pytest.approx(base * 1.02)                 # in the range's basis
    assert ro["hit80"] is True and ro["hit50"] is False
    assert ro["z"] == pytest.approx(math.log(1.02) / 0.02, rel=1e-6)
    assert ro["center_err_pct"] == pytest.approx(2.0, abs=1e-6)
    con = connect("us")
    rr = con.execute("SELECT actual_close, lo80, hi80 FROM range_record").fetchone()
    assert rr[1] <= rr[0] <= rr[2]                                          # stored edges and close agree


class RangeTicker:
    """A fake yfinance Ticker over a full daily series: history(period=...) gives its last
    PERIOD_BARS bars (a 1-month frame), history(start=...) everything from that date."""
    series: dict[str, pd.DataFrame] = {}
    PERIOD_BARS = 21

    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, period=None, start=None, **_):
        df = self.series.get(self.symbol, pd.DataFrame())
        if start is not None:
            return df[[i.date() >= date.fromisoformat(start) for i in df.index]].copy()
        return df.iloc[-self.PERIOD_BARS:].copy()


def bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5 and d != date(2026, 9, 7):      # US Labor Day
            out.append(d)
        d += timedelta(days=1)
    return out


def test_hold_persists_after_the_frame_moves_past_the_stored_bars(us, monkeypatch, capsys):
    """A re-base by 1/2 that no split row confirms for over a month: NVDA's stored bars end on
    2026-08-14 (old basis). Each run's 1-month frame soon holds none of them; the collector then
    fetches Yahoo's history from before the newest stored bar, so the re-base is seen again and
    the bars stay held (listed in warnings, held and failed) on every run. When the split row
    finally shows, the split is recorded and the held bars are written: no fake jump."""
    shutil.rmtree(us.root / "data" / "us" / "prices")              # only this test's bars
    old = bdays(date(2026, 8, 3), 10)                                # 08-03 .. 08-14
    write_stored(us.root, "us", "NVDA", {d: 200.0 + i for i, d in enumerate(old)})
    later = bdays(date(2026, 8, 17), 40)
    ex = later[0]
    full = old + later
    closes = [(200.0 + i) / 2 for i in range(10)] + [105.0 + 0.1 * i for i in range(40)]
    monkeypatch.setattr(sys.modules["yfinance"], "Ticker", RangeTicker)
    RangeTicker.series = {"SPY": frame(full, [500.0] * len(full), "America/New_York"),
                          "JPM": frame(full, [300.0] * len(full), "America/New_York")}
    for k, today in enumerate((later[3], later[30], later[38])):
        cut = [d for d in full if d < today]
        RangeTicker.series["NVDA"] = frame(cut, closes[:len(cut)], "America/New_York",
                                           splits={ex: 2.0} if k == 2 else None)
        for sym in ("SPY", "JPM"):
            RangeTicker.series[sym] = frame(cut, [500.0 if sym == "SPY" else 300.0] * len(cut), "America/New_York")
        monkeypatch.setattr(collect_prices, "utc_today", lambda t=today: t)
        monkeypatch.setattr(collect_prices, "utc_now", lambda t=today: f"{t}T12:00:00+00:00")
        out = run(monkeypatch, capsys, "us")
        con = connect("us")
        newest = con.execute("SELECT max(date) FROM ohlc_raw WHERE ticker = 'NVDA'").fetchone()[0]
        if k < 2:     # held, also a month later when the 1-month frame no longer covers 08-14
            assert out["held"] == ["NVDA"] and out["adjustments"] == []
            assert out["warnings"] == [f"NVDA: Yahoo's close differs from the stored close on 10 date(s) "
                                       f"2026-08-03..2026-08-14 (Yahoo/stored 0.5000-0.5000); a re-base by 1/2 that "
                                       f"no Yahoo split row or NSE bhavcopy confirms (yet): not recorded, new bars held"]
            assert any(f["ticker"] == "NVDA" and "new bars held" in f["error"] for f in out["failed"])
            assert newest == date(2026, 8, 14)
        else:
            assert "held" not in out and out["warnings"] == []
            assert [(a["id"], a["factor"]) for a in out["adjustments"]] == [("NVDA-2026-08-17", 0.5)]
            assert newest == later[37]
            assert con.execute("SELECT max(abs(ret_1d)) FROM returns WHERE ticker = 'NVDA'").fetchone()[0] < 0.01


def test_no_overlap_even_after_the_longer_fetch_holds(us, monkeypatch, capsys):
    """The judge's age-out case: Yahoo serves no bar we have stored, even when asked for more
    history (the fake ignores `start`). The first close is compared with our newest stored close
    across the gap: 105 vs 209 (x0.5024) cannot be verified, so the bars are held."""
    shutil.rmtree(us.root / "data" / "us" / "prices")              # only this test's bars
    old = bdays(date(2026, 8, 3), 10)
    write_stored(us.root, "us", "NVDA", {d: 200.0 + i for i, d in enumerate(old)})
    fb = bdays(date(2026, 8, 24), 20)
    monkeypatch.setattr(collect_prices, "utc_today", lambda: fb[-1] + timedelta(days=1))
    FakeTicker.frames = {"NVDA": frame(fb, [105.0 + 0.1 * i for i in range(20)], "America/New_York"),
                         "SPY": frame(fb, [500.0] * 20, "America/New_York"),
                         "JPM": frame(fb, [300.0] * 20, "America/New_York")}
    write_stored(us.root, "us", "SPY", {d: 500.0 for d in fb[:5]})
    write_stored(us.root, "us", "JPM", {d: 300.0 for d in fb[:5]})
    for _ in range(2):    # and again on the next run
        out = run(monkeypatch, capsys, "us")
        assert out["held"] == ["NVDA"] and out["adjustments"] == []
        assert out["warnings"] == [f"NVDA: no stored bar in Yahoo's frame to check the price basis; its first close "
                                   f"(2026-08-24) is 0.5024x our newest stored close (2026-08-14): not verifiable, "
                                   f"new bars held"]
        assert connect("us").execute("SELECT max(date) FROM ohlc_raw WHERE ticker = 'NVDA'").fetchone()[0] \
            == date(2026, 8, 14)


def test_split_row_with_unadjusted_yahoo_history_holds(us, monkeypatch, capsys):
    """A split row while neither Yahoo's history nor ours is adjusted (Yahoo itself steps -50% at
    the ex-date): a warning, no record, held."""
    tr = traded()
    write_stored(us.root, "us", "NVDA", dict(zip(US_DAYS[:9], tr[:9])))
    FakeTicker.frames["NVDA"] = frame(US_DAYS, tr, "America/New_York", splits={EX: 2.0})
    out = run(monkeypatch, capsys, "us")
    assert out["adjustments"] == [] and out["held"] == ["NVDA"]
    assert out["warnings"] == ["NVDA: Yahoo reports a split/bonus on 2026-09-14 (ratio 2) and steps by 0.5024 there, "
                               "but neither its history nor ours is adjusted; not recorded, new bars held"]


def test_rebase_by_a_non_simple_ratio_holds(us, monkeypatch, capsys):
    """Every stored close re-based by 0.7391 (no simple fraction p/q with p, q <= 20 within 0.1%):
    a warning, no record, held."""
    tr = traded(9)
    write_stored(us.root, "us", "NVDA", dict(zip(US_DAYS[:9], tr)))
    FakeTicker.frames["NVDA"] = frame(US_DAYS, [c * 0.7391 for c in tr] + [160.0, 161.0, 162.0, 163.0],
                                      "America/New_York")
    out = run(monkeypatch, capsys, "us")
    assert out["adjustments"] == [] and out["held"] == ["NVDA"]
    assert out["warnings"][0].endswith("a re-base by a ratio that is no simple fraction: not recorded, new bars held")


BHAV_HEADER = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
               "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER")


def synthetic_bhavcopy(replay: Path, day: date, prev_close: float, close: float):
    """A SYNTHETIC sec_bhavdata_full file (real column layout) with one TCS EQ row."""
    row = (f"TCS, EQ, {day:%d-%b-%Y}, {prev_close:.2f}, {close:.2f}, {close + 5:.2f}, {close - 5:.2f}, "
           f"{close:.2f}, {close:.2f}, {close:.2f}, 100000, 1000.00, 5000, 50000, 50.00")
    (replay / f"sec_bhavdata_full_{day:%d%m%Y}.csv").write_text(BHAV_HEADER + "\n" + row + "\n")


def india_bonus_1_10(tmp_path, monkeypatch, today: date):
    """TCS (synthetic): a 1:10 bonus (factor 10/11) with ex-date 2026-09-11, whose traded close
    1062 is 6% above the bonus-adjusted previous close 1001.82, so the step alone looks like an
    ordinary day. Stored as traded: 1100, 1101, 1102 (09-08..09-10). Yahoo serves them x10/11,
    no split row."""
    e = make_env(tmp_path, monkeypatch, ["TCS"], today)
    monkeypatch.setattr(collect_prices, "utc_now", lambda: f"{today}T02:30:00+00:00")
    stored_days = [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)]
    write_stored(e.root, "india", "TCS", dict(zip(stored_days, [1100.0, 1101.0, 1102.0])))
    write_stored(e.root, "india", "NIFTY50", {d: 25000.0 for d in stored_days})
    days = stored_days + [date(2026, 9, 11), date(2026, 9, 15)]
    yahoo = [1100.0 * 10 / 11, 1101.0 * 10 / 11, 1102.0 * 10 / 11, 1062.0, 1065.0]
    n = len([d for d in days if d < today])
    FakeTicker.frames = {"^NSEI": frame(days[:n], [25000.0] * n, "Asia/Kolkata"),
                         "TCS.NS": frame(days[:n], yahoo[:n], "Asia/Kolkata")}
    synthetic_bhavcopy(e.replay, date(2026, 9, 11), 1102.0, 1062.0)
    synthetic_bhavcopy(e.replay, date(2026, 9, 15), 1062.0, 1065.0)
    return e


def test_india_1_10_bonus_confirmed_by_the_prev_close_chain(tmp_path, monkeypatch, capsys):
    """Factor 10/11 >= 0.9: the step (1062 / 1102 = 0.9637) proves nothing; the chain does:
    PREV_CLOSE(09-11) 1102 = our stored close, PREV_CLOSE(09-15) 1062 = Yahoo's close of 09-11
    (new basis), so 09-11 is the ex-date."""
    e = india_bonus_1_10(tmp_path, monkeypatch, date(2026, 9, 16))
    out = run(monkeypatch, capsys, "india")
    assert out["warnings"] == [] and "held" not in out and out["failed"] == []
    assert [(a["id"], a["source"], a["check_date"], a["nse_prev_close"], a["nse_ex_close"]) for a in out["adjustments"]] \
        == [("TCS-2026-09-11", "nse_prev_close", "2026-09-10", 1102.0, 1062.0)]
    assert out["adjustments"][0]["factor"] == pytest.approx(10 / 11)
    con = connect("india")
    closes = [c for _, c in con.execute("SELECT date, close FROM ohlc WHERE ticker = 'TCS' ORDER BY date").fetchall()]
    assert closes == pytest.approx([1000.0, 1000.9091, 1001.8182, 1062.0, 1065.0], abs=1e-3)
    assert len(adj_rows(e.root, "india")) == 1


def test_india_1_10_bonus_without_the_next_session_is_held(tmp_path, monkeypatch, capsys):
    """The same bonus seen on 09-15, before the next session's bhavcopy exists: no proof yet, held."""
    india_bonus_1_10(tmp_path, monkeypatch, date(2026, 9, 15))
    out = run(monkeypatch, capsys, "india")
    assert out["adjustments"] == [] and out["held"] == ["TCS"]
    assert "NSE check: 2026-09-11: no step proves the ex-date and the next session's bhavcopy is not available yet" \
        in out["warnings"][0]


def test_step_matches():
    assert price_rebase.step_matches(973.4 / 1964.1, 0.5)
    assert not price_rebase.step_matches(1964.1 / 1964.6, 0.5)
    assert not price_rebase.step_matches(0.93, 0.8)            # nearer no step than the factor
    assert price_rebase.step_matches(0.82, 0.8)
    assert not price_rebase.step_matches(0.3, 0.5)


def test_superseded_record_is_left_out(tmp_path, monkeypatch, capsys):
    """A wrong record is corrected by a later row naming it in `supersedes` (here factor 1.0, a
    cancel): the views and adjust.load_adjustments drop the wrong one, and the collector does not record the
    same (ticker, ex-date) again."""
    root = tmp_path / "root"
    monkeypatch.setattr(common, "ROOT", root)
    write_stored(root, "us", "NVDA", {date(2026, 9, 11): 100.0, EX: 101.0})
    path = day_file("us", "adjustments", EX)
    append_jsonl(path, [adjust.adjustment_record("NVDA", EX, 0.5, "yahoo_splits", "2026-09-15T00:00:00+00:00")])
    con = connect("us")
    assert con.execute("SELECT close FROM ohlc WHERE ticker = 'NVDA' AND date = '2026-09-11'").fetchone()[0] == 50.0
    fix = {**adjust.adjustment_record("NVDA", EX, 1.0, "yahoo_splits", "2026-09-16T00:00:00+00:00"),
           "id": "NVDA-2026-09-14-fix1", "supersedes": "NVDA-2026-09-14", "note": "no split happened"}
    append_jsonl(path, [fix])
    con = connect("us")
    assert con.execute("SELECT close FROM ohlc WHERE ticker = 'NVDA' AND date = '2026-09-11'").fetchone()[0] == 100.0
    assert [r["id"] for r in con.execute("SELECT id FROM price_adjustments").df().to_dict("records")] == \
        ["NVDA-2026-09-14-fix1"]
    assert [a["id"] for a in adjust.load_adjustments("us")] == ["NVDA-2026-09-14-fix1"]
    assert len(adjust.load_adjustments("us", include_superseded=True)) == 2


def test_factor_after_and_split_fraction():
    a = [{"ticker": "X", "ex_date": date(2026, 9, 14), "factor": 0.5, "detected_at": "2026-09-15T00:00:00Z"},
         {"ticker": "X", "ex_date": date(2026, 9, 20), "factor": 2 / 3, "detected_at": "2026-09-21T00:00:00Z"},
         {"ticker": "Y", "ex_date": date(2026, 9, 14), "factor": 0.1, "detected_at": "2026-09-15T00:00:00Z"}]
    assert adjust.factor_after(a, "X", date(2026, 9, 11)) == pytest.approx(1 / 3)
    assert adjust.factor_after(a, "X", date(2026, 9, 14)) == pytest.approx(2 / 3)   # ex-date bar is new basis
    assert adjust.factor_after(a, "X", date(2026, 9, 20)) == 1.0
    assert adjust.factor_after(a, "X", date(2026, 9, 11), detected_after="2026-09-16T00:00:00+00:00") == pytest.approx(2 / 3)
    assert [str(adjust.split_fraction(x)) for x in (0.5, 0.4999, 2 / 3, 10 / 11, 2.0)] == ["1/2", "1/2", "2/3", "10/11", "2"]
    assert [adjust.split_fraction(x) for x in (0.618, 0.97, 1.0, 1.003, 0.0)] == [None, None, None, None, None]


# ---------- as-of replay roots ----------

def test_ai_replay_root_before_ex_date_is_unaffected(tmp_path, monkeypatch):
    """prepare's copy keeps an adjustment only when its ex-date is on or before D: a root as of
    09-11 (before the split) shows the bars exactly as stored, as the live run saw them; a root as of
    09-15 puts them on one basis."""
    src = tmp_path / "src"
    monkeypatch.setattr(common, "ROOT", src)
    days = [date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), EX, date(2026, 9, 15)]
    write_stored(src, "us", "NVDA", {d: (100.0 if d < EX else 51.0) for d in days})
    append_jsonl(day_file("us", "adjustments", EX), [
        adjust.adjustment_record("NVDA", EX, 0.5, "yahoo_splits", "2026-09-15T02:00:00+00:00", yahoo_ratio=2.0)])
    row = adj_rows(src, "us")[0]
    cut = pd.Timestamp("2026-09-14T12:15:00+00:00")
    assert not ar.keep_row("adjustments", row, date(2026, 9, 11), cut)
    assert ar.keep_row("adjustments", row, EX, cut)
    assert ar.rule_text("adjustments").startswith("ex_date <= D")

    before = tmp_path / "before"
    stats = ar.copy_asof("us", src, before, date(2026, 9, 11),
                         datetime(2026, 9, 14, 12, 15, tzinfo=timezone.utc))
    assert stats["kinds"]["adjustments"]["rows_kept"] == 0 and "adjustments" not in stats["excluded"]
    monkeypatch.setattr(common, "ROOT", before)
    con = connect("us")
    assert con.execute("SELECT date, close FROM ohlc WHERE ticker = 'NVDA' ORDER BY date").fetchall() == \
        [(date(2026, 9, 9), 100.0), (date(2026, 9, 10), 100.0), (date(2026, 9, 11), 100.0)]

    after = tmp_path / "after"
    stats = ar.copy_asof("us", src, after, date(2026, 9, 15), datetime(2026, 9, 16, 12, 15, tzinfo=timezone.utc))
    assert stats["kinds"]["adjustments"]["rows_kept"] == 1
    monkeypatch.setattr(common, "ROOT", after)
    con = connect("us")
    assert [c for _, c in con.execute("SELECT date, close FROM ohlc WHERE ticker = 'NVDA' ORDER BY date").fetchall()] \
        == [50.0, 50.0, 50.0, 51.0, 51.0]
