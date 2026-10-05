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
    assert notes == ["earnings in horizon (x5.0 day, 4 past moves)"]
    assert rl.horizon_sigma(0.01, 1, True, cfg, "CALM", False)[1] == ["earnings in horizon (x3.0 day)"]


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


def ranges_rows(root: Path) -> dict:
    return {x["id"]: x for f in (root / "data" / MARKET / "ranges").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())}


def test_ranges_apply_inputs(tmp_path):
    """Exact centre and width of ranges with every input on (and the IV shadow with it off)."""
    root, cfg = setup(tmp_path)
    mfile = cfg / "markets" / f"{MARKET}.yaml"
    mfile.write_text(mfile.read_text() + "\noptions: yfinance\nindex_cue: {symbol: BENCH, beta: 1.0}\n")
    rc = yaml.safe_load((cfg / "ranges.yaml").read_text())
    rc.update(ALL_ON)
    rc["regime_factor"] = {}            # no regime or market-event widening: exact sigmas below
    rc["major_event_factor"] = 1.0
    rc["earnings_vol_multiple_by_market"] = {MARKET: 2.5, "othermarket": 9.0}   # this market's prior: x2.5
    (cfg / "ranges.yaml").write_text(yaml.safe_dump(rc))

    rng = np.random.default_rng(21)
    n = 520
    days = weekdays(date(2024, 6, 3), n)
    xnys = {"calendar": "XNYS"}
    earn_idx = [i for i in (200, 263, 326, 389, 452) if ev.is_session(xnys, days[i])]
    br = rng.normal(0.0003, 0.01, n)
    ar = 1.2 * br + rng.normal(0, 0.01, n)
    for i in earn_idx:
        ar[i] += 0.07                   # 7% earnings-day jumps: far more than x3 a normal day
    bench, aapl = 100 * np.exp(np.cumsum(br)), 150 * np.exp(np.cumsum(ar))
    write_bars(root, {"BENCH": list(bench), "AAPL": list(aapl), "MSFT": fat_tailed_walk(rng, n, 300, 0.012),
                      "VOLX": [15.0] * n}, days)
    as_of = days[-1]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    today = datetime.now(timezone.utc).date()
    # index cue quoted before the features run, timestamped before the next session's close
    jsonl(root / "data" / MARKET / "quotes" / f"{today:%Y}" / f"{today:%m}" / f"{today}.jsonl",
          [{"symbol": "BENCH", "yahoo": "BENCH", "ts": f"{as_of}T22:00:00+00:00", "price": 101,
            "prev_close": 100, "change_pct": 0.01, "collected_at": now}])
    assert run("features.py", root, cfg).returncode == 0
    assert run("calibrate.py", root, cfg).returncode == 0

    nxt = ev.next_session(xnys, as_of, include=False)
    ev_rows = [{"id": f"AAPL-earnings-{days[i]}", "date": str(days[i]), "type": "earnings", "ticker": "AAPL",
                "name": "Apple earnings", "source": "sec_history", "first_seen_at": now, "timing": "before_open"}
               for i in earn_idx]
    ev_rows += [{"id": f"AAPL-earnings-{nxt}", "date": str(nxt), "type": "earnings", "ticker": "AAPL",
                 "name": "Apple earnings", "source": "yfinance", "first_seen_at": now},
                {"id": f"MSFT-ex_dividend-{nxt}", "date": str(nxt), "type": "ex_dividend", "ticker": "MSFT",
                 "name": "Microsoft ex-dividend", "source": "yfinance", "first_seen_at": now, "amount": 3.0}]
    jsonl(root / "data" / MARKET / "events" / "2026" / "01" / "2026-01-01.jsonl", ev_rows)
    expiry = nxt + timedelta(days=14)
    jsonl(root / "data" / MARKET / "options" / f"{as_of:%Y}" / f"{as_of:%m}" / f"{as_of}.jsonl",
          [{"id": f"{as_of}-MSFT-{expiry}", "ticker": "MSFT", "collected_at": f"{as_of}T21:00:00+00:00",
            "expiry": str(expiry), "days_to_expiry": 14, "spot": 300, "strike": 300, "call_iv": 0.6,
            "put_iv": 0.6, "atm_iv": 0.6, "straddle": 20, "straddle_pct": 0.067, "source": "yfinance"}])

    # a copy with implied vol switched off, for the shadow value
    import shutil
    root_off, cfg_off = tmp_path / "repo_off", tmp_path / "config_off"
    shutil.copytree(root, root_off)
    shutil.copytree(cfg, cfg_off)
    rc_off = {**rc, "implied_vol": {**ALL_ON["implied_vol"], "enabled": False}}
    (cfg_off / "ranges.yaml").write_text(yaml.safe_dump(rc_off))

    made_at = f"{as_of}T23:00:00+00:00"
    r = run("ranges.py", root, cfg, "--now", made_at)
    assert r.returncode == 0, r.stderr
    rows = ranges_rows(root)
    a1, m1 = rows[f"{as_of}-AAPL-1d"], rows[f"{as_of}-MSFT-1d"]
    feats = {x["ticker"]: x for f in (root / "data" / MARKET / "features").glob("**/*.jsonl")
             for x in map(json.loads, f.read_text().splitlines())}
    beta = {t: min(max(feats[t]["beta_1y"], 0.0), 2.5) for t in ("AAPL", "MSFT")}
    sd = {t: feats[t]["ewma_vol"] / math.sqrt(252) for t in ("AAPL", "MSFT")}
    index_cue = math.log1p(0.01)
    assert 0.8 < beta["AAPL"] < 1.6

    # AAPL 1d: earnings tomorrow sized from the 5 past reactions (independent recomputation)
    c = pd.Series(aapl)
    sig = rl.ewma_sigma(c, rc["ewma_lambda"])
    moves = [(math.log(c[i] / c[i - 1]), float(sig[i - 1]), 1) for i in earn_idx]
    m, k = rl.earnings_multiple(moves, 2.5, 2, 4, 8.0)
    assert k == len(earn_idx) and m > 3.5 and m != rl.earnings_multiple(moves, 3.0, 2, 4, 8.0)[0]
    assert abs(a1["sigma_h"] - sd["AAPL"] * m) < 2e-6                 # h=1: variance sd^2 * m^2
    assert set(a1["inputs"]) == {"earnings_history", "beta_split"}
    assert any(f"x{round(m, 2)} day, {k} past moves" in x for x in a1["notes"])
    # centre = index weight x clipped beta x expected index move (AAPL has no own cue)
    assert abs(a1["center"] - 0.5 * beta["AAPL"] * index_cue) < 2e-6

    # MSFT 1d: implied vol blended into the width, dividend going ex shifts the centre down
    sessions = sum(ev.is_session(xnys, as_of + timedelta(days=d)) for d in range(1, (expiry - as_of).days + 1))
    iv_var = 0.6 ** 2 * (expiry - as_of).days / 365 / sessions
    s_msft = math.sqrt(0.5 * sd["MSFT"] ** 2 + 0.5 * iv_var)
    assert abs(m1["sigma_h"] - s_msft) < 2e-6 and m1["sigma_h"] > 1.5 * sd["MSFT"]
    drift = min(0.5 * beta["MSFT"] * index_cue, 0.5 * m1["sigma_h"])
    assert abs(m1["center"] - (drift + math.log(1 - 3.0 / m1["base_close"]))) < 2e-6
    assert {"implied_vol", "ex_dividend"} <= set(m1["inputs"]) and m1["iv_sigma_h"] == m1["sigma_h"]
    assert a1["iv_sigma_h"] is None                                   # no chain for AAPL

    # implied vol off: EWMA width, and the IV width kept as the shadow value
    r = run("ranges.py", root_off, cfg_off, "--now", made_at)
    assert r.returncode == 0, r.stderr
    m1_off = ranges_rows(root_off)[f"{as_of}-MSFT-1d"]
    assert abs(m1_off["sigma_h"] - sd["MSFT"]) < 2e-6
    assert "implied_vol" not in m1_off["inputs"] and abs(m1_off["iv_sigma_h"] - m1["sigma_h"]) < 2e-6


