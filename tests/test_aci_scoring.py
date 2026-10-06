"""Adaptive Conformal Inference (marketbrief/analytics/adaptive_conformal.py) and proper scores (marketbrief/analytics/scoring.py):
the ACI update against two references, no look-ahead (live and replay), ACI off reproduces the
current ranges exactly, and Brier / log loss / reliability / quantile score on synthetic data.
Run: pytest -q"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.analytics import adaptive_conformal as aci  # noqa: E402
from marketbrief.core.market_config import load_ranges_config  # noqa: E402
from marketbrief.analytics import range_math as rl  # noqa: E402
from marketbrief.analytics import scoring  # noqa: E402
from test_pipeline import MARKET, fat_tailed_walk, run, setup, weekdays, write_bars  # noqa: E402
from test_replay import D_POS, build, dump, fixture  # noqa: E402

from datetime import date  # noqa: E402


# ---------- ACI update math ----------

def reference_aci(errs, alpha, lr):
    """aangelopoulos/conformal-time-series core/methods.py `aci`, transcribed: alphat += lr * (alpha - err)
    after each step, starting at alpha (no clipping)."""
    alphat, out = alpha, []
    for e in errs:
        alphat += lr * (alpha - e)
        out.append(alphat)
    return out


def test_aci_update_matches_reference_formula():
    rng = np.random.default_rng(3)
    errs = (rng.random(500) < np.where(np.arange(500) < 250, 0.35, 0.05)).astype(float)
    for target, gamma in ((0.2, 0.005), (0.5, 0.05), (0.1, 0.01)):
        mine = aci.aci_path(errs, target, gamma)[1:]
        assert np.allclose(mine, reference_aci(errs, target, gamma), atol=1e-12)
    # hand-checked steps: miss -> down by gamma*(1-target); hit -> up by gamma*target
    assert aci.aci_step(0.2, 0.2, 1.0, 0.01) == pytest.approx(0.192)
    assert aci.aci_step(0.2, 0.2, 0.0, 0.01) == pytest.approx(0.202)
    assert aci.aci_step(0.2, 0.2, 0.25, 0.01) == pytest.approx(0.1995)    # share of misses in a step
    assert aci.aci_step(0.06, 0.2, 1.0, 0.1, lo=0.05) == 0.05               # clamped


def test_aci_update_matches_mapie():
    """MAPIE's TimeSeriesRegressor.adapt_conformal_inference (BSD-3; test reference only, not a
    runtime dependency): the same alpha path on a synthetic series with a variance shift."""
    pytest.importorskip("mapie")
    from mapie.regression import TimeSeriesRegressor
    from sklearn.linear_model import LinearRegression
    rng = np.random.default_rng(0)
    n = 300
    X = rng.normal(size=(n, 1))
    y = 2 * X[:, 0] + rng.normal(size=n) * np.where(np.arange(n) > 200, 3, 1)
    m = TimeSeriesRegressor(LinearRegression().fit(X[:100], y[:100]), method="aci", cv="prefit")
    m.fit(X[100:150], y[100:150])
    gamma, alpha0 = 0.05, 0.2
    errs, theirs = [], []
    for i in range(150, n):
        _, b = m.predict(X[i:i + 1], confidence_level=1 - alpha0, allow_infinite_bounds=True)
        errs.append(float(not (b[0, 0, 0] < y[i] < b[0, 1, 0])))
        m.adapt_conformal_inference(X[i:i + 1], y[i:i + 1], gamma=gamma, confidence_level=1 - alpha0)
        theirs.append(float(m.current_alpha[alpha0]))
    assert 10 < sum(errs) < 140                                  # both hits and misses happen
    mine = aci.aci_path(errs, alpha0, gamma, 0.0, 1.0)[1:]       # MAPIE clips alpha to [0, 1]
    assert np.allclose(mine, theirs, atol=1e-12)


def test_tracker_steps_per_target_date_min_history_and_nesting():
    rc = {"aci": {"enabled": True, "gamma": 0.1, "max_shift": 0.15, "min_history": 3, "by_regime": False}}
    t = aci.Tracker(rc)
    df = pd.DataFrame({"horizon_days": [1] * 6, "target_date": ["2026-01-02"] * 2 + ["2026-01-05"] * 2 + ["2026-01-06"] * 2,
                       "hit50": [True, False, False, False, True, True], "hit80": [True, True, False, True, True, True]})
    t.feed(df.iloc[::-1])                                         # order of rows does not matter
    exp50 = aci.aci_path([0.5, 1.0, 0.0], 0.5, 0.1, *aci.clamps(0.5, 0.15))
    exp80 = aci.aci_path([0.0, 0.5, 0.0], 0.2, 0.1, *aci.clamps(0.2, 0.15))
    assert t.alpha[(1, "50", "all")] == pytest.approx(exp50[-1]) and t.steps[(1, "50", "all")] == 3
    assert t.alpha[(1, "80", "all")] == pytest.approx(exp80[-1])
    lv = t.levels(1, "all")
    assert lv["q10"] == pytest.approx(min(exp80[-1], exp50[-1]) / 2) and lv["q75"] == pytest.approx(1 - exp50[-1] / 2)
    assert lv["q10"] <= lv["q25"] < lv["q75"] <= lv["q90"]
    t2 = aci.Tracker({"aci": {**rc["aci"], "min_history": 4}})
    t2.feed(df)
    assert t2.levels(1, "all") == {"q10": 0.1, "q25": 0.25, "q75": 0.75, "q90": 0.9}   # too little history


# ---------- no look-ahead ----------

def live_con(rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE range_record (id VARCHAR, horizon_days INTEGER, target_date DATE, regime VARCHAR, "
                "hit50 BOOLEAN, hit80 BOOLEAN)")
    con.execute("CREATE TABLE range_outcomes (range_id VARCHAR, scored_at TIMESTAMPTZ)")
    for r in rows:
        con.execute("INSERT INTO range_record VALUES (?, ?, ?, ?, ?, ?)", [r[0], 1, r[1], "CALM", r[2], r[3]])
        con.execute("INSERT INTO range_outcomes VALUES (?, ?)", [r[0], r[4]])
    return con


def test_live_alpha_ignores_outcomes_scored_after_now():
    rc = {"aci": {"gamma": 0.05, "min_history": 1}}
    rng = np.random.default_rng(5)
    days = pd.bdate_range("2026-01-01", periods=60)
    rows = [(f"r{i}", d.date(), bool(rng.random() < .5), bool(rng.random() < .8), f"{d.date()}T22:00:00+00:00")
            for i, d in enumerate(days)]
    now = f"{days[39].date()}T23:00:00+00:00"
    base = aci.live_tracker(live_con(rows), rc, now).snapshot()
    flipped = [r if r[4] <= now else (r[0], r[1], not r[2], not r[3], r[4]) for r in rows]
    assert aci.live_tracker(live_con(flipped), rc, now).snapshot() == base
    assert base[0]["steps"] == 40
    # flipping an outcome scored before now does change alpha
    early = [(r[0], r[1], not r[2], not r[3], r[4]) if i == 5 else r for i, r in enumerate(rows)]
    assert aci.live_tracker(live_con(early), rc, now).snapshot() != base


def aci_config(cfg: Path) -> None:
    p = cfg / "ranges.yaml"
    text = p.read_text()
    assert "aci:\n  enabled: false" in text
    p.write_text(text.replace("aci:\n  enabled: false", "aci:\n  enabled: true")
                 .replace("gamma: 0.01 ", "gamma: 0.05 ").replace("min_history: 20", "min_history: 5"))


def test_replay_aci_has_no_lookahead(tmp_path):
    days, series, events, d, _ = fixture(tmp_path)
    base_root, base_cfg = build(tmp_path, "base", days, series, events)
    aci_config(base_cfg)
    rng = np.random.default_rng(99)
    shaken = {k: [x if i <= D_POS else x * float(np.exp(rng.normal(0, 0.05))) for i, x in enumerate(v)]
              for k, v in series.items()}
    pert_root, pert_cfg = build(tmp_path, "pert", days, shaken, events)
    aci_config(pert_cfg)
    a = {(x["ticker"], int(x["h"]), x["date"]): x for x in dump(base_root, base_cfg)}
    b = {(x["ticker"], int(x["h"]), x["date"]): x for x in dump(pert_root, pert_cfg)}
    early = [k for k in a if k[2] <= str(d)]
    assert len(early) > 400
    for k in early:   # alpha and the bands at or before d use only outcomes known by d
        for f in ("alpha50", "alpha80", "lo50", "hi50", "lo80", "hi80"):
            assert a[k][f] == b[k][f], (k, f)
    assert any(a[k]["alpha80"] != 0.2 for k in early)           # ACI was active
    later = [k for k in a if k[2] > str(days[D_POS + 6])]
    assert any(a[k]["alpha80"] != b[k]["alpha80"] for k in later)   # and does react to later outcomes


# ---------- ACI off reproduces today's ranges ----------

def strip_aci_block(cfg: Path) -> None:
    """The config as it was before ACI existed (no `aci:` block at all)."""
    p = cfg / "ranges.yaml"
    lines = p.read_text().splitlines(keepends=True)
    i = next(k for k, x in enumerate(lines) if x.startswith("aci:"))
    j = i + 1
    while j < len(lines) and lines[j].startswith("  "):
        j += 1
    p.write_text("".join(lines[:i] + lines[j:]))


def test_aci_off_reproduces_ranges_byte_for_byte(tmp_path):
    rng = np.random.default_rng(11)
    days = weekdays(date(2024, 6, 3), 400)
    series = {"BENCH": fat_tailed_walk(rng, 400, 100, 0.01), "AAPL": fat_tailed_walk(rng, 400, 150, 0.015),
              "MSFT": fat_tailed_walk(rng, 400, 300, 0.012), "VOLX": [15.0] * 400}
    out = {}
    for name in ("off", "absent"):
        root, cfg = setup(tmp_path / name)
        if name == "absent":
            strip_aci_block(cfg)
            assert "\naci:" not in (cfg / "ranges.yaml").read_text()
        write_bars(root, series, days)
        assert run("features.py", root, cfg).returncode == 0
        env_now = f"{days[-1]}T23:00:00+00:00"
        import os
        os.environ["MB_NOW"] = env_now
        try:
            assert run("calibrate.py", root, cfg).returncode == 0
            r = run("ranges.py", root, cfg, "--now", env_now)
        finally:
            del os.environ["MB_NOW"]
        assert r.returncode == 0, r.stderr
        files = {}
        for kind in ("calibration", "ranges"):
            for f in sorted((root / "data" / MARKET / kind).glob("**/*.jsonl")):
                files[f"{kind}/{f.name}"] = f.read_bytes()
        out[name] = files
    assert out["off"].keys() == out["absent"].keys() and len(out["off"]) == 2
    for k in out["off"]:
        assert out["off"][k] == out["absent"][k], k
    cal = [json.loads(x) for x in out["off"][next(k for k in out["off"] if k.startswith("calibration"))].splitlines()]
    assert all(not any(k.startswith("aci_") for k in c) and c["source"] == "pool" for c in cal)


def test_replay_aci_off_rows_unchanged(tmp_path):
    days, series, events, _, _ = fixture(tmp_path)
    root, cfg = build(tmp_path, "on", days, series, events)
    rows_off = dump(root, cfg)
    strip_aci_block(cfg)
    assert dump(root, cfg) == rows_off
    assert all(r["alpha50"] == 0.5 and r["alpha80"] == pytest.approx(0.2) for r in rows_off)


# ---------- proper scores ----------

def test_brier_log_loss_reliability_exact():
    p = [0.5, 0.6, 0.6, 0.7, 0.8, 0.9, 0.9, 0.65]
    y = [1, 1, 0, 1, 0, 1, 1, 0]
    # Brier: (.25 + .16 + .36 + .09 + .64 + .01 + .01 + .4225) / 8 = 1.9425 / 8
    assert scoring.brier(p, y) == pytest.approx(1.9425 / 8)
    ll = -(math.log(.5) + math.log(.6) + math.log(.4) + math.log(.7) + math.log(.2) + 2 * math.log(.9) + math.log(.35)) / 8
    assert scoring.log_loss(p, y) == pytest.approx(ll)
    assert scoring.brier([0.5] * 4, [1, 0, 1, 1]) == 0.25 and scoring.log_loss([0.5], [0]) == pytest.approx(math.log(2))
    rel = scoring.reliability(p, y)
    assert [r["n"] for r in rel] == [1, 3, 1, 3]          # [.5,.6) [.6,.7) [.7,.8) [.8,.9]
    assert rel[1]["hit_rate"] == pytest.approx(1 / 3) and rel[1]["mean_conf"] == pytest.approx((0.6 + 0.6 + 0.65) / 3)
    assert rel[3]["hit_rate"] == pytest.approx(2 / 3) and rel[3]["mean_conf"] == pytest.approx(2.6 / 3)
    lo, hi = scoring.wilson(2, 3)
    # Wilson 95% for 2/3: centre (2/3 + z^2/6) / (1 + z^2/3), half z sqrt(2/27 + z^2/36) / (1 + z^2/3)
    z = 1.96
    den = 1 + z * z / 3
    assert rel[3]["wilson_lo"] == pytest.approx(lo) and lo == pytest.approx((2 / 3 + z * z / 6 - z * math.sqrt(2 / 27 + z * z / 36)) / den)
    assert hi == pytest.approx((2 / 3 + z * z / 6 + z * math.sqrt(2 / 27 + z * z / 36)) / den)
    s = scoring.call_scores(pd.DataFrame({"confidence": p, "hit": y}))
    assert s["n"] == 8 and s["brier_skill"] == pytest.approx(1 - (1.9425 / 8) / 0.25, abs=1e-4)
    assert scoring.reliability([], [])[0]["n"] == 0 and scoring.brier([], []) is None


def test_quantile_score_and_interval_score_identity():
    assert scoring.pinball(10.0, 0.9, 12.0) == pytest.approx(1.8)
    assert scoring.pinball(10.0, 0.1, 12.0) == pytest.approx(0.2)
    assert scoring.pinball(10.0, 0.1, 8.0) == pytest.approx(1.8)
    rng = np.random.default_rng(2)
    for _ in range(50):
        lo80, lo50, hi50, hi80 = np.sort(rng.normal(100, 3, 4))
        y, base = float(rng.normal(100, 4)), 100.0
        r = scoring.range_scores_row(lo50, hi50, lo80, hi80, y, base)
        is80, is50 = rl.interval_score(lo80, hi80, y, 0.8), rl.interval_score(lo50, hi50, y, 0.5)
        assert r["qs_pct"] == pytest.approx((0.1 * is80 + 0.25 * is50) / 4)
        assert r["is80_pct"] == pytest.approx(is80) and r["is50_pct"] == pytest.approx(is50)
    df = pd.DataFrame({"lo50": [99.0], "hi50": [101.0], "lo80": [98.0], "hi80": [102.0], "actual_close": [103.0],
                       "base_close": [100.0], "hit50": [False], "hit80": [False]})
    s = scoring.range_scores(df)
    # IS80 = 4 + (2/0.2) * 1 = 14; IS50 = 2 + (2/0.5) * 2 = 10; QS = (1.4 + 2.5) / 4
    assert s["is80_pct"] == 14 and s["is50_pct"] == 10 and s["qs_pct"] == pytest.approx(0.975)


# ---------- calibrate.py with ACI on ----------

def test_calibrate_uses_aci_levels_from_outcomes_scored_by_now():
    from marketbrief.analytics import calibration as calibrate
    rng = np.random.default_rng(4)
    idx = pd.bdate_range("2024-01-01", periods=400)
    bars = {t: pd.DataFrame({"close": fat_tailed_walk(rng, 400, 100, 0.01)}, index=idx) for t in ("BENCH", "A")}
    cfg = {"market": "testmkt", "symbols": {"BENCH": {"role": "benchmark"}}, "tickers": {"A": {}}}
    rc = {**load_ranges_config("us"), "horizons": [1]}
    rc["aci"] = {**rc["aci"], "enabled": True, "gamma": 0.05, "min_history": 3, "by_regime": False}
    con = duckdb.connect()
    con.execute("CREATE TABLE range_record (id VARCHAR, horizon_days INTEGER, as_of_date DATE, target_date DATE, "
                "regime VARCHAR, hit50 BOOLEAN, hit80 BOOLEAN, z DOUBLE)")
    con.execute("CREATE TABLE range_outcomes (range_id VARCHAR, scored_at TIMESTAMPTZ)")
    con.execute("CREATE TABLE regime_latest (as_of_date DATE, regime VARCHAR)")
    now = f"{idx[-1].date()}T23:00:00+00:00"
    for i, d in enumerate(idx[-11:-1]):   # ten scored dates, every range missed both bands
        con.execute("INSERT INTO range_record VALUES (?, 1, ?, ?, 'CALM', false, false, NULL)", [f"r{i}", d.date(), d.date()])
        con.execute("INSERT INTO range_outcomes VALUES (?, ?)", [f"r{i}", f"{d.date()}T22:00:00+00:00"])
    con.execute("INSERT INTO range_record VALUES ('late', 1, ?, ?, 'CALM', true, true, NULL)", [idx[-1].date(), idx[-1].date()])
    con.execute("INSERT INTO range_outcomes VALUES ('late', ?)", [f"{idx[-1].date()}T23:30:00+00:00"])   # after now
    [row] = calibrate.compute(cfg, rc, con, bars, now)
    a80 = aci.aci_path([1.0] * 10, 0.2, 0.05, *aci.clamps(0.2, 0.15))[-1]
    a50 = aci.aci_path([1.0] * 10, 0.5, 0.05, *aci.clamps(0.5, 0.15))[-1]
    assert row["aci_steps"] == 10 and row["source"] == "pool+aci"
    assert row["aci_alpha80"] == pytest.approx(a80) and row["aci_alpha50"] == pytest.approx(a50)
    rc_off = {**rc, "aci": {**rc["aci"], "enabled": False}}
    [off] = calibrate.compute(cfg, rc_off, con, bars, now)
    assert row["q10"] < off["q10"] and row["q90"] > off["q90"] and "aci_alpha80" not in off   # misses widen


# ---------- weekly review: ACI proposal from the replay ----------

def test_review_proposes_aci_only_when_score_and_coverage_improve():
    from marketbrief.constants import review
    from marketbrief.pipeline.review import aci_review

    def grp(c50, c80, s50, s80):
        return {"n": 1000, "cover50": c50, "cover80": c80, "score50": s50, "score80": s80}
    cur = {k: aci.DEFAULTS[k] for k in review.ACI_SETTING_KEYS}
    good = {"id": "x-aci", "settings": dict(cur),
            "comparison": {h: {"overall": {"before": grp(.56, .855, 11.6, 17.3),
                                           "after": grp(.51, .81, 11.5, 16.9)}} for h in ("1", "5")}}
    p = aci_review.aci_proposal({"aci": {"enabled": False}}, good)
    assert p["changes"] == [{"param": "aci.enabled", "current": False, "proposed": True}] and p["n"] == 2000
    assert p["rel_score"] == pytest.approx(16.9 / 17.3 - 1, abs=1e-4)
    # no held-out check: provisional, labelled in-sample
    assert p["provisional"] and p["evidence"] == "in-sample" and "PROVISIONAL" in p["variant"]
    assert "in-sample: settings tuned on this replay" in p["source"]
    assert set(p) >= {"cover80_before", "cover80_after"} and "cover80_now" not in p
    # held-out test passes with the config's settings selected on the tuning dates: not provisional
    test = {h: {"overall": {"before": grp(.55, .85, 11.0, 17.0), "after": grp(.51, .81, 10.9, 16.7)}} for h in ("1", "5")}
    ho = {"tune_end": "2024-12-31", "selected": dict(cur), "selected_is_config": True, "test_selected": test}
    p = aci_review.aci_proposal({}, {**good, "held_out": ho})
    assert not p["provisional"] and p["evidence"] == "out-of-sample" and "after 2024-12-31" in p["source"]
    assert p["rel_score"] == pytest.approx(16.7 / 17.0 - 1, abs=1e-4)
    # tuning picked other settings, or the held-out dates fail: back to provisional
    p = aci_review.aci_proposal({}, {**good, "held_out": {**ho, "selected_is_config": False}})
    assert p["provisional"] and "picked other settings" in p["source"]
    bad = {h: {"overall": {"before": grp(.55, .85, 11.0, 17.0), "after": grp(.51, .81, 10.9, 17.1)}} for h in ("1", "5")}
    p = aci_review.aci_proposal({}, {**good, "held_out": {**ho, "test_selected": bad}})
    assert p["provisional"] and "do not pass" in p["source"]
    # a replay run with other ACI settings is never evidence
    assert aci_review.aci_proposal({}, {**good, "settings": {**cur, "gamma": 0.02}}) is None
    assert aci_review.aci_proposal({"aci": {"enabled": True}}, good) is None            # already on
    assert aci_review.aci_proposal({}, None) is None                                     # no replay
    worse = {**good, "comparison": {**good["comparison"], "5": {"overall": {
        "before": grp(.56, .855, 11.6, 17.3), "after": grp(.51, .81, 11.5, 17.4)}}}}
    assert aci_review.aci_proposal({}, worse) is None                                    # 5d score worse
    over = {**good, "comparison": {**good["comparison"], "1": {"overall": {
        "before": grp(.53, .83, 4.9, 7.3), "after": grp(.40, .70, 4.8, 7.2)}}}}
    assert aci_review.aci_proposal({}, over) is None                                     # coverage further from target


HELD_OUT = """
import json, sys, datetime
from marketbrief.replay.rule_replay import aci_compare
from marketbrief.replay.rule_replay import inputs
from marketbrief.replay.rule_replay import range_rows
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market, load_ranges_config
cfg = load_market('testmkt'); rc = load_ranges_config('testmkt')
tune_end = datetime.date.fromisoformat(sys.argv[1])
ho = aci_compare.held_out(cfg, aci_compare.aci_rc(rc), connect('testmkt'), tune_end)
bars, extra = inputs.load_inputs(cfg, rc, connect('testmkt'))
res, _ = range_rows.replay_rows(cfg, rc, bars, extra)
n_test = {str(h): int(((g['date'] > tune_end) & g['actual'].notna()).sum()) for h, g in res.items()}
c80 = {str(h): float(g.loc[(g['date'] > tune_end) & g['actual'].notna(), 'hit80'].astype(float).mean())
       for h, g in res.items()}
