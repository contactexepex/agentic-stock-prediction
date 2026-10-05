"""Range engine inputs: past earnings-day moves, ex-dividend shift, beta split of the overnight
cue, option-implied volatility (collector math and the width blend), and their backtest arms.
Run: pytest -q"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect_events as ce  # noqa: E402
import collect_options as co  # noqa: E402
import events as ev  # noqa: E402
import range_inputs as ri  # noqa: E402
import rangelib as rl  # noqa: E402
from test_pipeline import MARKET, fat_tailed_walk, run, setup, weekdays, write_bars  # noqa: E402

XNYS = {"market": "x", "calendar": "XNYS", "timezone": "America/New_York"}
ALL_ON = {"earnings_history": {"enabled": True, "min_events": 2, "prior_events": 4, "lookback_events": 12,
                               "max_multiple": 8.0},
          "ex_dividend": {"enabled": True},
          "beta_split": {"enabled": True, "index_weight": 0.5, "own_weight": 0.5, "beta_clip": [0.0, 2.5],
                         "fit_sessions": 250},
          "implied_vol": {"enabled": True, "weight": 0.5, "max_age_days": 1, "max_expiry_days": 30,
                          "use_for_earnings": True}}


# ---------- pure math ----------

def test_earnings_multiple_fallback_shrinkage_and_window():
    assert rl.earnings_multiple([(0.05, 0.01, 1)], 3.0, 2, 4, 8.0) == (3.0, 1)       # too few events
    m, n = rl.earnings_multiple([(0.05, 0.01, 1)] * 4, 3.0, 2, 4, 8.0)                 # 5 sigma moves
    assert n == 4 and abs(m - math.sqrt((4 * 25 + 4 * 9) / 8)) < 1e-9
    m0, _ = rl.earnings_multiple([(0.05, 0.01, 1)] * 4, 3.0, 2, 0, 8.0)
    assert abs(m0 - 5.0) < 1e-9
    # a two-session window holds one normal day: 5.1^2 - 1 normal-day variance
    m2, _ = rl.earnings_multiple([(0.051, 0.01, 2)] * 4, 3.0, 2, 0, 8.0)
    assert abs(m2 ** 2 - (5.1 ** 2 - 1)) < 1e-6
    assert rl.earnings_multiple([(0.5, 0.01, 1)] * 4, 3.0, 2, 0, 8.0)[0] == 8.0       # capped
    assert rl.earnings_multiple([(0.0, 0.01, 1)] * 4, 3.0, 2, 0, 8.0)[0] == 1.0       # floor: a normal day


def test_implied_vol_math():
    var = rl.implied_variance(0.32, 36.5)
    assert abs(var - 0.32 ** 2 / 10) < 1e-12
    sd = 0.01
    # 5 sessions, implied total variance = 4 normal days + an earnings day of 4 sigma
    m = rl.implied_earnings_multiple(4 * sd ** 2 + 16 * sd ** 2, 5, sd, 8.0)
    assert abs(m - 4.0) < 1e-9
    assert rl.implied_earnings_multiple(sd ** 2, 5, sd, 8.0) == 1.0
    assert abs(rl.blend_sigma(0.01, 0.02 ** 2, 0.5) - math.sqrt(0.5 * 1e-4 + 0.5 * 4e-4)) < 1e-12


def test_ex_dividend_shift_and_beta_split():
    assert abs(rl.ex_dividend_shift(100.0, [1.5]) - math.log(0.985)) < 1e-12
    assert rl.ex_dividend_shift(100.0, [None, 0, 80]) == 0.0      # missing, zero and implausible
    # with an own cue: index part + own part net of beta x index
    c = rl.beta_split_center(1.5, 0.01, 0.02, 0.5, 0.25, 0.5)
    assert abs(c - (0.5 * 0.015 + 0.25 * (0.02 - 0.015))) < 1e-12
    assert abs(rl.beta_split_center(1.5, 0.01, None, 0.5, 0.25, 0.5) - 0.0075) < 1e-12
    assert rl.beta_split_center(None, 0.01, 0.02, 0.5, 0.25, 0.5) == 0.01         # fallback: direct cue
    assert rl.beta_split_center(1.0, None, None, 0.5, 0.25, 0.5) == 0.0
    # equal weights reduce to the direct cue whenever the stock has its own cue
    assert abs(rl.beta_split_center(1.3, 0.004, 0.01, 0.5, 0.5, 0.5) - 0.005) < 1e-12


def test_horizon_sigma_earnings_override():
    cfg = {"earnings_vol_multiple": 3.0, "regime_factor": {}, "major_event_factor": 1.15}
    s_fixed, _ = rl.horizon_sigma(0.01, 1, True, cfg, "CALM", False)
    s_hist, notes = rl.horizon_sigma(0.01, 1, True, cfg, "CALM", False, 5.0, ", 4 past moves")
    assert abs(s_fixed - 0.03) < 1e-12 and abs(s_hist - 0.05) < 1e-12
    assert notes == ["earnings in horizon (x5 day, 4 past moves)"]


# ---------- calendars and history ----------

def test_event_timing_and_reaction_sessions():
    et = "America/New_York"
    assert ce.timing(XNYS, pd.Timestamp("2026-07-14 06:45", tz=et)) == (date(2026, 7, 14), "before_open")
    assert ce.timing(XNYS, pd.Timestamp("2026-07-14 12:00", tz=et)) == (date(2026, 7, 14), "during")
    assert ce.timing(XNYS, pd.Timestamp("2026-07-14 16:20", tz=et)) == (date(2026, 7, 14), "after_close")
    assert ce.timing(XNYS, pd.Timestamp("2026-07-11 10:00", tz=et))[1] == "before_open"   # Saturday
    assert ce.timing(XNYS, "2026-07-14")[1] is None                                      # no time
    # reaction sessions: Tuesday 2026-07-14
    tue, wed = date(2026, 7, 14), date(2026, 7, 15)
    assert ri.affected_sessions(XNYS, tue, "before_open") == [tue]
    assert ri.affected_sessions(XNYS, tue, "after_close") == [wed]
    assert ri.affected_sessions(XNYS, tue, None) == [tue, wed]
    assert ri.affected_sessions(XNYS, date(2026, 7, 11), None) == [date(2026, 7, 13)]
    # an after-close report on the as-of date reacts inside a 1-day horizon
    assert ri.earnings_in_horizon(XNYS, [(tue, "after_close")], tue, wed)
    assert not ri.earnings_in_horizon(XNYS, [(tue, "before_open")], tue, wed)
    assert ri.earnings_in_horizon(XNYS, [(wed, "before_open")], tue, wed)
    assert ri.dividends_in_horizon(XNYS, [(wed, 1.0), (tue, 2.0)], tue, wed) == [1.0]
    # merging the same report from several sources keeps the best source
    kept = ce.merge_near([(date(2026, 7, 15), None, 2), (date(2026, 7, 14), "before_open", 0),
                          (date(2026, 4, 14), "after_close", 1)])
    assert kept == [(date(2026, 7, 14), "before_open", 0), (date(2026, 4, 14), "after_close", 1)]


def test_past_moves_and_event_cleanup():
    idx = ev._xcal("XNYS").sessions_in_range("2026-01-05", "2026-08-31")[:120]
    close = pd.Series(100.0, index=idx)
    d = idx[100].date()
    close.iloc[100:] = 110.0                    # +10% on the earnings day (before the open)
    sig = pd.Series(0.01, index=idx)
    moves = ri.past_moves(XNYS, close, sig, [(d, "before_open"), (idx[10].date(), None)], warmup=60)
    assert len(moves) == 1                      # the early one is inside the warm-up
    end, r, s, k = moves[0]
    assert end == d and abs(r - math.log(1.1)) < 1e-12 and s == 0.01 and k == 1
    m, n, med = ri.earnings_stats(moves * 3, {"earnings_vol_multiple": 3.0, **ALL_ON}, d)
    assert n == 3 and m > 3.0 and abs(med - math.log(1.1)) < 1e-12
    assert ri.earnings_stats(moves, {"earnings_vol_multiple": 3.0, **ALL_ON}, d - timedelta(days=1))[1] == 0

    t0 = pd.Timestamp("2026-01-01", tz="UTC")
    evdf = pd.DataFrame([
        {"ticker": "A", "type": "earnings", "date": date(2026, 4, 20), "timing": None, "amount": None,
         "source": "yfinance", "first_seen_at": t0},
        {"ticker": "A", "type": "earnings", "date": date(2026, 4, 22), "timing": None, "amount": None,
         "source": "yfinance", "first_seen_at": t0 + timedelta(days=5)},            # moved date
        {"ticker": "A", "type": "earnings", "date": date(2026, 1, 21), "timing": None, "amount": None,
         "source": "yfinance", "first_seen_at": t0},
        {"ticker": "A", "type": "earnings", "date": date(2026, 1, 22), "timing": "after_close", "amount": None,
         "source": "sec_history", "first_seen_at": t0},                              # same report, timed
        {"ticker": "A", "type": "ex_dividend", "date": date(2026, 2, 5), "timing": None, "amount": 0.5,
         "source": "yfinance_history", "first_seen_at": t0},
        {"ticker": "A", "type": "ex_dividend", "date": date(2026, 5, 5), "timing": None, "amount": None,
         "source": "yfinance", "first_seen_at": t0},
    ])
    cleaned = ri._clean(evdf)
    assert date(2026, 4, 20) not in set(cleaned["date"])
    assert ri.earnings_events(cleaned)["A"] == [(date(2026, 1, 22), "after_close"), (date(2026, 4, 22), None)]
    assert ri.dividend_events(cleaned)["A"] == [(date(2026, 2, 5), 0.5), (date(2026, 5, 5), 0.5)]


def test_fit_cue_beta_recovers_slope():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2025-01-01", periods=300)
    cue_r = rng.normal(0, 0.01, 300)
    bench_r = np.r_[0.0, 0.4 * cue_r[:-1]] + rng.normal(0, 0.002, 300)    # reacts to yesterday's cue
    cue = pd.Series(100 * np.exp(np.cumsum(cue_r)), index=idx)
    bench = pd.Series(100 * np.exp(np.cumsum(bench_r)), index=idx)
    b = ri.fit_cue_beta(bench, cue, None, 250)
    assert abs(b - 0.4) < 0.05
    assert ri.fit_cue_beta(bench, cue, idx[30], 250) is None              # too little history
    assert ri.enabled({"x": {"enabled": ["us"]}}, "x", "us") and not ri.enabled({"x": {"enabled": ["us"]}}, "x", "india")
    assert not ri.enabled({}, "x", "us")


# ---------- options collector ----------

def chain(strikes, ivs, bid=1.0, ask=1.2):
    return pd.DataFrame({"strike": strikes, "impliedVolatility": ivs, "bid": bid, "ask": ask,
                         "lastPrice": (bid + ask) / 2})


def test_option_snapshot_interpolates_at_the_money():
    calls = chain([90, 95, 100, 105, 110], [0.40, 0.35, 0.30, 0.28, 1e-5])
    puts = chain([90, 95, 100, 105, 110], [0.42, 0.37, 0.32, 0.30, 0.29])
    assert abs(co.iv_at(calls, 102.5) - 0.29) < 1e-12
    assert co.iv_at(calls, 120) == 0.28        # the 1e-5 quote is ignored, nearest usable strike
    snap = co.snapshot(calls, puts, 101.0)
    assert snap["strike"] == 100 and abs(snap["straddle"] - 2.2) < 1e-9
    assert abs(snap["atm_iv"] - (snap["call_iv"] + snap["put_iv"]) / 2) < 1e-6
    assert co.snapshot(chain([], []), chain([], []), 100.0) is None


def test_options_collector_skips_markets_without_chains(tmp_path):
    root, cfg = setup(tmp_path)
    r = run("collect_options.py", root, cfg)
    assert r.returncode == 0, r.stderr
    assert "skipped" in json.loads(r.stdout)
    assert not (root / "data" / MARKET / "options").exists()


# ---------- ranges.py with every input ----------

def jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def test_ranges_apply_inputs(tmp_path):
    root, cfg = setup(tmp_path)
    mfile = cfg / "markets" / f"{MARKET}.yaml"
    mfile.write_text(mfile.read_text() + "\noptions: yfinance\nindex_cue: {symbol: BENCH, beta: 1.0}\n")
    rc = yaml.safe_load((cfg / "ranges.yaml").read_text())
    rc.update(ALL_ON)
    (cfg / "ranges.yaml").write_text(yaml.safe_dump(rc))

    rng = np.random.default_rng(21)
    n = 520
    days = weekdays(date(2024, 6, 3), n)
    br = rng.normal(0.0003, 0.01, n)
    bench = 100 * np.exp(np.cumsum(br))
    aapl = 150 * np.exp(np.cumsum(1.2 * br + rng.normal(0, 0.01, n)))
    write_bars(root, {"BENCH": list(bench), "AAPL": list(aapl), "MSFT": fat_tailed_walk(rng, n, 300, 0.012),
                      "VOLX": [15.0] * n}, days)
    assert run("features.py", root, cfg).returncode == 0
    assert run("calibrate.py", root, cfg).returncode == 0

    as_of = days[-1]
    nxt = ev.next_session({"calendar": "XNYS"}, as_of, include=False)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ev_rows = [{"id": f"AAPL-earnings-{d}", "date": str(d), "type": "earnings", "ticker": "AAPL",
                "name": "Apple earnings", "source": "sec_history", "first_seen_at": now, "timing": "before_open"}
               for d in (days[200], days[263], days[326], days[389], days[452])]
    ev_rows += [{"id": f"AAPL-earnings-{nxt}", "date": str(nxt), "type": "earnings", "ticker": "AAPL",
                 "name": "Apple earnings", "source": "yfinance", "first_seen_at": now},
                {"id": f"MSFT-ex_dividend-{nxt}", "date": str(nxt), "type": "ex_dividend", "ticker": "MSFT",
                 "name": "Microsoft ex-dividend", "source": "yfinance", "first_seen_at": now, "amount": 3.0}]
    jsonl(root / "data" / MARKET / "events" / "2026" / "01" / "2026-01-01.jsonl", ev_rows)
    today = datetime.now(timezone.utc).date()
    jsonl(root / "data" / MARKET / "quotes" / f"{today:%Y}" / f"{today:%m}" / f"{today}.jsonl",
          [{"symbol": "BENCH", "yahoo": "BENCH", "ts": now, "price": 101, "prev_close": 100,
            "change_pct": 0.01, "collected_at": now}])
    expiry = str(nxt + timedelta(days=14))
    jsonl(root / "data" / MARKET / "options" / f"{today:%Y}" / f"{today:%m}" / f"{today}.jsonl",
          [{"id": f"{today}-MSFT-{expiry}", "ticker": "MSFT", "collected_at": now, "expiry": expiry,
            "days_to_expiry": 14, "spot": 300, "strike": 300, "call_iv": 0.6, "put_iv": 0.6, "atm_iv": 0.6,
            "straddle": 20, "straddle_pct": 0.067, "source": "yfinance"}])

    r = run("ranges.py", root, cfg)
    assert r.returncode == 0, r.stderr
    rows = {x["id"]: x for f in (root / "data" / MARKET / "ranges").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())}
    a1, m1, m5 = rows[f"{as_of}-AAPL-1d"], rows[f"{as_of}-MSFT-1d"], rows[f"{as_of}-MSFT-5d"]
    assert "earnings_history" in a1["inputs"] and "beta_split" in a1["inputs"]
    assert any("past moves" in x for x in a1["notes"]) and a1["center"] > 0      # positive beta x +1% cue
    for m in (m1, m5):
        assert {"implied_vol", "ex_dividend"} <= set(m["inputs"])
        assert m["lo80"] < m["lo50"] < m["hi50"] < m["hi80"]
    # 60% IV against ~19% realized: the blend widens the range well beyond EWMA alone
    feats = [x for f in (root / "data" / MARKET / "features").glob("**/*.jsonl")
             for x in map(json.loads, f.read_text().splitlines()) if x["ticker"] == "MSFT"]
    sd = feats[-1]["ewma_vol"] / math.sqrt(252)
    assert m1["sigma_h"] > 1.5 * sd
    # the ex-dividend drop is applied on top of the (capped) cue drift
    assert m1["center"] < 0.5 * m1["sigma_h"] + math.log(1 - 3.0 / m1["base_close"]) + 1e-9


def test_backtest_scores_inputs(tmp_path):
    root, cfg = setup(tmp_path)
    mfile = cfg / "markets" / f"{MARKET}.yaml"
    mfile.write_text(mfile.read_text() + "\npremarket_quotes: true\nindex_cue: {symbol: BENCH, beta: 1.0}\n")
    rc = yaml.safe_load((cfg / "ranges.yaml").read_text())
    rc.update(ALL_ON)
    (cfg / "ranges.yaml").write_text(yaml.safe_dump(rc))
    rng = np.random.default_rng(9)
    n = 560
    days = weekdays(date(2024, 1, 1), n)
    aapl = np.array(fat_tailed_walk(rng, n, 150, 0.015))
    # monthly dividends of 3% that the price really drops by, and big quarterly earnings-day moves
    divs, earn = list(range(100, n, 21)), list(range(130, n, 63))
    r = np.diff(np.log(aapl), prepend=np.log(aapl[0]))
    for i in divs:
        r[i] += math.log(0.97)
    for i in earn:
        r[i] += rng.choice([-1, 1]) * 0.08
    aapl = 150 * np.exp(np.cumsum(r))
    write_bars(root, {"BENCH": fat_tailed_walk(rng, n, 100, 0.01), "VOLX": [15.0] * n, "AAPL": list(aapl),
                      "MSFT": fat_tailed_walk(rng, n, 300, 0.02)}, days)
    now = "2026-01-01T00:00:00+00:00"
    rows = [{"id": f"AAPL-ex_dividend-{days[i]}", "date": str(days[i]), "type": "ex_dividend", "ticker": "AAPL",
             "name": "d", "source": "yfinance_history", "first_seen_at": now, "amount": round(0.03 * aapl[i - 1], 4)}
            for i in divs]
    rows += [{"id": f"AAPL-earnings-{days[i]}", "date": str(days[i]), "type": "earnings", "ticker": "AAPL",
              "name": "e", "source": "sec_history", "first_seen_at": now, "timing": "before_open"} for i in earn]
    jsonl(root / "data" / MARKET / "events" / "2026" / "01" / "2026-01-01.jsonl", rows)

    out_md = tmp_path / "bt.md"
    r = run("backtest.py", root, cfg, "--eval-sessions", "300", "--out", str(out_md))
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["event_history"] == {"earnings": len(earn), "dividends": len(divs)}
    for h in ("1", "5"):
        inp = s["inputs"][h]
        assert inp["ex_dividend"]["applies"] > 0 and inp["ex_dividend"]["verdict"] == "improves"
        assert inp["earnings_history"]["applies"] > 0
        assert inp["implied_vol"]["verdict"].startswith("live only")
        assert inp["beta_split"]["verdict"] == "same"     # equal weights + own cue = direct cue
    assert s["inputs"]["1"]["earnings_history"]["verdict"] == "improves"   # 8% moves need > x3
    assert "## Range inputs" in out_md.read_text()
    assert not (root / "reports").exists()