def test_late_run_guard_drops_late_index_cue_and_options(tmp_path):
    """A run after the first target session's close: the 1d range is not published, and an index
    cue or option snapshot taken after that close is not used (it would carry that session)."""
    root, cfg = setup(tmp_path)
    mfile = cfg / "markets" / f"{MARKET}.yaml"
    mfile.write_text(mfile.read_text() + "\noptions: yfinance\nindex_cue: {symbol: BENCH, beta: 1.0}\n")
    rc = yaml.safe_load((cfg / "ranges.yaml").read_text())
    rc.update(ALL_ON)
    (cfg / "ranges.yaml").write_text(yaml.safe_dump(rc))
    rng = np.random.default_rng(31)
    n = 520
    days = weekdays(date(2024, 6, 3), n)
    br = rng.normal(0.0003, 0.01, n)
    write_bars(root, {"BENCH": list(100 * np.exp(np.cumsum(br))),
                      "AAPL": list(150 * np.exp(np.cumsum(1.2 * br + rng.normal(0, 0.01, n)))),
                      "MSFT": fat_tailed_walk(rng, n, 300, 0.012), "VOLX": [15.0] * n}, days)
    as_of = days[-1]
    xnys = {"market": MARKET, "calendar": "XNYS", "timezone": "America/New_York"}
    first = ev.next_session(xnys, as_of, include=False)
    first_close = ev.session_close_utc(xnys, first)
    late = (first_close + timedelta(minutes=30)).isoformat()      # quoted after the first close
    made_at = (first_close + timedelta(hours=1)).isoformat()      # run after that close too
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    today = datetime.now(timezone.utc).date()
    jsonl(root / "data" / MARKET / "quotes" / f"{today:%Y}" / f"{today:%m}" / f"{today}.jsonl",
          [{"symbol": "BENCH", "yahoo": "BENCH", "ts": late, "price": 101, "prev_close": 100,
            "change_pct": 0.01, "collected_at": now}])
    assert run("features.py", root, cfg).returncode == 0
    assert run("calibrate.py", root, cfg).returncode == 0
    expiry = first + timedelta(days=21)
    jsonl(root / "data" / MARKET / "options" / f"{first:%Y}" / f"{first:%m}" / f"{first}.jsonl",
          [{"id": f"{first}-{t}-{expiry}", "ticker": t, "collected_at": late, "expiry": str(expiry),
            "days_to_expiry": 21, "spot": 300, "strike": 300, "call_iv": 0.6, "put_iv": 0.6, "atm_iv": 0.6,
            "straddle": 20, "straddle_pct": 0.067, "source": "yfinance"} for t in ("AAPL", "MSFT")])

    r = run("ranges.py", root, cfg, "--now", made_at)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["late"] is True
    rows = ranges_rows(root)
    assert not any(x["horizon_days"] == 1 for x in rows.values())      # target session closed
    for t in ("AAPL", "MSFT"):
        x = rows[f"{as_of}-{t}-5d"]
        assert f"index cue ignored: BENCH quoted after {first} close" in x["notes"]
        assert "beta_split" not in x["inputs"] and x["center"] == 0
        assert "implied_vol" not in x["inputs"] and x["iv_sigma_h"] is None
        assert f"late: {first} closed before made_at" in x["notes"]


