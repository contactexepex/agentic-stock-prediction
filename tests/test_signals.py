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


def test_market_events_shift_to_previous_session():
    india = load_market("india")
    evs = ev.market_events(india, date(2026, 10, 1), date(2026, 10, 31))
    monthly = [e["date"] for e in evs if e["type"] == "fno_expiry"]
    assert monthly == [date(2026, 10, 27)]
    weekly = [e["date"] for e in evs if e["type"] == "weekly_expiry"]
    assert date(2026, 10, 20) not in weekly                    # Diwali holiday -> moved earlier
    assert date(2026, 10, 19) in weekly
