"""Unit tests for indicator formulas, regime rules and event dates."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import events as ev  # noqa: E402
import indicators as ind  # noqa: E402
import regime as rg  # noqa: E402
from common import load_market  # noqa: E402

TH = {"unstable_vol": 28, "event_vol": 20, "calm_vol": 16, "unstable_bench_vol": 0.25,
      "trend_return_5d": 0.015, "flat_return_5d": 0.005, "stress_vol_jump": 0.30}


def bars(closes, spread=1.0, volume=None):
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c + spread, "low": c - spread, "close": c,
                         "volume": volume if volume is not None else [1000] * len(c)}, index=idx)


def test_returns_and_nulls():
    df = bars([100, 110, 121])
    assert ind.ret(df["close"], 1) == pytest.approx(0.10)
    assert ind.ret(df["close"], 2) == pytest.approx(0.21)
    assert ind.ret(df["close"], 5) is None                     # too few bars -> explicit null
    assert ind.ema_ratio(df["close"]) is None


def test_rsi_extremes():
    assert ind.rsi(pd.Series(range(1, 30), dtype=float)) == 100.0
    assert ind.rsi(pd.Series(range(30, 1, -1), dtype=float)) == pytest.approx(0.0)
    assert ind.rsi(pd.Series([5.0] * 20)) == 50.0


def test_atr_constant_range():
    df = bars([100.0] * 30, spread=2.0)                        # true range is always 4
    assert ind.atr(df) == pytest.approx(4.0)


def test_bb_width_and_volume_ratio():
    df = bars([100.0] * 25, volume=[1000] * 24 + [3000])
    assert ind.bb_width(df["close"]) == 0.0
    assert ind.volume_ratio(df) == pytest.approx(3000 / 1100)


def test_obv_trend_clipped():
    df = bars([10, 11, 12, 13, 14, 15, 16], volume=[1, 1, 1, 1, 1, 1, 1000])
    assert ind.obv_trend(df) == 2.0


def test_beta_of_scaled_returns():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 300)
    bench = pd.Series(100 * np.exp(np.cumsum(r)), index=pd.bdate_range("2025-01-01", periods=300))
    stock = pd.Series(50 * np.exp(np.cumsum(2 * r)), index=bench.index)
    assert ind.beta(stock, bench) == pytest.approx(2.0, abs=1e-9)


def test_quality_blocked_with_few_bars():
    out = ind.compute(bars([100, 101, 102]))
    assert out["quality"] == "BLOCKED" and out["ret_1d"] is not None


@pytest.mark.parametrize("args,expected", [
    ((30, 0.0, 0.1, False), "UNSTABLE"),
    ((15, 0.0, 0.30, False), "UNSTABLE"),
    ((22, 0.0, 0.1, False), "EVENT_HEAVY"),
    ((15, 0.0, 0.1, True), "EVENT_HEAVY"),
    ((15, 0.02, 0.1, False), "TRENDING"),
    ((15, 0.0, 0.1, False), "CALM"),
    ((None, 0.02, 0.1, False), "EVENT_HEAVY"),                 # missing vol index -> conservative
    ((15, None, None, False), "EVENT_HEAVY"),                  # missing benchmark -> conservative
])
def test_regime_rules(args, expected):
    assert rg.classify(TH, *args)[0] == expected


def test_regime_stress():
    regime, stress, notes = rg.classify(TH, 18, 0.0, 0.1, False, vol_change_1d=0.35)
    assert (regime, stress) == ("UNSTABLE", True) and notes


def test_rule_dates():
    assert ev.rule_dates({"rule": "third_friday"}, date(2026, 10, 1), date(2026, 10, 31)) == [date(2026, 10, 16)]
    assert ev.rule_dates({"rule": "first_friday"}, date(2026, 11, 1), date(2026, 11, 30)) == [date(2026, 11, 6)]
    assert ev.rule_dates({"rule": "last_weekday", "weekday": 1},
                         date(2026, 10, 1), date(2026, 10, 31)) == [date(2026, 10, 27)]
    assert ev.rule_dates({"rule": "third_friday", "months": [3, 6, 9, 12]},
                         date(2026, 10, 1), date(2026, 12, 31)) == [date(2026, 12, 18)]
    assert len(ev.rule_dates({"rule": "weekly", "weekday": 1}, date(2026, 10, 1), date(2026, 10, 31))) == 4


def test_real_market_configs_and_holidays():
    india, us = load_market("india"), load_market("us")
    assert len(india["tickers"]) == 20 and len(us["tickers"]) == 20
    for cfg in (india, us):
        sectors = cfg["sectors"]
        assert len(sectors) == 10 and all(len(v) == 2 for v in sectors.values())
        assert {t for v in sectors.values() for t in v} == set(cfg["tickers"])
    assert not ev.is_session(india, date(2026, 10, 2))         # Gandhi Jayanti
    assert ev.is_session(us, date(2026, 10, 2))
    assert ev.next_session(us, date(2026, 10, 3)) == date(2026, 10, 5)   # Saturday -> Monday


def test_config_holidays_close_the_market():
    india = load_market("india")
    assert not ev.is_session(india, date(2026, 1, 15))          # Maharashtra civic polls (exchange_calendars)
    assert not ev.is_session(india, date(2027, 1, 26))          # Republic Day 2027 (config `holidays`)
    assert ev.next_session(india, date(2027, 1, 26)) == date(2027, 1, 27)
    assert ev.is_session({**india, "holidays": []}, date(2027, 1, 26)) is True  # library has no 2027 list
    assert not ev.is_session({"calendar": "XNYS", "holidays": ["2026-10-05"]}, date(2026, 10, 5))


def test_scheduled_macro_events():
    india, us = load_market("india"), load_market("us")
    evs = ev.market_events(india, date(2026, 10, 1), date(2027, 2, 28))
    assert {(e["date"], e["type"]) for e in evs} >= {(date(2026, 10, 7), "rbi_policy"), (date(2026, 12, 4), "rbi_policy"),
                                                     (date(2027, 2, 5), "rbi_policy"), (date(2027, 2, 1), "budget")}
    us_evs = ev.market_events(us, date(2026, 10, 14), date(2026, 10, 14))
    cpi = [e for e in us_evs if e["type"] == "cpi"]
    assert cpi and cpi[0]["major"] and cpi[0]["release"] == "08:30 ET"
    jobs = ev.market_events(us, date(2026, 11, 6), date(2026, 11, 6))
    assert jobs[0]["type"] == "jobs_report" and jobs[0]["release"] == "08:30 ET"
    india_jobs = [e for e in ev.market_events(india, date(2026, 11, 6), date(2026, 11, 6)) if e["type"] == "jobs_report"]
    assert india_jobs and india_jobs[0]["release"] is None       # released after the NSE close
    fomc27 = [e["date"] for e in ev.market_events(us, date(2027, 1, 1), date(2027, 12, 31)) if e["type"] == "fomc"]
    assert len(fomc27) == 8
    assert not any(e["major"] for e in ev.market_events(us, date(2027, 1, 1), date(2027, 12, 31))
                   if e["type"] == "fomc")                     # provisional until confirmed
    # 2027-01-01 is a holiday: no jobs report moved back to 2026-12-31, a provisional Jan 8 instead
    around = [(e["date"], e["major"]) for e in ev.market_events(us, date(2026, 12, 28), date(2027, 1, 12))
              if e["type"] == "jobs_report"]
    assert around == [(date(2027, 1, 8), False)]


def test_market_events_shift_to_previous_session():
    india = load_market("india")
    evs = ev.market_events(india, date(2026, 10, 1), date(2026, 10, 31))
    monthly = [e["date"] for e in evs if e["type"] == "fno_expiry"]
    assert monthly == [date(2026, 10, 27)]
    weekly = [e["date"] for e in evs if e["type"] == "weekly_expiry"]
    assert date(2026, 10, 20) not in weekly                    # Diwali holiday -> moved earlier
    assert date(2026, 10, 19) in weekly


def test_scorecard_last_30_days_and_since_start():
    import duckdb
    import report
    con = duckdb.connect()
    con.execute("""CREATE TABLE range_record (horizon_days INTEGER, target_date DATE, hit50 BOOLEAN, hit80 BOOLEAN,
                   naive_hit80 BOOLEAN, width80_pct DOUBLE, naive_width80_pct DOUBLE, is80_pct DOUBLE,
                   naive_is80_pct DOUBLE, center_err_pct DOUBLE, naive_center_err_pct DOUBLE)""")
    con.execute("""INSERT INTO range_record VALUES
        (1, current_date - 3,   true,  true,  true,  4.0, 5.0, 4.0, 5.0, 1.0, 1.5),
        (1, current_date - 20,  false, false, true,  4.0, 5.0, 9.0, 6.0, 3.0, 2.0),
        (1, current_date - 200, true,  true,  false, 6.0, 5.0, 6.0, 9.0, 1.0, 1.0)""")
    sc = con.execute(report.SCORECARD_SQL).df()
    rows = {r.win: r for r in sc.itertuples()}
    assert list(sc["win"]) == ["since start", "last 30 days"]
    assert rows["last 30 days"].n == 2 and rows["last 30 days"].c80 == 0.5 and rows["last 30 days"].nc80 == 1.0
    assert rows["since start"].n == 3 and abs(rows["since start"].c80 - 2 / 3) < 1e-9
    assert rows["last 30 days"].ce == 2.0 and rows["last 30 days"].nce == 1.75
    # and the report renders both rows
    us, empty = load_market("us"), pd.DataFrame()
    d = {"as_of": date(2026, 10, 2), "session": date(2026, 10, 5),
         "ranges": pd.DataFrame([{"ticker": "JPM", "horizon_days": 1, "direction": None, "confidence": None,
                                  "base_close": 100.0, "lo80": 98.0, "hi80": 102.0, "lo50": 99.0, "hi50": 101.0,
                                  "notes": [], "target_date": "2026-10-05"}]),
         "regime": empty, "features": empty, "quotes": pd.DataFrame(columns=["symbol", "price", "change_pct"]),
         "scored": empty, "last_target": None, "calls_scored": empty, "scorecard": sc, "by_regime": empty,
         "direction": empty, "conf_bands": empty, "market": empty, "calibration": empty,
         "company_events": pd.DataFrame(columns=["date", "name"])}
    rep, _, _ = report.build(us, d, {"repo_url": "https://example.com/r", "branch": "main"})
    assert "| 1d | last 30 days | 2 | 50% | 50% | 100% |" in rep and "| 1d | since start | 3 |" in rep


def test_overview_shows_5d_range_and_call_when_1d_was_skipped(monkeypatch):
    import charts
    cfg = {"name": "T", "sectors": {"Tech": ["AAPL", "MSFT"]},
           "tickers": {"AAPL": {"name": "Apple", "sector": "Tech"}, "MSFT": {"name": "Microsoft", "sector": "Tech"}}}
    idx = pd.bdate_range("2026-07-01", periods=60)
    bars = {t: pd.DataFrame({"close": np.linspace(100, 110, 60)}, index=idx) for t in ("AAPL", "MSFT")}
    # late run: the 1-day range targets a closed session and was not published, the 5-day one was
    ranges = pd.DataFrame([{"ticker": "AAPL", "horizon_days": 5, "lo80": 104.0, "hi80": 116.0,
                            "direction": "down", "confidence": 0.6}])
    past = pd.DataFrame(columns=["ticker", "target_date", "hit80"])
    captured = {}
    monkeypatch.setattr(charts, "save_png", lambda fig, path: captured.setdefault("fig", fig))
    charts.overview(cfg, bars, ranges, past, "CALM", idx[-1].date(), "unused.png")
    titles = {ax.get_title(loc="left").split()[0]: ax for ax in captured["fig"].axes if ax.get_visible()}
    aapl, msft = titles["AAPL"], titles["MSFT"]
    assert "5d ▼ down 60%" in aapl.get_title(loc="left") and "no range" not in aapl.get_title(loc="left")
    assert len(aapl.collections) == 1                            # the 80% cone out to 5 days is drawn
    assert "no range" in msft.get_title(loc="left") and not msft.collections


def test_slack_draft_fits_twelve_lines_and_flags_premarket_releases():
    import report
    us = load_market("us")
    rows = [{"ticker": t, "horizon_days": 1, "direction": "up", "confidence": 0.6, "base_close": 100.0,
             "lo80": 98.0, "hi80": 102.0, "lo50": 99.0, "hi50": 101.0, "notes": [], "target_date": "2026-10-06"}
            for t in list(us["tickers"])[:9]]
    empty = pd.DataFrame()
    d = {"as_of": date(2026, 10, 2), "session": date(2026, 10, 5), "ranges": pd.DataFrame(rows),
         "regime": empty, "features": empty, "quotes": pd.DataFrame(columns=["symbol", "price", "change_pct"]),
         "scored": empty, "last_target": None, "calls_scored": empty, "scorecard": empty, "by_regime": empty,
         "direction": empty, "conf_bands": empty, "market": empty, "calibration": empty,
         "company_events": pd.DataFrame(columns=["date", "name"])}
    settings = {"repo_url": "https://example.com/r", "branch": "main"}
    _, slack, _ = report.build(us, d, settings)
    filled = slack.replace("News: <!-- AGENT:news (the 2 most material items, one line each) -->", "News: a\nb")
    assert len(filled.strip().splitlines()) <= 12               # 9 calls used to give 15 lines
    assert "• +6 more in the report" in slack and slack.count("• ") == 4
    # US CPI at 08:30 ET on the session day: the brief says the calls were made before it
    d["session"] = date(2026, 10, 14)
    rep, slack, _ = report.build(us, d, settings)
    assert "Calls made before release: US CPI (September) at 08:30 ET." in rep
    assert "calls made before US CPI (September) (08:30 ET)" in slack.splitlines()[0]
