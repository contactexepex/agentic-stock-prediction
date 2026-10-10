"""Unit tests for indicator formulas, regime rules and event dates."""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.core import calendar as ev  # noqa: E402
from marketbrief.analytics import indicators as ind  # noqa: E402
from marketbrief.analytics import regime as rg  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402

TH = {"unstable_vol": 28, "event_vol": 20, "calm_vol": 16, "unstable_bench_vol": 0.25,
      "trend_return_5d": 0.015, "flat_return_5d": 0.005, "stress_vol_jump": 0.30}


def bars(closes, spread=1.0, volume=None):
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c + spread, "low": c - spread, "close": c,
                         "volume": volume if volume is not None else [1000] * len(c)}, index=idx)


def test_returns_and_nulls():
    df = bars([100, 110, 121])
    assert ind.period_return(df["close"], 1) == pytest.approx(0.10)
    assert ind.period_return(df["close"], 2) == pytest.approx(0.21)
    assert ind.period_return(df["close"], 5) is None                     # too few bars -> explicit null
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
    assert {(e["date"], e["type"]) for e in evs} >= {
        (date(2026, 10, 7), "rbi_policy"), (date(2026, 12, 4), "rbi_policy"),
        (date(2027, 2, 5), "rbi_policy"), (date(2027, 2, 1), "budget")}
    us_evs = ev.market_events(us, date(2026, 10, 14), date(2026, 10, 14))
    cpi = [e for e in us_evs if e["type"] == "cpi"]
    assert cpi and cpi[0]["major"] and cpi[0]["release"] == "08:30 ET"
    jobs = ev.market_events(us, date(2026, 11, 6), date(2026, 11, 6))
    assert jobs[0]["type"] == "jobs_report" and jobs[0]["release"] == "08:30 ET"
    india_jobs = [e for e in ev.market_events(india, date(2026, 11, 6), date(2026, 11, 6))
                  if e["type"] == "jobs_report"]
    assert india_jobs and india_jobs[0]["release"] is None       # released after the NSE close
    fomc27 = [e["date"] for e in ev.market_events(us, date(2027, 1, 1), date(2027, 12, 31)) if e["type"] == "fomc"]
    assert len(fomc27) == 8
    assert not any(e["major"] for e in ev.market_events(us, date(2027, 1, 1), date(2027, 12, 31))
                   if e["type"] == "fomc")                     # provisional until confirmed
    # 2027-01-01 is a holiday: no jobs report moved back to 2026-12-31, a provisional Jan 8 instead
    around = [(e["date"], e["major"]) for e in ev.market_events(us, date(2026, 12, 28), date(2027, 1, 12))
              if e["type"] == "jobs_report"]
    assert around == [(date(2027, 1, 8), False)]


def test_index_rebalance_dates():
    india, us = load_market("india"), load_market("us")
    # S&P 500: the third Friday of Mar/Jun/Sep/Dec (2026-09-18: changes effective before the
    # open of Monday 2026-09-21), the same day as triple witching, also when a holiday moves it
    us_evs = ev.market_events(us, date(2026, 1, 1), date(2027, 12, 31))
    reb = [e for e in us_evs if e["type"] == "index_rebalance"]
    assert [e["date"] for e in reb if e["date"].year == 2026] == \
        [date(2026, 3, 20), date(2026, 6, 18), date(2026, 9, 18), date(2026, 12, 18)]   # Jun 19: Juneteenth
    assert [e["date"] for e in reb] == [e["date"] for e in us_evs if e["type"] == "triple_witching"]
    assert not any(e["major"] for e in reb)
    # Nifty 50: at the close of the session before the last session of March and September
    # (2025-03-27; 2026-03-27 because 2026-03-31 was a holiday; 2026-09-29, also the F&O expiry)
    in_evs = ev.market_events(india, date(2025, 1, 1), date(2026, 12, 31))
    nifty = [e for e in in_evs if e["type"] == "index_rebalance"]
    assert [e["date"] for e in nifty] == [date(2025, 3, 27), date(2025, 9, 29), date(2026, 3, 27), date(2026, 9, 29)]
    assert not any(e["major"] for e in nifty)
    fno = {e["date"] for e in in_evs if e["type"] == "fno_expiry"}
    assert date(2026, 9, 29) in fno and date(2026, 3, 27) not in fno and date(2026, 3, 30) in fno
    # not major: alone it does not raise EVENT_HEAVY (2026-03-27: the expiry is 3 days later)
    assert ev.major_events_near(in_evs, date(2026, 3, 27)) == []