def test_ranges_config_per_market_override(tmp_path, monkeypatch):
    import common
    (tmp_path / "ranges.yaml").write_text("earnings_vol_multiple: 3.0\nearnings_vol_multiple_by_market: {india: 2.0}\n")
    monkeypatch.setattr(common, "CONFIG", tmp_path)
    assert common.load_ranges_config("india")["earnings_vol_multiple"] == 2.0
    assert common.load_ranges_config("us")["earnings_vol_multiple"] == 3.0
    assert common.load_ranges_config()["earnings_vol_multiple"] == 3.0
    monkeypatch.setattr(common, "CONFIG", Path(__file__).resolve().parents[1] / "config")   # the shipped defaults
    assert common.load_ranges_config("india")["earnings_vol_multiple"] == 2.0
    assert common.load_ranges_config("us")["earnings_vol_multiple"] == 3.0
    # every script loads the settings of the market it runs for (review's replay, calibrate, ...)
    import re
    calls = {f"{f.name}:{m}" for f in sorted((Path(__file__).resolve().parents[1] / "scripts").glob("*.py"))
             if f.name != "common.py" for m in re.findall(r"load_ranges_config\(([^)]*)\)", f.read_text())}
    assert {c.split(":")[0] for c in calls} >= {"backtest.py", "calibrate.py", "ranges.py", "relations.py", "review.py"}
    assert all(c.endswith(':cfg["market"]') for c in calls), calls