print(json.dumps({'ho': ho, 'n_test': n_test, 'fixed_c80': c80}, default=str))
"""


def test_replay_held_out_selects_on_tuning_dates_and_reports_test_dates(tmp_path):
    from test_replay import py
    days, series, events, _, _ = fixture(tmp_path)
    root, cfg = build(tmp_path, "ho", days, series, events)
    tune_end = days[200]
    r = py(HELD_OUT, root, cfg, str(tune_end))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    ho = out["ho"]
    assert len(ho["grid"]) == 8 and ho["tune_end"] == str(tune_end)
    best = min(ho["grid"], key=lambda v: v["tune_rel_score80"])
    assert (ho["selected"]["gamma"], ho["selected"]["by_regime"]) == (best["gamma"], best["by_regime"])
    assert ho["selected_is_config"] == (best["gamma"] == 0.01 and best["by_regime"] is True)
    for h in ("1", "5"):   # the test comparison holds exactly the scored rows after tune_end
        assert ho["test_selected"][h]["overall"]["before"]["n"] == out["n_test"][h]
        assert ho["test_config"][h]["overall"]["before"]["n"] == out["n_test"][h]
        # "before" is the fixed bands (ACI off), even though held_out gets the ACI-on settings
        assert ho["test_config"][h]["overall"]["before"]["cover80"] == pytest.approx(out["fixed_c80"][h], abs=1e-4)
    assert any(ho["test_config"][h]["overall"]["before"] != ho["test_config"][h]["overall"]["after"] for h in ("1", "5"))


def test_review_skips_aci_replays_with_other_settings_and_ids_name_settings():
    from marketbrief.replay.rule_replay import aci_compare
    from marketbrief.pipeline.review import aci_review
    a = aci.settings({})
    assert aci_compare.aci_tag(a) == "-aci-g0.01-regime-s0.15-m20"
    tag = aci_compare.aci_tag({**a, "gamma": 0.002, "by_regime": False}, date(2024, 12, 31))
    assert tag == "-aci-g0.002-all-s0.15-m20-t2024-12-31"
    cmp = {h: {"overall": {"before": {"n": 10, "cover50": .56, "cover80": .855, "score50": 11.6, "score80": 17.3},
                           "after": {"n": 10, "cover50": .51, "cover80": .81, "score50": 11.5, "score80": 16.9}}}
           for h in ("1", "5")}
    con = duckdb.connect()
    con.execute("CREATE TABLE replays (id VARCHAR, end_date DATE, computed_at TIMESTAMPTZ, settings JSON, detail JSON)")

    def add(rid, at, settings):
        con.execute("INSERT INTO replays VALUES (?, '2026-10-05', ?, ?, ?)",
                    [rid, at, json.dumps({"aci": settings}), json.dumps({"aci_comparison": cmp})])
    add("w" + aci_compare.aci_tag({**a, "gamma": 0.02}), "2026-10-06T02:00:00+00:00",
        {**a, "gamma": 0.02, "enabled": True})
    rep = aci_review.latest_aci_replay(con, date(2026, 10, 11), {})
    assert rep["comparison"] is None and "none with the config/ranges.yaml ACI settings" in rep["note"]
    assert aci_review.aci_proposal({}, rep) is None
    add("w" + aci_compare.aci_tag(a), "2026-10-06T01:00:00+00:00", {**a, "enabled": True})   # older, matching
    rep = aci_review.latest_aci_replay(con, date(2026, 10, 11), {})
    assert rep["id"].endswith("-aci-g0.01-regime-s0.15-m20") and "1 newer ACI replay(s)" in rep["note"]
    assert aci_review.aci_proposal({}, rep)["provisional"]
    # the config changes gamma: the stored g0.01 replay no longer counts
    rc = {"aci": {"gamma": 0.005}}
    rep = aci_review.latest_aci_replay(con, date(2026, 10, 11), rc)
    assert rep["comparison"] is None and aci_review.aci_proposal(rc, rep) is None