def test_provisional_event_dates_are_flagged_and_named():
    """Issue #15: unconfirmed dates carry provisional: true and say so in the name the report shows."""
    india, us = load_market("india"), load_market("us")
    reb = {e["date"]: e for e in ev.market_events(us, date(2026, 1, 1), date(2027, 12, 31))
           if e["type"] == "index_rebalance"}
    provisional = sorted(day for day, e in reb.items() if e["provisional"])
    assert provisional == [date(2026, 6, 18), date(2027, 6, 17)]          # moved by Juneteenth
    assert reb[date(2027, 6, 17)]["name"].endswith("(provisional date)")
    assert "provisional" not in reb[date(2027, 3, 19)]["name"]
    nifty = {e["date"]: e for e in ev.market_events(india, date(2026, 1, 1), date(2027, 12, 31))
             if e["type"] == "index_rebalance"}
    assert {day: e["provisional"] for day, e in nifty.items()} == {
        date(2026, 3, 27): False, date(2026, 9, 29): False, date(2027, 3, 30): True, date(2027, 9, 29): True}
    assert nifty[date(2027, 3, 30)]["name"].endswith("(provisional date)")
    # a fixed date already named provisional is flagged without a second suffix
    fomc = next(e for e in ev.market_events(us, date(2027, 1, 27), date(2027, 1, 27)) if e["type"] == "fomc")
    assert fomc["provisional"] and fomc["name"] == "FOMC rate decision (provisional)"
    assert not any(e["provisional"] for e in ev.market_events(us, date(2026, 10, 1), date(2026, 10, 31)))


def test_month_end_rule_and_session_offset(tmp_path):
    assert ev.rule_dates({"rule": "month_end", "months": [3, 9]}, date(2026, 1, 1), date(2026, 12, 31)) == \
        [date(2026, 3, 31), date(2026, 9, 30)]
    assert ev.rule_dates({"rule": "month_end"}, date(2024, 2, 1), date(2024, 2, 29)) == [date(2024, 2, 29)]
    spec = tmp_path / "events.yaml"
    spec.write_text("rules:\n"
                    "  - {markets: [t], type: a, rule: month_end, months: [10], name: A}\n"
                    "  - {markets: [t], type: b, rule: month_end, months: [10], session_offset: -1, name: B}\n"
                    "  - {markets: [t], type: c, rule: month_end, months: [10], session_offset: -2, name: C}\n")
    # 2026-10-31 is a Saturday and 2026-10-30 a configured holiday: last session Thu 2026-10-29
    cfg = {"market": "t", "calendar": "XNYS", "holidays": ["2026-10-30"]}
    got = {e["type"]: e["date"] for e in ev.market_events(cfg, date(2026, 10, 1), date(2026, 11, 30), path=spec)}
    assert got == {"a": date(2026, 10, 29), "b": date(2026, 10, 28), "c": date(2026, 10, 27)}
    spec.write_text("rules:\n  - {markets: [t], type: a, rule: month_end, session_offset: 1, name: A}\n")
    with pytest.raises(ValueError):
        ev.market_events(cfg, date(2026, 10, 1), date(2026, 10, 31), path=spec)


def test_sector_etfs_cover_the_watchlist():
    from marketbrief.core.market_config import sector_etf_problems
    india, us = load_market("india"), load_market("us")
    for cfg in (india, us):
        assert sector_etf_problems(cfg) == []
        assert all(cfg["symbols"][k]["role"] == "sector_etf" for k in cfg["sector_etfs"].values())
        assert all(m["sector_etf"] == cfg["sector_etfs"].get(m["sector"]) for m in cfg["tickers"].values())
    # US: every watchlist sector has its own ETF (10 sectors, 10 ETFs), Airlines -> JETS
    assert set(us["sector_etfs"]) == set(us["sectors"]) and len(set(us["sector_etfs"].values())) == 10
    assert us["sector_etfs"]["Airlines"] == "JETS" and us["sector_etfs"]["Insurance"] == "IAK"
    assert us["tickers"]["DAL"]["sector_etf"] == "JETS" and us["symbols"]["JETS"]["yahoo"] == "JETS"
    # India: only three Nifty sector indices have daily history on Yahoo
    assert india["sector_etfs"] == {"Banks": "NIFTYBANK", "IT": "NIFTYIT", "Pharma": "NIFTYPHARMA"}