def test_switches_per_market_and_horizon():
    rc = {"a": {"enabled": {"us": [1]}}, "b": {"enabled": {"india": True}}, "c": {"enabled": ["us"]},
          "d": {"enabled": True}}
    assert ri.enabled(rc, "a", "us", 1) and not ri.enabled(rc, "a", "us", 5)
    assert ri.enabled(rc, "a", "us") and not ri.enabled(rc, "a", "india", 1)
    assert ri.enabled(rc, "b", "india", 5) and not ri.enabled(rc, "b", "us")
    assert ri.enabled(rc, "c", "us", 5) and not ri.enabled(rc, "c", "india", 1)
    assert ri.enabled(rc, "d", "india", 5) and not ri.enabled(rc, "e", "us", 1)


def test_event_dedupe_reads_every_file(tmp_path, monkeypatch):
    """History ids written 450 run days ago are still seen, so the backfill never repeats them."""
    base = tmp_path / "data" / MARKET
    for i in range(450):
        d = date(2025, 1, 1) + timedelta(days=i)
        jsonl(base / "events" / f"{d:%Y}" / f"{d:%m}" / f"{d}.jsonl",
              [{"id": f"AAPL-ex_dividend-{d}", "date": str(d), "type": "ex_dividend", "ticker": "AAPL",
                "source": "yfinance_history", "amount": 0.25}])
    monkeypatch.setattr(ce, "data_dir", lambda market: tmp_path / "data" / market)
    ids = {r["id"] for r in ce.stored_events(MARKET)}
    assert len(ids) == 450 and "AAPL-ex_dividend-2025-01-01" in ids


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

    # the fixed multiple is per market: only this market's override changes the fixed arm
    def fixed_arm(by_market: dict) -> dict:
        (cfg / "ranges.yaml").write_text(yaml.safe_dump({**rc, "earnings_vol_multiple_by_market": by_market}))
        r2 = run("backtest.py", root, cfg, "--eval-sessions", "300", "--out", str(out_md))
        assert r2.returncode == 0, r2.stderr
        return json.loads(r2.stdout)["inputs"]["1"]["earnings_history"]["off"]
    x3 = s["inputs"]["1"]["earnings_history"]["off"]
    assert fixed_arm({"othermarket": 2.0}) == x3
    assert fixed_arm({MARKET: 2.0})["width80_pct"] < x3["width80_pct"]


# ---------- earnings dates from NSE results filings (collect_events.py) ----------

NSE_FIX = Path(__file__).resolve().parent / "fixtures" / "nse" / "earnings"
XBOM = {"market": "x", "calendar": "XBOM", "timezone": "Asia/Kolkata"}
IST_TZ = "Asia/Kolkata"
INDIA = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "markets" / "india.yaml").read_text())
INFY_DATES = [(date(2023, 10, 12), "after_close"), (date(2024, 1, 11), "after_close"), (date(2024, 4, 19), "during"),
              (date(2024, 7, 18), "after_close"), (date(2024, 10, 17), "after_close"),
              (date(2025, 1, 16), "after_close"), (date(2025, 4, 17), "after_close"),
              (date(2025, 7, 23), "after_close"), (date(2025, 10, 16), "after_close"),
              (date(2026, 1, 14), "after_close"), (date(2026, 4, 23), "after_close"), (date(2026, 7, 23), "after_close")]
