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
    assert any(k.startswith("Energy") for k in d["breakdowns"]["sector"])
    assert {"cue", "regime", "event", "ai_call"} <= {k.split(" · ")[0] for k in d["breakdowns"]["note"]}
    assert set(d["breakdowns"]["regime"]) >= {"CALM · 5d", "EVENT_HEAVY · 1d"}

    live = d["live_ablation"]
    assert live["n"] == n_ranges and live["reproduced"] == n_ranges          # replay matches every published range
    verdicts = {v["name"]: v["verdict"] for v in live["variants"]}
    assert verdicts["current config"] == "baseline" and verdicts["drop overnight cue"] == "improves score"
    assert d["history_ablation"]["n"] > 0 and len(d["history_ablation"]["variants"]) == 3

    props = {(c["param"], p["source"]): c for p in rec["proposals"] for c in p["changes"]}
    assert props[("cue_weight", "live replay")]["proposed"] == 0.0 and rec["n_proposals"] == len(rec["proposals"])
    assert any("80%-90%" in a for a in d["advice"])                          # 80% calls that hit about half the time

    text = (root / rec["report"]).read_text()
    for needle in ("## Ranges: coverage vs target", "### By widening note", "## Direction calls",
                   "### By confidence band", "## Calibration", "## Ablation: replay of live scored ranges",
                   "## Ablation: walk-forward on stored prices", "## Proposed changes to config/ranges.yaml",
                   "`cue_weight`", "**Not applied.**", "drop overnight cue", "low n"):
        assert needle in text, needle
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