def test_sector_etf_config_mistakes_are_reported_not_fatal():
    from marketbrief.core.market_config import sector_etf_map, sector_etf_problems
    cfg = {"sectors": {"Tech": ["A"], "Energy": ["B"]},
           "symbols": {"T1": {"role": "sector_etf", "sectors": ["Tech"]},
                       "T2": {"role": "sector_etf", "sectors": ["Tech", "Tehc"]},
                       "BM": {"role": "benchmark", "sectors": ["Energy"]}}}
    assert sector_etf_map(cfg) == {"Tech": "T1"}               # first wins; typo and non-ETF skipped
    assert sector_etf_problems(cfg) == ["sector 'Tech' is mapped to both T1 and T2",
                                        "symbol T2: unknown sector 'Tehc'",
                                        "symbol BM: `sectors` is only for role sector_etf"]


def test_context_lists_sectors_without_an_etf():
    from marketbrief.pipeline import context
    india = load_market("india")
    gaps = context.sector_gaps(india)
    for s in ("Insurance", "Transport", "Energy", "Autos", "Consumer goods", "Construction", "Metals"):
        assert s in gaps
    assert "Banks" not in gaps and context.sector_gaps(load_market("us")) == ""


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
    from marketbrief.presentation.report import build, gather
    con = duckdb.connect()
    con.execute("""CREATE TABLE range_record (horizon_days INTEGER, horizon_label VARCHAR, target_date DATE,
                   hit50 BOOLEAN, hit80 BOOLEAN, naive_hit80 BOOLEAN, width80_pct DOUBLE, naive_width80_pct DOUBLE,
                   is80_pct DOUBLE, naive_is80_pct DOUBLE, center_err_pct DOUBLE, naive_center_err_pct DOUBLE)""")
    con.execute("""INSERT INTO range_record VALUES
        (1, 'n_plus_k',  current_date - 3,   true,  true,  true,  4.0, 5.0, 4.0, 5.0, 1.0, 1.5),
        (1, 'n_plus_k',  current_date - 20,  false, false, true,  4.0, 5.0, 9.0, 6.0, 3.0, 2.0),
        (1, 'n_plus_k',  current_date - 200, true,  true,  false, 6.0, 5.0, 6.0, 9.0, 1.0, 1.0),
        (1, 'legacy_cc', current_date - 210, false, false, false, 6.0, 5.0, 6.0, 9.0, 1.0, 1.0)""")
    sc = con.execute(gather.SCORECARD_SQL).df()
    rows = {r.win: r for r in sc[sc["label"] == "n_plus_k"].itertuples()}
    assert list(sc["win"]) == ["since start", "last 30 days", "since start"]   # the old window after N+1, apart
    assert list(sc["label"]) == ["n_plus_k", "n_plus_k", "legacy_cc"]
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
    rep, _, _ = build.build(us, d, {"repo_url": "https://example.com/r", "branch": "main"})
    assert "| 1d | last 30 days | 2 | 50% | 50% | 100% |" in rep and "| 1d | since start | 3 |" in rep
    assert "| 1d legacy_cc | since start | 1 | 0% |" in rep


def _view_company(ticker, ranges, close=110.0):
    return {"ticker": ticker, "name": ticker, "sector": "Tech", "close": close, "ret_1d": 0.01, "quality": "OK",
            "history": [], "ranges": ranges, "calls": [], "events": [], "news": [],
            "record": {"ranges": {}, "calls": {"n": 0, "hits": 0, "text": ""}}}