MARUTI_DATES = [(date(2025, 4, 25), "during"), (date(2025, 7, 31), "during"), (date(2025, 10, 31), "during"),
                (date(2026, 1, 28), "during"), (date(2026, 4, 28), "during"), (date(2026, 7, 31), "after_close")]


def replay_nse():
    from nse import Nse
    return Nse(replay=NSE_FIX, pause=0)


def ist(s: str) -> datetime:
    return pd.Timestamp(s, tz=IST_TZ).tz_convert("UTC").to_pydatetime()


def test_nse_earnings_from_real_results_filings():
    """Real NSE responses: INFY backfill (Integrated Filing from the March 2025 quarter, the older
    financial-results list before it, both bases), MARUTI incremental (quarters after its newest
    stored date). MARUTI's XBRL is filed after the close but its results announcement comes
    during the session, so the announcement time sets the timing."""
    out, failed, notes = ce.nse_earnings(INDIA, replay_nse(), {"INFY": None, "MARUTI": date(2025, 1, 29)},
                                         date(2023, 10, 1), date(2026, 10, 5))
    assert failed == [] and notes == []
    assert [(d, tm) for d, tm, _ in out["INFY"]] == INFY_DATES
    assert [(d, tm) for d, tm, _ in out["MARUTI"]] == MARUTI_DATES
    assert {p for rows in out.values() for _, _, p in rows} == {0}          # filings beat yfinance
    # a ticker with stored history only takes quarters filed after it
    out, _, _ = ce.nse_earnings(INDIA, replay_nse(), {"INFY": date(2026, 1, 14)}, date(2023, 10, 1), date(2026, 10, 5))
    assert [(d, tm) for d, tm, _ in out["INFY"]] == INFY_DATES[-2:]
    # 2019 in the window: the March 2019 quarter was first filed in September (late XBRL), not used
    out, _, notes = ce.nse_earnings(INDIA, replay_nse(), {"INFY": None}, date(2019, 1, 1), date(2026, 10, 5))
    assert [(d, tm) for d, tm, _ in out["INFY"]] == [(date(2019, 10, 11), None)] + INFY_DATES   # calendar from 2020
    assert notes == ["INFY: 1 quarter(s) first filed after the SEBI deadline, not used"]
    # a symbol without responses is a failure for that ticker only
    out, failed, _ = ce.nse_earnings(INDIA, replay_nse(), {"HDFCBANK": None, "INFY": date(2026, 1, 14)},
                                     date(2023, 10, 1), date(2026, 10, 5))
    assert [f["source"] for f in failed] == ["nse_earnings:HDFCBANK"] and list(out) == ["INFY"]


def test_nse_reports_release_window_and_deadline():
    filings = [(date(2026, 6, 30), ist("2026-07-23 18:00")), (date(2026, 6, 30), ist("2026-07-23 17:40")),
               (date(2026, 3, 31), ist("2026-06-15 10:00")),                         # 76 days: late XBRL
               (date(2025, 12, 31), ist("2026-01-14 08:00"))]                        # before the open
    releases = [ist("2026-07-23 13:30"),          # results PDF during the session, 4h10 before the XBRL
                ist("2026-07-20 11:00")]          # board outcome 3 days earlier: another meeting
    rows, late = ce.nse_reports(XBOM, filings, releases)
    assert late == 1
    assert rows == [(date(2026, 1, 14), "before_open", 0), (date(2026, 7, 23), "during", 0)]
    rows, _ = ce.nse_reports(XBOM, filings, [ist("2026-07-21 23:00")])   # outside the 36h window
    assert rows[-1] == (date(2026, 7, 23), "after_close", 0)
    rows, late = ce.nse_reports(XBOM, filings, releases, after=date(2026, 1, 14))
    assert rows == [(date(2026, 7, 23), "during", 0)] and late == 1
    assert ce.max_filing_lag(date(2026, 3, 31)) == 63 and ce.max_filing_lag(date(2026, 6, 30)) == 48


