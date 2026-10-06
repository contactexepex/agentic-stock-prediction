"""Weekly review (scripts/review.py) on synthetic outcome data: unit tests for the replay and
the gates, and an end-to-end run on a throwaway market with stored ranges, calls and bars.
Run: pytest -q tests"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rangelib as rl  # noqa: E402
import report  # noqa: E402
import review  # noqa: E402
from marketbrief.utils.event_dates import major_event_between  # noqa: E402
import test_pipeline as tp  # noqa: E402  (helpers only; imported as a module so its tests are not re-collected)

REPO = Path(__file__).resolve().parents[1]
RC = yaml.safe_load((REPO / "config" / "ranges.yaml").read_text())


def make_range(rc: dict, ticker: str, as_of, target, h: int, base: float, sd: float, *, regime="CALM",
               major=False, earnings=False, cue=None, extra_shift=0.0, direction=None, confidence=None,
               widen=0.0, naive_sd=None) -> dict:
    """A published range built the way ranges.py builds it (same notes, cap and rounding)."""
    sigma_h, notes = rl.horizon_sigma(sd, h, earnings, rc, regime, major)
    center = 0.0
    if cue is not None:
        center += rc["cue_weight"] * math.log1p(cue)
        notes.append(f"cue {cue:+.2%} x{rc['cue_weight']}")
    if extra_shift:
        center += extra_shift
        notes.append(f"ex-dividend shift {extra_shift:+.2%}")
    if direction:
        center += (1 if direction == "up" else -1) * (confidence - 0.5) * rc["ai_drift_scale"] * sigma_h
        if widen:
            sigma_h *= 1 + widen
            notes.append(f"AI widened +{widen:.0%}")
    cap = rc["max_center_shift_sigma"] * sigma_h
    center = max(-cap, min(cap, center))
    lo80, hi80 = rl.normal_quantiles(0.8)
    lo50, hi50 = rl.normal_quantiles(0.5)
    band = lambda q: round(base * math.exp(center + q * sigma_h), 4)  # noqa: E731
    n50 = rl.naive_range(base, naive_sd or sd, h, 0.5)
    n80 = rl.naive_range(base, naive_sd or sd, h, 0.8)
    return {"id": f"{as_of}-{ticker}-{h}d", "made_at": f"{as_of}T22:00:00+00:00", "as_of_date": str(as_of),
            "session_date": str(as_of), "target_date": str(target), "ticker": ticker, "horizon_days": h,
            "base_close": base, "center": round(center, 6), "sigma_h": round(sigma_h, 6),
            "lo50": band(lo50), "hi50": band(hi50), "lo80": band(lo80), "hi80": band(hi80),
            "naive_lo50": round(n50[0], 4), "naive_hi50": round(n50[1], 4),
            "naive_lo80": round(n80[0], 4), "naive_hi80": round(n80[1], 4),
            "direction": direction, "confidence": confidence, "regime": regime,
            "calibration_id": "test (normal)", "notes": notes}


# ---------- unit tests ----------

def test_weeks():
    assert review.week_bounds("2026-W40") == (date(2026, 9, 28), date(2026, 10, 4))
    assert review.previous_week(date(2026, 10, 5)) == "2026-W40"
    assert review.previous_week(date(2027, 1, 4)) == "2026-W53"


def test_note_tags():
    assert review.note_tags([]) == ["none"]
    assert review.note_tags(None) == ["none"]
    tags = review.note_tags(["earnings in horizon (x3.0 day)", "regime UNSTABLE x1.25", "major event x1.15",
                             "AI widened +20%", "cue -1.14% x0.5", "ex-dividend shift -1.00%"])
    assert tags == ["earnings", "regime", "event", "ai_widen", "cue", "ex-dividend"]


def test_replay_reproduces_published_ranges_and_changes_one_input():
    rows = [
        make_range(RC, "A", "2026-10-01", "2026-10-02", 1, 100.0, 0.015, cue=0.004),
        make_range(RC, "A", "2026-10-01", "2026-10-08", 5, 100.0, 0.015, regime="UNSTABLE", major=True,
                   earnings=True, direction="up", confidence=0.8, widen=0.3, extra_shift=-0.002),
        make_range(RC, "B", "2026-10-01", "2026-10-02", 1, 50.0, 0.02, cue=0.05),       # hits the centre cap
        make_range(RC, "C", "2026-10-01", "2026-10-02", 1, 10.0, 0.01, direction="down", confidence=0.6),
    ]
    for r in rows:
        r["actual_close"] = r["base_close"]
        comp = review.decompose(r, RC)
        out = review.replay(comp, RC)
        assert abs(out["lo80"] / r["lo80"] - 1) < 1e-6 and abs(out["hi80"] / r["hi80"] - 1) < 1e-6, r["notes"]
    # dropping the cue recentres the first range on the last close
    comp = review.decompose(rows[0], RC)
    no_cue = review.replay(comp, {**RC, "cue_weight": 0.0})
    assert math.isclose(math.sqrt(no_cue["lo80"] * no_cue["hi80"]), 100.0, rel_tol=1e-4)
    # dropping regime, event, earnings and AI widening narrows the second range, never shifts the outcome
    comp = review.decompose(rows[1], RC)
    plain = review.replay(comp, {**RC, "regime_factor": {}, "major_event_factor": 1.0,
                                 "earnings_vol_multiple": 1.0, "max_ai_widen": 0.0})
    published = review.replay(comp, RC)
    assert plain["width80"] < published["width80"] / 2
    assert comp["residual"] != 0                                    # the unknown ex-dividend shift is kept fixed


def test_gates_flag_small_samples():
    rv = {**review.DEFAULTS, "min_n_recommend": 200}
    good = {"rel_score": -0.10, "coverage_shortfall": 0.0, "coverage_gain": 0.05}
    assert review.verdict(good, 50, rv) == "low n"
    assert review.verdict(good, 500, rv) == "improves score"
    assert review.verdict({"rel_score": 0.0, "coverage_shortfall": 0.0, "coverage_gain": 0.05}, 500, rv) == "improves coverage"
    assert review.verdict({"rel_score": 0.05, "coverage_shortfall": 0.0, "coverage_gain": 0.0}, 500, rv) == "worse score"
    assert review.verdict({"rel_score": -0.01, "coverage_shortfall": 0.0, "coverage_gain": 0.0}, 500, rv) == "no material change"
    calls = pd.DataFrame({"confidence": [0.55] * 10 + [0.85] * 60, "hit": [True] * 10 + [True] * 30 + [False] * 30,
                          "actual_return": [0.01] * 70})
    bands = review.confidence_bands(calls, rv["confidence_bands"])
    assert bands["50%-60%"]["n"] == 10 and bands["80%-90%"]["n"] == 60 and bands["60%-70%"]["n"] == 0
    assert bands["80%-90%"]["gap"] == -0.35
    advice = review.confidence_advice(bands, {"all": review.call_summary(calls)}, rv)
    assert len(advice) == 2 and "80%-90%" in advice[0] and "always-up" in advice[1]   # small 50-60% band: no advice


def test_report_review_line():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("CREATE TABLE review_latest (id VARCHAR, week VARCHAR, report VARCHAR, n_proposals INTEGER, "
                "low_sample BOOLEAN, computed_at TIMESTAMPTZ)")
    assert report.weekly_review(con, date(2026, 10, 5)) is None
    con.execute("INSERT INTO review_latest VALUES ('2026-W40', '2026-W40', 'reports/x/review-2026-W40.md', 1, true, now())")
    rv = report.weekly_review(con, date(2026, 10, 6))            # any session in W41 sees the W40 review
    assert rv["fresh"] and rv["week"] == "2026-W40"
    line = report.review_line(rv, "https://example.com/r.md")
    assert line == "Weekly review 2026-W40: 1 proposed range change for a human to decide (low sample) · https://example.com/r.md"


def test_summaries_match_hand_calculation():
    """Four scored ranges around base 100: 50% range 98-102, 80% range 95-105, naive 99-101 / 97-103
    (row b: naive 97.5-103.5 / 96-105, so its naive 50% range hits while its own 50% range misses)."""
    ys = [100.0, 103.0, 110.0, 94.0]
    con = duckdb.connect()
    con.execute("""CREATE TABLE range_record AS SELECT * FROM (VALUES
        ('a', DATE '2026-10-01', 'A', 1, 100.0, 100.0, 98.0, 102.0, 95.0, 105.0, 99.0, 101.0, 97.0, 103.0,
         NULL, 'CALM', ['cue +1.00% x0.5'], true, true, true, true, 10.0, 6.0, 10.0, 6.0),
        ('b', DATE '2026-10-01', 'A', 1, 100.0, 103.0, 98.0, 102.0, 95.0, 105.0, 97.5, 103.5, 96.0, 105.0,
         'up', 'CALM', [], false, true, true, true, 10.0, 9.0, 10.0, 9.0),
        ('c', DATE '2026-10-02', 'B', 5, 100.0, 110.0, 98.0, 102.0, 95.0, 105.0, 99.0, 101.0, 97.0, 103.0,
         NULL, 'UNSTABLE', ['regime UNSTABLE x1.25'], false, false, false, false, 60.0, 76.0, 10.0, 6.0),
        ('d', DATE '2026-10-02', 'B', 5, 100.0, 94.0, 98.0, 102.0, 95.0, 105.0, 99.0, 101.0, 97.0, 103.0,
         NULL, 'CALM', [], false, false, false, false, 20.0, 36.0, 10.0, 6.0))
        t(id, target_date, ticker, horizon_days, base_close, actual_close, lo50, hi50, lo80, hi80,
          naive_lo50, naive_hi50, naive_lo80, naive_hi80, direction, regime, notes,
          hit50, hit80, naive_hit50, naive_hit80, is80_pct, naive_is80_pct, width80_pct, naive_width80_pct)""")
    # stored is80 matches the interval score by hand: width + (2/0.2) x miss distance
    naive80 = [(97, 103), (96, 105), (97, 103), (97, 103)]
    for y, stored, (nlo, nhi), naive in zip(ys, (10.0, 10.0, 60.0, 20.0), naive80, (6.0, 9.0, 76.0, 36.0)):
        assert math.isclose(100 * rl.interval_score(95, 105, y, 0.8) / 100, stored)
        assert math.isclose(100 * rl.interval_score(nlo, nhi, y, 0.8) / 100, naive)
    cfg = {"tickers": {"A": {"sector": "Tech"}, "B": {"sector": "Energy"}}}
    df = review.load_ranges(con, cfg, date(2026, 10, 4))
    # 50% score by hand: 4 + 4 x miss -> 4, 8, 36, 20; naive: width + 4 x miss -> 2, 6, 38, 22
    assert list(df["is50_pct"]) == [4.0, 8.0, 36.0, 20.0]
    assert list(df["naive_is50_pct"]) == [2.0, 6.0, 38.0, 22.0]
    assert list(df["width50_pct"]) == [4.0, 4.0, 4.0, 4.0]
    assert list(df["sector"]) == ["Tech", "Tech", "Energy", "Energy"]
    assert [t for t in df["tags"]] == [["cue"], ["none", "ai_call"], ["regime"], ["none"]]
    s = review.range_summary(df)
    assert s == {"n": 4, "cover50": 0.25, "cover80": 0.5, "naive_cover50": 0.5, "naive_cover80": 0.5,
                 "width50_pct": 4.0, "width80_pct": 10.0, "naive_width80_pct": 6.75,
                 "score50_pct": 17.0, "naive_score50_pct": 17.0, "score80_pct": 25.0, "naive_score80_pct": 31.75}
    by_h = review.by_horizon(df, review.range_summary)
    assert by_h["1d"]["cover80"] == 1.0 and by_h["5d"]["cover80"] == 0.0 and by_h["5d"]["score80_pct"] == 40.0
    br = review.breakdown(df, "tags")
    assert br["none · 5d"]["n"] == 1 and br["none · 1d"]["cover50"] == 0.0 and br["cue · 1d"]["score50_pct"] == 4.0

    calls = pd.DataFrame({"hit": [True, True, False, False], "actual_return": [0.01, 0.02, 0.03, -0.01],
                          "confidence": [0.6, 0.7, 0.8, 0.9]})
    c = review.call_summary(calls)
    assert c == {"n": 4, "hit_rate": 0.5, "always_up": 0.75, "edge": -0.25, "mean_confidence": 0.75}


def test_backtest_scale_widens_ranges():
    import backtest as bt
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2025-01-01", periods=320)
    bars = {"A": pd.DataFrame({"close": tp.fat_tailed_walk(rng, 320, 100, 0.01)}, index=idx),
            "B": pd.DataFrame({"close": tp.fat_tailed_walk(rng, 320, 50, 0.02)}, index=idx)}
    rank = {d: i for i, d in enumerate(idx)}
    obs = bt.observations(bars, ["A", "B"], 1, RC, rank)
    plain = bt.evaluate(obs, 1, RC, 40)
    ones = bt.evaluate(obs, 1, RC, 40, scale={i: 1.0 for i in range(320)})
    double = bt.evaluate(obs, 1, RC, 40, scale={i: 2.0 for i in range(320)})
    assert len(plain) == 80 and plain.equals(ones)                          # no scale = the formula as before
    ratio = double["width80"] / plain["width80"]
    assert ratio.between(1.95, 2.05).all() and (ratio != 1).all()           # log-width doubles exactly
    assert double["hit80"].mean() >= plain["hit80"].mean()
    assert not np.allclose(double["is80"], plain["is80"])
    # scale applies per start day only
    half = bt.evaluate(obs, 1, RC, 40, scale={int(plain["rank"].max()): 2.0})
    changed = half["width80"] != plain["width80"]
    assert set(half.loc[changed, "rank"]) == {int(plain["rank"].max())}


# ---------- end to end ----------

MARKET_YAML = (tp.MARKET_YAML.replace("  Tech: [AAPL, MSFT]\n", "  Tech: [AAPL, MSFT]\n  Energy: [XOM]\n")
               .replace("  MSFT: {name: Microsoft}\n", "  MSFT: {name: Microsoft}\n  XOM: {name: Exxon}\n"))


def build_market(tmp: Path):
    root, cfg = tp.setup(tmp)
    (cfg / "markets" / f"{tp.MARKET}.yaml").write_text(MARKET_YAML % (tmp / "feed.xml"))
    rv = yaml.safe_load((REPO / "config" / "review.yaml").read_text())
    rv.update({"min_n": 30, "min_n_recommend": 100, "min_n_calls": 20, "history_eval_sessions": 30,
               "history_variants": rv["history_variants"][:1] + [{"name": "EWMA lambda 0.97", "set": {"ewma_lambda": 0.97}}]})
    (cfg / "review.yaml").write_text(yaml.safe_dump(rv))

    rng = np.random.default_rng(5)
    n = 300
    days = tp.weekdays(date(2025, 8, 4), n)
    series = {"BENCH": tp.fat_tailed_walk(rng, n, 100, 0.01), "VOLX": [15.0] * n,
              "AAPL": tp.fat_tailed_walk(rng, n, 150, 0.015), "MSFT": tp.fat_tailed_walk(rng, n, 300, 0.012),
              "XOM": tp.fat_tailed_walk(rng, n, 80, 0.018)}
    tp.write_bars(root, series, days)

    # live period: the last 40 sessions publish ranges for every ticker and horizon
    ranges, preds = [], []
    for t in ("AAPL", "MSFT", "XOM"):
        close = pd.Series(series[t], index=pd.to_datetime(days))
        sig = rl.ewma_sigma(close, RC["ewma_lambda"])
        for i in range(n - 41, n - 1):
            for h in (1, 5):
                if i + h >= n:
                    continue
                k = len(ranges)
                ranges.append(make_range(
                    RC, t, days[i], days[i + h], h, round(series[t][i], 4), float(sig.iloc[i]),
                    naive_sd=rl.realized_sigma(close.iloc[: i + 1]),
                    regime="EVENT_HEAVY" if k % 4 == 0 else "CALM", major=k % 6 == 0,
                    cue=float(rng.choice([-0.03, 0.03])),            # pure noise: the review should drop it
                    direction="up" if (t == "AAPL" and h == 1) else None,
                    confidence=0.8 if (t == "AAPL" and h == 1) else None))
            if t == "AAPL":
                preds.append({"id": f"{days[i]}-AAPL-1d", "made_at": f"{days[i]}T22:00:00+00:00",
                              "as_of_date": str(days[i]), "ticker": "AAPL", "horizon_days": 1, "direction": "up",
                              "confidence": 0.8, "rationale": "t", "evidence_ids": ["x"], "prompt_version": "test",
                              "range_widen": None})
    for kind, rows in (("ranges", ranges), ("predictions", preds)):
        p = root / "data" / tp.MARKET / kind / "2026" / "01" / "2026-01-01.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    cal = root / "data" / tp.MARKET / "calibration" / "2026" / "01" / "2026-01-01.jsonl"
    cal.parent.mkdir(parents=True)
    cal.write_text("".join(json.dumps({"id": f"{days[-41]}-{h}d", "as_of_date": str(days[-41]),
                                       "computed_at": "2026-01-01T00:00:00+00:00", "horizon_days": h,
                                       "q10": -1.28, "q25": -0.67, "q75": 0.67, "q90": 1.28, "n_history": 900,
                                       "n_live": 0, "source": "normal"}) + "\n" for h in (1, 5)))
    s = tp.run("score_predictions.py", root, cfg)
    assert s.returncode == 0, s.stderr
    assert json.loads(s.stdout)["ranges_scored"] == len(ranges)
    return root, cfg, days, len(ranges)


def records(root: Path) -> list[dict]:
    return [json.loads(line) for f in sorted((root / "data" / tp.MARKET / "reviews").glob("**/*.jsonl"))
            for line in f.read_text().splitlines()]


def test_review_end_to_end(tmp_path):
    root, cfg, days, n_ranges = build_market(tmp_path)
    week = review.iso_week(days[-1])
    r = tp.run("review.py", root, cfg, "--week", week)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["due"] and out["n_ranges_all"] == n_ranges and out["n_ranges_week"] > 0
    assert out["low_sample"] is False and out["n_calls_all"] == 40

    [rec] = records(root)
    assert rec["id"] == week and rec["report"] == f"reports/{tp.MARKET}/review-{week}.md"
    d = rec["detail"]
    assert set(d["ranges"]) == {"week", "rolling", "all"} and set(d["ranges"]["all"]) == {"all", "1d", "5d"}
    b = d["breakdowns"]
    assert set(b) == {"week", "rolling", "all"} and set(d["bands"]) == {"week", "rolling", "all"}
    assert any(k.startswith("Energy") for k in b["all"]["sector"])
    assert {"cue", "regime", "event", "ai_call"} <= {k.split(" · ")[0] for k in b["all"]["note"]}
    assert set(b["all"]["regime"]) >= {"CALM · 5d", "EVENT_HEAVY · 1d"}
    for key in ("regime", "sector", "note"):                                  # windows nest: week <= 30d <= all
        n = {w: sum(x["n"] for x in b[w][key].values()) for w in b}
        assert 0 < n["week"] < n["rolling"] < n["all"], (key, n)
    assert 0 < d["bands"]["week"]["80%-90%"]["n"] < d["bands"]["rolling"]["80%-90%"]["n"] < 40
    assert d["bands"]["all"]["80%-90%"]["n"] == 40

    # since-start coverage equals the scored outcomes on disk
    outs = [json.loads(x) for f in (root / "data" / tp.MARKET / "range_outcomes").glob("**/*.jsonl")
            for x in f.read_text().splitlines()]
    a = d["ranges"]["all"]["all"]
    assert a["cover80"] == round(sum(o["hit80"] for o in outs) / len(outs), 4)
    assert a["cover50"] == round(sum(o["hit50"] for o in outs) / len(outs), 4)
    assert a["naive_cover80"] == round(sum(o["naive_hit80"] for o in outs) / len(outs), 4)
    assert a["score80_pct"] == round(sum(o["is80_pct"] for o in outs) / len(outs), 3)

    live = d["live_ablation"]
    assert live["n"] == n_ranges and live["reproduced"] == n_ranges          # replay matches every published range
    verdicts = {v["name"]: v["verdict"] for v in live["variants"]}
    assert verdicts["current config"] == "baseline" and verdicts["drop overnight cue"] == "improves score"
    hist = {v["name"]: v for v in d["history_ablation"]["variants"]}
    assert d["history_ablation"]["n"] > 0 and len(hist) == 3
    base = hist["current config"]["by_h"]
    for name in ("drop regime widening", "EWMA lambda 0.97"):               # each variant really changes the ranges
        var = hist[name]["by_h"]
        assert set(var) == set(base) == {"1d", "5d"}
        assert any(var[h]["width80_pct"] != base[h]["width80_pct"] for h in base), name
        assert any(var[h]["score80_pct"] != base[h]["score80_pct"] for h in base), name
    assert all(hist["drop regime widening"]["by_h"][h]["width80_pct"] < base[h]["width80_pct"] for h in base)
    assert "EVENT_HEAVY" in d["history_ablation"]["regime_share"] and d["history_ablation"]["regime_share"]["EVENT_HEAVY"] > 0

    props = {(c["param"], p["source"]): c for p in rec["proposals"] for c in p["changes"]}
    assert props[("cue_weight", "live replay")]["proposed"] == 0.0 and rec["n_proposals"] == len(rec["proposals"])
    assert any("80%-90%" in a for a in d["advice"])                          # 80% calls that hit about half the time

    text = (root / rec["report"]).read_text()
    for needle in ("## Ranges: coverage vs target", "### By widening note", "## Direction calls",
                   "### By confidence band", "## Calibration", "## Ablation: replay of live scored ranges",
                   "Round-trip consistency check against the current config",
                   "## Ablation: walk-forward on stored prices", "## Proposed changes to config/ranges.yaml",
                   "`cue_weight`", "**Not applied.**", "drop overnight cue", "low n"):
        assert needle in text, needle
    # every coverage row is flagged exactly when n < min_n (30), and both kinds occur
    section = text.split("## Ranges: coverage vs target")[1].split("###")[0]
    rows = [[c.strip() for c in line.strip("|").split("|")] for line in section.splitlines()
            if line.startswith("| ") and not line.startswith("| Window")]
    assert len(rows) == 9
    assert all((r[-1] == "low n") == (int(r[2]) < 30) for r in rows), rows
    assert {r[-1] for r in rows} == {"low n", ""}
    assert [r[-1] for r in rows if r[0] == f"week {week}" and r[1] == "1d"] == ["low n"]
    # config is never touched
    assert yaml.safe_load((cfg / "ranges.yaml").read_text()) == RC

    # the review record is readable through DuckDB (schema + view)
    q = tp.run("review.py", root, cfg, "--week", week, "--if-due")
    assert q.returncode == 0, q.stderr
    assert json.loads(q.stdout)["due"] is False and len(records(root)) == 1


def test_review_with_little_data_makes_no_live_proposal(tmp_path):
    root, cfg, days, _ = build_market(tmp_path)
    week = review.iso_week(days[-40] + timedelta(days=7))          # a week into the live period
    r = tp.run("review.py", root, cfg, "--week", week, "--no-history")
    assert r.returncode == 0, r.stderr
    [rec] = records(root)
    assert rec["low_sample"] is True and 0 < rec["n_ranges_all"] < 100
    assert rec["proposals"] == []                                            # history skipped, live below min n
    assert all(v["verdict"] in ("baseline", "low n") for v in rec["detail"]["live_ablation"]["variants"])
    text = (root / rec["report"]).read_text()
    assert "**Low sample:**" in text and "_None: no variant cleared the thresholds" in text


def test_review_on_empty_market(tmp_path):
    root, cfg = tp.setup(tmp_path)
    r = tp.run("review.py", root, cfg, "--week", "2026-W40")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["n_ranges_all"] == 0 and out["low_sample"] and out["proposals"] == []
    assert "_No scored live ranges yet._" in (root / out["report"]).read_text()


# ---------- windows, look-ahead and gates ----------

TH = {"unstable_vol": 28, "event_vol": 20, "calm_vol": 16, "unstable_bench_vol": 0.25,
      "trend_return_5d": 0.015, "flat_return_5d": 0.005, "stress_vol_jump": 0.30}


def window_con(target_dates: list[date]):
    """In-memory DuckDB with one scored range and one scored call per target date."""
    from marketbrief.core.schemas import SCHEMAS
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(f"CREATE TABLE calibration ({', '.join(f'{k} {v}' for k, v in SCHEMAS['calibration'][1].items())})")
    ranges = pd.DataFrame([{  # noqa: F841  (read by DuckDB below)
        "id": f"r{i}", "target_date": d, "ticker": "A", "horizon_days": 1, "base_close": 100.0, "actual_close": 100.0,
        "center": 0.0, "sigma_h": 0.02, "lo50": 98.0, "hi50": 102.0, "lo80": 95.0, "hi80": 105.0,
        "naive_lo50": 99.0, "naive_hi50": 101.0, "naive_lo80": 97.0, "naive_hi80": 103.0, "direction": None,
        "confidence": None, "regime": "CALM", "notes": [], "hit50": True, "hit80": True, "naive_hit50": True,
        "naive_hit80": True, "is80_pct": 10.0, "naive_is80_pct": 6.0, "width80_pct": 10.0, "naive_width80_pct": 6.0}
        for i, d in enumerate(target_dates)])
    calls = pd.DataFrame([{"id": f"c{i}", "target_date": d, "horizon_days": 1,  # noqa: F841
                           "confidence": 0.85, "hit": True, "actual_return": 0.01} for i, d in enumerate(target_dates)])
    con.execute("CREATE TABLE range_record AS SELECT * FROM ranges")
    con.execute("CREATE TABLE track_record AS SELECT * FROM calls")
    return con


def test_window_boundaries_and_no_data_after_the_week():
    start, end = review.week_bounds("2026-W40")                              # 2026-09-28 .. 2026-10-04
    dates = [start - timedelta(days=1), start, end, end + timedelta(days=1),
             end - timedelta(days=29), end - timedelta(days=30)]
    rv = {**review.DEFAULTS, "rolling_days": 30}
    cfg = {"market": "testmkt", "tickers": {"A": {"sector": "Tech"}}}
    rec, d = review.build(cfg, RC, rv, window_con(dates), "2026-W40", history=False)
    # week: start, end · 30 days: end-29 .. end · since start: all up to end (end+1 is after the week)
    assert (rec["n_ranges_week"], rec["n_ranges_30d"], rec["n_ranges_all"]) == (2, 4, 5)
    assert {w: d["calls"][w]["all"]["n"] for w in d["calls"]} == {"week": 2, "rolling": 4, "all": 5}
    assert {w: d["bands"][w]["80%-90%"]["n"] for w in d["bands"]} == {"week": 2, "rolling": 4, "all": 5}
    assert {w: d["breakdowns"][w]["sector"]["Tech · 1d"]["n"] for w in d["breakdowns"]} == \
        {"week": 2, "rolling": 4, "all": 5}
    assert rec["detail"]["live_ablation"]["n"] == 5 and rec["n_calls_all"] == 5


def test_confidence_bands_edges():
    calls = pd.DataFrame({"confidence": [0.50, 0.59, 0.60, 0.70, 0.79, 0.80, 0.85, 0.90],
                          "hit": [True] * 8, "actual_return": [0.01] * 8})
    bands = review.confidence_bands(calls, [0.5, 0.6, 0.7, 0.8, 0.9])
    # lower edge inclusive, upper exclusive, except the top band which keeps 0.90 (the maximum allowed)
    assert {b: s["n"] for b, s in bands.items()} == {"50%-60%": 2, "60%-70%": 1, "70%-80%": 2, "80%-90%": 3}
    assert bands["80%-90%"]["mean_confidence"] == 0.85


def test_compare_coverage_terms():
    base = {"1d": {"n": 100, "cover50": 0.50, "cover80": 0.80, "score80_pct": 5.0},
            "5d": {"n": 100, "cover50": 0.50, "cover80": 0.80, "score80_pct": 10.0}}

    def var(c50_1, c80_1, s1, c50_5=0.50, c80_5=0.80, s5=10.0):
        return {"1d": {"n": 100, "cover50": c50_1, "cover80": c80_1, "score80_pct": s1},
                "5d": {"n": 100, "cover50": c50_5, "cover80": c80_5, "score80_pct": s5}}
    # 80% coverage moving away from target: negative gain, and a shortfall when it drops below
    c = review.compare(base, var(0.50, 0.70, 5.0))
    assert c == {"rel_score": 0.0, "coverage_shortfall": 0.1, "coverage_gain": -0.05}
    assert review.compare(base, var(0.50, 0.90, 5.0))["coverage_gain"] == -0.05      # over-covering
    assert review.compare(base, var(0.50, 0.90, 5.0))["coverage_shortfall"] == 0.0
    # a drop below target in the 50% band only still counts as a shortfall
    c = review.compare(base, var(0.42, 0.80, 5.0))
    assert c["coverage_shortfall"] == 0.08 and c["coverage_gain"] == 0.0
    # moving towards target from below: positive gain; scores averaged as relative changes
    worse = {**base, "1d": {**base["1d"], "cover80": 0.70}}
    c = review.compare(worse, var(0.50, 0.78, 4.5, s5=11.0))
    assert c == {"rel_score": 0.0, "coverage_shortfall": 0.0, "coverage_gain": 0.04}
    assert review.compare(base, {"1d": {"n": 0}}) is None


def test_history_regime_uses_the_next_session():
    """A major event counts when it falls within 2 days of the NEXT session (as features.py)."""
    idx = pd.bdate_range("2026-09-14", "2026-11-03")
    bars = {"BENCH": pd.DataFrame({"close": [100 * 1.0001 ** i for i in range(len(idx))]}, index=idx),
            "VOLX": pd.DataFrame({"close": [15.0] * len(idx)}, index=idx)}
    cfg = {"market": "us", "calendar": "XNYS", "regime": TH,
           "symbols": {"BENCH": {"role": "benchmark"}, "VOLX": {"role": "vol_index"}}}
    regimes, majors = review.history_context(cfg, bars, list(idx))
    assert date(2026, 10, 28) in majors                                        # FOMC (config/events.yaml)
    reg = dict(zip((d.date() for d in idx), regimes))
    assert reg[date(2026, 10, 22)] == "CALM"            # next session 10-23: window 10-23..10-25
    assert reg[date(2026, 10, 23)] == "EVENT_HEAVY"     # next session 10-26: window reaches 10-28
    assert reg[date(2026, 10, 27)] == "EVENT_HEAVY"     # next session is the event day
    assert reg[date(2026, 10, 28)] == "CALM"            # event day itself: the next session is after it


def test_flag_threshold():
    rv = {**review.DEFAULTS, "min_n": 30}
    assert review.flag(29, rv) == "low n" and review.flag(30, rv) == "" and review.flag(0, rv) == "low n"


def test_coverage_gate_needs_a_score_no_worse():
    rv = {**review.DEFAULTS, "min_n_recommend": 200}
    assert review.verdict({"rel_score": 0.01, "coverage_shortfall": 0.0, "coverage_gain": 0.10}, 500, rv) \
        == "no material change"
    assert review.verdict({"rel_score": 0.0, "coverage_shortfall": 0.0, "coverage_gain": 0.10}, 500, rv) \
        == "improves coverage"


def ablation(name: str, setting: dict, verdict: str, rel: float) -> dict:
    by_h = {"1d": {"n": 300, "cover80": 0.8, "score80_pct": 5.0}}
    return {"variants": [{"name": "current config", "set": {}, "n": 300, "by_h": by_h, "verdict": "baseline"},
                         {"name": name, "set": setting, "n": 300, "by_h": by_h, "verdict": verdict,
                          "vs_current": {"rel_score": rel, "coverage_shortfall": 0.0, "coverage_gain": 0.0}}]}


def test_proposals_prefer_live_evidence():
    flat = {"regime_factor": {"CALM": 1.0, "TRENDING": 1.0, "EVENT_HEAVY": 1.0, "UNSTABLE": 1.0}}
    hist = ablation("drop regime widening", flat, "improves score", -0.05)
    [p] = review.proposals(RC, {"variants": []}, hist)                      # history alone proposes
    assert p["source"] == "history walk-forward" and p["changes"][0]["param"] == "regime_factor"
    assert p["changes"][0]["current"] == RC["regime_factor"] and p["drop"]
    # live evidence (n >= min) that the change is worse suppresses the history proposal
    assert review.proposals(RC, ablation("drop regime widening", flat, "worse score", 0.04), hist) == []
    assert review.proposals(RC, ablation("drop regime widening", flat, "under-covers", 0.0), hist) == []
    # a live improvement wins over history for the same parameter
    [p] = review.proposals(RC, ablation("drop regime widening", flat, "improves score", -0.03), hist)
    assert p["source"] == "live replay" and p["rel_score"] == -0.03
    assert review.proposals(RC, ablation("x", {"cue_weight": 0.0}, "low n", -0.5), {"variants": []}) == []


def test_major_event_counts_after_start_up_to_target():
    majors = [date(2026, 10, 2)]
    assert not major_event_between(majors, date(2026, 10, 2), date(2026, 10, 9))   # on the as-of day: known
    assert major_event_between(majors, date(2026, 10, 1), date(2026, 10, 2))        # on the target day
    assert major_event_between(majors, date(2026, 9, 28), date(2026, 10, 5))        # inside the horizon
    assert not major_event_between(majors, date(2026, 9, 25), date(2026, 10, 1))    # after the target
    assert not major_event_between([], date(2026, 9, 25), date(2026, 10, 1))


def test_history_ablation_never_looks_past_the_week():
    rng = np.random.default_rng(9)
    n = 340
    idx = pd.bdate_range("2025-03-03", periods=n)

    def walk(start, vol):
        return pd.DataFrame({"close": tp.fat_tailed_walk(rng, n, start, vol)}, index=idx)
    bars = {"BENCH": walk(100, 0.01), "A": walk(150, 0.015), "B": walk(80, 0.02),
            "VOLX": pd.DataFrame({"close": list(np.linspace(14, 30, n))}, index=idx)}   # crosses regime thresholds
    cfg = {"market": "testmkt", "calendar": "XNYS", "regime": TH, "tickers": {"A": {}, "B": {}},
           "symbols": {"BENCH": {"role": "benchmark"}, "VOLX": {"role": "vol_index"}}}
    rv = {**review.DEFAULTS, "history_eval_sessions": 30,
          "history_variants": [{"name": "drop regime widening",
                                "set": {"regime_factor": {k: 1.0 for k in RC["regime_factor"]}}}]}
    week_end = idx[-60].date()
    cut = {t: df[df.index <= pd.Timestamp(week_end)] for t, df in bars.items()}
    past = review.history_ablation(cfg, RC, rv, bars, week_end)
    assert past["n"] > 0 and past == review.history_ablation(cfg, RC, rv, cut, week_end)   # later bars change nothing
    assert past != review.history_ablation(cfg, RC, rv, bars, idx[-1].date())


def test_weekly_review_written_earlier_is_not_fresh():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("CREATE TABLE review_latest (id VARCHAR, week VARCHAR, report VARCHAR, n_proposals INTEGER, "
                "low_sample BOOLEAN, computed_at TIMESTAMPTZ)")
    con.execute("INSERT INTO review_latest VALUES ('2026-W40', '2026-W40', 'reports/x/review-2026-W40.md', 0, false, "
                "now() - INTERVAL 2 DAY)")
    rv = report.weekly_review(con, date(2026, 10, 7))
    assert rv is not None and rv["fresh"] is False                          # linked in the report, no Slack line