def _rng(h, late=False, direction=None, confidence=None, horizon_label="legacy_cc"):
    nk = horizon_label == "n_plus_k"
    phrase = f"in {h + 1} trading days (N+{h})" if nk else (
        "after the next trading day" if h == 1 else f"in {h} trading days")
    return {"h": h, "horizon_label": horizon_label, "phrase": phrase, "target_date": "2026-10-09",
            "target_label": "Fri 9 Oct", "base_close": 110.0,
            "center_price": 110.0, "lo50": 107.0, "hi50": 113.0, "lo80": 104.0, "hi80": 116.0,
            "direction": direction, "confidence": confidence, "late": late, "notes": []}


def test_ranges_chart_uses_5d_when_1d_was_skipped_and_labels_late(monkeypatch):
    import charts
    # mid-session run: no 1-day range was published, the 5-day ranges are late (never forecasts)
    view = {"currency": "USD", "companies": [_view_company("AAPL", [_rng(5, late=True)]), _view_company("MSFT", [])]}
    captured = {}
    monkeypatch.setattr(charts, "save_png", lambda fig, _path: captured.setdefault("fig", fig))
    assert charts.ranges_chart(view, "unused.png")
    fig = captured["fig"]
    texts = [t.get_text() for ax in fig.axes for t in ax.texts] + [t.get_text() for t in fig.texts]
    assert any("in 5 trading days (by Fri 9 Oct)" in t for t in texts)
    assert any("late, not a forecast" in t for t in texts) and not any("▼" in t or "▲" in t for t in texts)
    assert [t.get_text() for t in fig.axes[0].get_yticklabels()] == ["AAPL"]   # MSFT has no range
    # a non-late 5-day call is shown with its direction and confidence
    view["companies"][0]["ranges"] = [_rng(5, direction="down", confidence=0.6)]
    captured.clear()
    charts.ranges_chart(view, "unused.png")
    texts = [t.get_text() for t in captured["fig"].axes[0].texts]
    assert any("▼ down 60%" in t for t in texts)
    plt_close(captured["fig"])
    # N+k ranges (decision 37): the shortest horizon with a range that is not late, named by its window
    view["companies"][0]["ranges"] = [_rng(1, late=True, horizon_label="n_plus_k"),
                                      _rng(3, horizon_label="n_plus_k"), _rng(5, horizon_label="n_plus_k")]
    captured.clear()
    charts.ranges_chart(view, "unused.png")
    texts = [t.get_text() for t in captured["fig"].texts]
    assert any("Where each price may be in 4 trading days (N+3) (by Fri 9 Oct)" in t for t in texts)
    plt_close(captured["fig"])


def plt_close(fig):
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_slack_draft_fits_twelve_lines_and_flags_premarket_releases(monkeypatch):
    from marketbrief.presentation.report import build
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
    _, slack, _ = build.build(us, d, settings)
    filled = re.sub(r"<!-- AGENT:top3[^>]*-->", "• a\n• b\n• c", slack)
    assert len(filled.strip().splitlines()) <= 12               # 9 calls used to give 15 lines
    # the summary names the number of calls and at most three of them; details are in the report
    assert "Calls today: 9 · " in slack and "and 6 more in the report" in slack
    from marketbrief.core.settings import slack_link_url   # the link opens the market's page in the app
    assert slack.strip().splitlines()[-1] == f"Market page: {slack_link_url().rstrip('/')}/us"
    # with C2's secret and brief_link_url the last line is the day's public brief page instead (same line count)
    from marketbrief.presentation.reader.links import brief_path
    monkeypatch.setenv("BRIEF_LINK_SECRET", "test-secret")
    _, briefed, _ = build.build(us, d, {**settings, "brief_link_url": "https://gw.example"})
    assert briefed.strip().splitlines()[-1] == "Today's brief: https://gw.example" + brief_path("us", "2026-10-05")
    assert len(briefed.splitlines()) == len(slack.splitlines())
    monkeypatch.delenv("BRIEF_LINK_SECRET")
    assert "market mood" not in slack.splitlines()[0]           # no regime row in this fixture
    # US CPI at 08:30 ET on the session day: the brief says the calls were made before it
    d["session"] = date(2026, 10, 14)
    rep, slack, _ = build.build(us, d, settings)
    assert "Calls made before release: US CPI (September) at 08:30 ET." in rep
    assert "calls made before US CPI (September) (08:30 ET)" in slack.splitlines()[0]