def test_nse_due_polls_only_what_needs_it():
    def row(t, d, src):
        return {"id": f"{t}-earnings-{d}", "ticker": t, "type": "earnings", "date": d, "source": src}
    stored = [row("A", "2026-07-20", "nse_history"), row("A", "2026-10-20", "yfinance"),      # next one ahead
              row("B", "2026-07-01", "nse_history"), row("B", "2026-10-01", "yfinance"),      # passed
              row("C", "2026-06-20", "nse_history"),                                          # 107 days old
              row("D", "2026-07-15", "yfinance_history"),                                     # no NSE yet
              row("F", "2026-07-20", "nse_history"), row("F", "2026-09-20", "yfinance_history"),
              row("G", "2026-07-20", "nse_history"), row("G", "2026-07-22", "yfinance"),      # same report
              {"id": "A-ex_dividend-2026-10-02", "ticker": "A", "type": "ex_dividend", "date": "2026-10-02",
               "source": "yfinance"}]
    due = ce.nse_due(stored, ["A", "B", "C", "D", "E", "F", "G"], date(2026, 10, 5))
    assert due == {"B": date(2026, 7, 1), "C": date(2026, 6, 20), "D": None, "E": None}


def test_between_quarters():
    nse = [date(2024, 5, 22), date(2024, 8, 1), date(2025, 1, 10), date(2025, 4, 20)]
    assert ce.between_quarters(date(2024, 7, 11), nse)          # 71 days apart: no quarter missing
    assert ce.between_quarters(date(2024, 8, 1), nse)           # the report itself
    assert not ce.between_quarters(date(2024, 10, 30), nse)     # 162-day gap: a quarter NSE lacks
    assert not ce.between_quarters(date(2025, 5, 1), nse) and not ce.between_quarters(date(2024, 1, 1), nse)
    assert not ce.between_quarters(date(2024, 7, 11), [])


class FakeTicker:
    def __init__(self, data: dict):
        self.data = data

    @property
    def calendar(self):
        return self.data.get("calendar", {})

    @property
    def dividends(self):
        return pd.Series(dtype=float)

    def get_earnings_dates(self, limit=40):
        idx = pd.DatetimeIndex([pd.Timestamp(t, tz=IST_TZ) for t in self.data.get("earnings", [])])
        return pd.DataFrame({"Event Type": ["Earnings"] * len(idx)}, index=idx)


def run_events_main(monkeypatch, capsys, tmp_path, cfg: dict, yf_data: dict, today: date) -> dict:
    """collect_events.main() in-process: fake yfinance, NSE replayed from NSE_FIX, data under tmp_path."""
    import types

    import common
    fake = types.ModuleType("yfinance")
    fake.Ticker = lambda sym: FakeTicker(yf_data.get(sym, {}))
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(ce, "require_market", lambda args: cfg)
    monkeypatch.setattr(ce, "data_dir", lambda m: tmp_path / "data" / m)
    monkeypatch.setattr(common, "data_dir", lambda m: tmp_path / "data" / m)
    monkeypatch.setattr(ce, "utc_today", lambda: today)
    monkeypatch.setattr(ce, "nse_client", lambda c: replay_nse())
    monkeypatch.setattr(sys, "argv", ["collect_events.py"])
    assert ce.main() == 0
    return json.loads(capsys.readouterr().out)


def test_collect_events_nse_backfill_is_append_only_and_idempotent(tmp_path, monkeypatch, capsys):
    cfg = {"market": "testnse", "name": "Test NSE", "calendar": "XBOM", "timezone": IST_TZ,
           "relations": {"source": "nse", "pause_seconds": 0},
           "tickers": {"INFY": {"yahoo": "INFY.NS", "name": "Infosys"},
                       "MARUTI": {"yahoo": "MARUTI.NS", "name": "Maruti Suzuki"},
                       "HDFCBANK": {"yahoo": "HDFCBANK.NS", "name": "HDFC Bank"}}}
    today = date(2026, 10, 5)
    base = tmp_path / "data" / "testnse" / "events"
    old = base / "2025" / "02" / "2025-02-01.jsonl"
    jsonl(old, [{"id": "MARUTI-earnings-2025-01-29", "date": "2025-01-29", "type": "earnings", "ticker": "MARUTI",
                 "name": "Maruti Suzuki earnings", "source": "nse_history", "first_seen_at": "2025-02-01T00:00:00+00:00",
                 "amount": None, "timing": "during"}])
    before = old.read_bytes()
    yf_data = {"INFY.NS": {"calendar": {"Earnings Date": [date(2026, 10, 23)]},
                           "earnings": ["2025-07-24 12:00",            # same report as NSE 2025-07-23: NSE wins
                                        "2024-08-30 12:00",            # between two NSE quarters: not a release
                                        "2026-09-01 12:00"]},          # after NSE's last date: kept
               "HDFCBANK.NS": {"earnings": ["2026-07-18 13:00"]}}      # NSE fails for HDFCBANK: yfinance row kept
    s = run_events_main(monkeypatch, capsys, tmp_path, cfg, yf_data, today)
    assert (s["nse_polled"], s["nse_backfill"], s["nse_tickers"]) == (3, 2, 2)
    assert [f["source"] for f in s["nse_failed"]] == ["nse_earnings:HDFCBANK"]
    assert s["new_history"]["earnings"] == 12 + 6 + 2 and s["new_events"] == 1
    new = base / "2026" / "10" / "2026-10-05.jsonl"
    rows = [json.loads(x) for x in new.read_text().splitlines()]
    hist = {(r["ticker"], r["date"], r["timing"], r["source"]) for r in rows if r["source"].endswith("_history")}
    assert hist == ({("INFY", str(d), tm, "nse_history") for d, tm in INFY_DATES}
                    | {("MARUTI", str(d), tm, "nse_history") for d, tm in MARUTI_DATES}
                    | {("INFY", "2026-09-01", "during", "yfinance_history"),
                       ("HDFCBANK", "2026-07-18", "before_open", "yfinance_history")})
    assert old.read_bytes() == before
    # second run: nothing new; only the failed backfill (HDFCBANK, no NSE rows yet) is polled again
    s = run_events_main(monkeypatch, capsys, tmp_path, cfg, yf_data, today)
    assert (s["nse_polled"], s["nse_backfill"], s["new_history"]["earnings"], s["new_events"]) == (1, 1, 0, 0)
    assert len(new.read_text().splitlines()) == len(rows)


def test_collect_events_summary_lists_sec_failures(tmp_path, monkeypatch, capsys):
    """Issue 11: a ticker whose SEC submissions request fails is listed in the JSON summary."""
    fx = tmp_path / "sec"
    fx.mkdir()
    sub = {"name": "Apple", "filings": {"recent": {"form": ["8-K"], "items": ["2.02,9.01"],
                                                   "acceptanceDateTime": ["2026-07-30T20:31:00.000Z"]}}}
    (fx / "sub.json").write_text(json.dumps(sub))
    (fx / "urls.json").write_text(json.dumps({
        "https://www.sec.gov/files/company_tickers.json": str(Path(__file__).resolve().parent / "fixtures" / "sec"
                                                              / "company_tickers.json"),
        "https://data.sec.gov/submissions/CIK0000320193.json": "sub.json"}))   # NVDA: no fixture
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fx))
    monkeypatch.setenv("SEC_USER_AGENT", "market-brief tests test@example.com")
    cfg = {"market": "testsecev", "name": "Test", "calendar": "XNYS", "timezone": "America/New_York",
           "filings": "sec", "tickers": {"AAPL": {"yahoo": "AAPL", "name": "Apple"},
                                         "NVDA": {"yahoo": "NVDA", "name": "NVIDIA"}}}
    s = run_events_main(monkeypatch, capsys, tmp_path, cfg, {}, date(2026, 10, 5))
    assert s["sec_tickers"] == 1 and s["sec_error"] is None
    assert [(f["ticker"], f["cik"]) for f in s["sec_failed"]] == [("NVDA", 1045810)]
    assert "nse_polled" not in s and s["new_history"]["earnings"] == 1
