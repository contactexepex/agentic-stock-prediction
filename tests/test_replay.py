"""Historical replay (scripts/replay.py): same ranges as ranges.py on a sample day, no look-ahead,
and the direction-baseline statistics on synthetic series.
Run: pytest -q"""
from __future__ import annotations

import json
import re
import math
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.core import calendar as ev  # noqa: E402
from marketbrief.analytics import indicators as ind  # noqa: E402
from marketbrief.constants import replay
from marketbrief.replay import html_parts
from marketbrief.replay.rule_replay import inputs
from marketbrief.replay.rule_replay import replay_statistics  # noqa: E402
from test_pipeline import MARKET, SCRIPTS, fat_tailed_walk, run, setup, write_bars  # noqa: E402

XNYS = {"market": "x", "calendar": "XNYS", "timezone": "America/New_York"}
N = 330
D_POS = N - 12          # the sample as-of day: its 1d and 5d targets are inside the stored bars

DUMP = """
import json, sys, datetime
from marketbrief.constants import replay
from marketbrief.replay import html_parts
from marketbrief.replay.rule_replay import inputs
from marketbrief.replay.rule_replay import range_rows
from marketbrief.replay.rule_replay import replay_statistics  # noqa: E402
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market, load_ranges_config
cfg = load_market('testmkt'); rc = load_ranges_config('testmkt')
bars, extra = inputs.load_inputs(cfg, rc, connect('testmkt'))
start = datetime.date.fromisoformat(sys.argv[1]) if sys.argv[1] != '-' else None
end = datetime.date.fromisoformat(sys.argv[2]) if sys.argv[2] != '-' else None
res, reg = range_rows.replay_rows(cfg, rc, bars, extra, start, end)
rows = [r for h, g in res.items() for r in g.to_dict('records')]
print(json.dumps(rows, default=str))
"""

FEATURES = """
import json, sys, datetime
from marketbrief.analytics import features
from marketbrief.core.market_config import load_market
cfg = load_market('testmkt')
d = datetime.date.fromisoformat(sys.argv[1])
print(json.dumps(features.run(cfg, today_local=d, utc_day=d), default=str))
"""


def sessions(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if ev.is_session(XNYS, d):
            out.append(d)
        d += timedelta(days=1)
    return out


def py(code: str, root: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess:
    import os
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET}
    return subprocess.run([sys.executable, "-c", code, *args], cwd=SCRIPTS, env=env, capture_output=True,
                          text=True, check=False)


def build(tmp: Path, name: str, days: list[date], series: dict, events: list[dict],
          cue: bool = False) -> tuple[Path, Path]:
    root, cfg = setup(tmp / name)
    # earnings_history on for the test market's 1-day ranges, so both earnings paths are exercised
    rc = (cfg / "ranges.yaml").read_text().replace("enabled: {us: [1]}", "enabled: {us: [1], testmkt: [1]}")
    if cue:   # India's path: beta split of an index cue whose beta is fitted ("fit"), 1-day ranges
        rc = rc.replace("enabled: {india: [1]}", "enabled: {india: [1], testmkt: [1]}")
        mk = cfg / "markets" / f"{MARKET}.yaml"
        text = mk.read_text().replace("  VOLX: {role: vol_index, name: Vol index}\n",
                                      "  VOLX: {role: vol_index, name: Vol index}\n  CUE: {role: cue, name: Index cue}\n")
        mk.write_text(text + "index_cue: {symbol: CUE, beta: fit}\n")
    (cfg / "ranges.yaml").write_text(rc)
    write_bars(root, series, days)
    p = root / "data" / MARKET / "events" / "2024" / "01" / "2024-01-01.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(e) + "\n" for e in events))
    return root, cfg


def fixture(tmp: Path):
    rng = np.random.default_rng(7)
    days = sessions(date(2024, 6, 3), N)
    bench = fat_tailed_walk(rng, N, 100, 0.01)
    series = {"BENCH": bench, "AAPL": list(1.5 * np.array(bench) * np.array(fat_tailed_walk(rng, N, 1, 0.011))),
              "MSFT": fat_tailed_walk(rng, N, 300, 0.012),
              "VOLX": list(np.clip(20 + np.cumsum(rng.normal(0, 1.2, N)), 11, 35))}
    series["CUE"] = list(np.array(series["BENCH"]) * np.exp(rng.normal(0, 0.006, N)))   # tracks the benchmark
    d = days[D_POS]
    session = days[D_POS + 1]
    seen = "2024-01-01T00:00:00+00:00"
    events = [{"id": f"AAPL-earnings-{days[i]}", "date": str(days[i]), "type": "earnings", "ticker": "AAPL",
               "name": "Apple earnings", "source": "yfinance_history", "first_seen_at": seen, "timing": "after_close"}
              for i in (100, 163, 226, 289)]
    events += [{"id": f"AAPL-earnings-{session}", "date": str(session), "type": "earnings", "ticker": "AAPL",
                "name": "Apple earnings", "source": "yfinance", "first_seen_at": seen, "timing": "before_open"},
               {"id": f"MSFT-ex_dividend-{days[D_POS + 3]}", "date": str(days[D_POS + 3]), "type": "ex_dividend",
                "ticker": "MSFT", "name": "Microsoft ex-dividend", "source": "yfinance", "first_seen_at": seen,
                "amount": 2.5}]
    return days, series, events, d, session


def dump(root: Path, cfg: Path, start: str = "-", end: str = "-") -> list[dict]:
    r = py(DUMP, root, cfg, start, end)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


RANGE_FIELDS = ("lo50", "hi50", "lo80", "hi80", "center", "sigma_h", "base")


@pytest.mark.parametrize("cue", [False, True])
def test_replay_ranges_equal_ranges_py(tmp_path, cue):
    days, series, events, d, session = fixture(tmp_path)
    # the live pipeline on the bars known at d: features (regime), calibrate, ranges pre-open the next session
    live_root, live_cfg = build(tmp_path, "live", days[:D_POS + 1], {k: v[:D_POS + 1] for k, v in series.items()},
                                events, cue)
    if cue:   # the pre-open quote of the index cue: its last session's change (collected today, quoted pre-open S)
        today = datetime.now(timezone.utc).date()
        q = {"symbol": "CUE", "yahoo": "CUE", "ts": f"{session}T12:00:00+00:00", "price": series["CUE"][D_POS],
             "prev_close": series["CUE"][D_POS - 1], "change_pct": series["CUE"][D_POS] / series["CUE"][D_POS - 1] - 1,
             "collected_at": f"{today}T00:00:00+00:00"}
        qp = live_root / "data" / MARKET / "quotes" / f"{today:%Y}" / f"{today:%m}" / f"{today}.jsonl"
        qp.parent.mkdir(parents=True, exist_ok=True)
        qp.write_text(json.dumps(q) + "\n")
    r = py(FEATURES, live_root, live_cfg, str(session))
    assert r.returncode == 0, r.stderr
    regime = json.loads(r.stdout)["regime"]
    assert run("calibrate.py", live_root, live_cfg).returncode == 0
    r = run("ranges.py", live_root, live_cfg, "--now", f"{session}T12:00:00+00:00")
    assert r.returncode == 0, r.stderr
    live = {(x["ticker"], x["horizon_days"]): x for f in (live_root / "data" / MARKET / "ranges").glob("**/*.jsonl")
            for x in map(json.loads, f.read_text().splitlines())}
    assert len(live) == 4
    notes = " ".join(n for x in live.values() for n in x["notes"])
    assert "earnings in horizon" in notes and "past moves" in notes and "ex-dividend" in notes
    assert ("expected from CUE" in notes) is cue
    if cue:
        assert all("beta_split" in live[(t, 1)]["inputs"] for t in ("AAPL", "MSFT"))
        assert live[("AAPL", 1)]["center"] != 0               # AAPL tracks the benchmark (beta near 1)
        assert all("beta_split" not in live[(t, 5)]["inputs"] for t in ("AAPL", "MSFT"))

    # the replay over all stored bars (outcomes included), day d only
    full_root, full_cfg = build(tmp_path, "full", days, series, events, cue)
    rows = {(x["ticker"], int(x["h"])): x for x in dump(full_root, full_cfg, str(d), str(d))}
    assert set(rows) == set(live)
    for key, lv in live.items():
        rp = rows[key]
        assert rp["regime"] == lv["regime"] == regime
        assert rp["date"] == lv["as_of_date"] and rp["target_date"] == lv["target_date"]
        assert rp["base"] == pytest.approx(lv["base_close"], abs=1e-9)
        assert rp["center"] == pytest.approx(lv["center"], abs=2e-6)
        assert rp["sigma_h"] == pytest.approx(lv["sigma_h"], abs=2e-6)
        for k in ("lo50", "hi50", "lo80", "hi80", "naive_lo50", "naive_hi50", "naive_lo80", "naive_hi80"):
            assert rp[k] == pytest.approx(lv[k], abs=2e-4), (key, k)
        assert rp["actual"] == pytest.approx(series[key[0]][D_POS + key[1]], rel=1e-9)   # scored on the h-th close
    assert rows[("AAPL", 1)]["earn"] and rows[("AAPL", 5)]["earn"] and rows[("MSFT", 5)]["div"]


def test_replay_has_no_lookahead(tmp_path):
    days, series, events, d, _ = fixture(tmp_path)
    base_root, base_cfg = build(tmp_path, "base", days, series, events)
    rng = np.random.default_rng(99)
    shaken = {k: [x if i <= D_POS else x * float(np.exp(rng.normal(0, 0.05))) for i, x in enumerate(v)]
              for k, v in series.items()}
    pert_root, pert_cfg = build(tmp_path, "pert", days, shaken, events)
    a = {(x["ticker"], int(x["h"]), x["date"]): x for x in dump(base_root, base_cfg)}
    b = {(x["ticker"], int(x["h"]), x["date"]): x for x in dump(pert_root, pert_cfg)}
    assert a.keys() == b.keys()
    on_d = [k for k in a if k[2] == str(d)]
    assert len(on_d) == 4
    for k in on_d:   # everything known at d is unchanged; only the outcome moved
        for f in (*RANGE_FIELDS, "regime", "earn", "div", "major", "rsi", "ret1", "ret5"):
            assert a[k][f] == b[k][f], (k, f)
    assert any(a[k]["actual"] != b[k]["actual"] for k in on_d)
    # and every earlier day too (days whose outcome is after d only change in the outcome)
    early = [k for k in a if k[2] <= str(d)]
    assert len(early) > 400
    for k in early:
        assert all(a[k][f] == b[k][f] for f in RANGE_FIELDS), k


def test_replay_cli_writes_report_json_and_record(tmp_path):
    days, series, events, _, _ = fixture(tmp_path)
    root, cfg = build(tmp_path, "cli", days, series, events)
    r = run("replay.py", root, cfg)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    end = str(days[-1])
    assert out["end"] == end and out["start"] == str(days[60])
    page = (root / out["report"]).read_text()
    for needle in ("Historical replay", "Do the ranges keep their promise?", "Where are they too wide or too narrow?",
                   "Do simple up/down rules work?", "Direction baselines", 'id="sector"', "not the product's forecasts",
                   "Look for:", "interval score", "pts = percentage points", "95% interval ="):
        assert needle in page, needle
    assert "http://" not in page and "https://" not in page          # self-contained, no network
    assert page.count("<svg") == 3 and page.count("<details>") == 6 and page.count('class="card tile"') == 4
    assert "textContent" in page and "innerHTML" not in page
    # the dense parts sit in collapsed sections: before the first <details> only the answers, tiles and charts
    head = page.split("<details>")[0]
    assert "<table" not in head and 'class="summary"' not in head
    s = json.loads((root / out["json"]).read_text())
    assert 1 <= len(s["top"]) <= 4 and all(len(x) < 400 for x in s["top"])
    for x in s["summary"] + s["top"]:   # one decimal everywhere, never a whole-number rounding of a rate
        labels = x.replace("80%", "").replace("50%", "").replace("95%", "")   # band names, not measured rates
        assert not re.search(r"(?<![\d.])\d+%", labels), x
    assert s["horizons"]["1"]["overall"]["n"] > 400 and len(s["horizons"]["1"]["calibration"]) == len(replay.LEVELS)
    rec = py("from marketbrief.core.database import connect; print(connect('testmkt').execute("
             "'SELECT count(*), max(cover80_1d), CAST(max(end_date) AS VARCHAR) FROM replays').fetchone())", root, cfg)
    assert rec.returncode == 0, rec.stderr
    assert rec.stdout.strip().startswith("(1, ") and end in rec.stdout
    # issues #27/#28: the record's id carries its run time (a re-run is a new id), its file the UTC run date
    [stored] = list((root / "data" / "testmkt" / "replays").glob("**/*.jsonl"))
    row = json.loads(stored.read_text().splitlines()[0])
    assert row["id"] == f"{row['start_date']}_{row['end_date']}@{row['computed_at']}"
    assert stored.stem == row["computed_at"][:10]


# ---------- statistics on synthetic series ----------

def test_baseline_hit_rates_on_synthetic_series():
    n = 200
    fwd = np.where(np.arange(n) % 2 == 0, 0.01, -0.01)
    fwd[10] = 0.0                                              # a flat close is a miss for every call
    ret1 = np.r_[np.nan, np.sign(fwd[:-1]) * 0.01]             # last return = the opposite of the next one
    rsi = np.where(np.arange(n) % 4 == 0, 20.0, np.where(np.arange(n) % 4 == 1, 80.0, 50.0))
    g = pd.DataFrame({"date": [date(2025, 1, 1) + timedelta(days=i) for i in range(n)], "rank": np.arange(n),
                      "ticker": "X", "fwd": fwd, "actual": 100 * np.exp(fwd), "ret1": ret1, "ret5": np.nan, "rsi": rsi})
    b = replay_statistics.baseline_stats(g, 1)
    au = b["always_up"]
    assert au["calls"] == n and au["hits"] == 99 and au["hit_rate"] == pytest.approx(99 / n, abs=1e-4)
    m1 = b["momentum_1d"]
    assert m1["calls"] == n - 1 - 1 and m1["hits"] == 0      # no call on the first row or after the flat one
    assert m1["p_vs_50"] < 1e-12 and m1["diff_vs_always_up"] < 0 and m1["diff_ci95"][1] < 0
    assert b["momentum_5d"]["calls"] == 0 and b["momentum_5d"]["hit_rate"] is None
    mr = b["rsi_reversion"]                                    # RSI 20 on up days, 80 on down days: always right
    assert mr["calls"] == n // 2 and mr["hits"] == n // 2 and mr["coverage"] == 0.5   # flat row 10 has RSI 50: no call
    lo, hi = au["ci95_iid"]
    assert lo < 0.5 < hi and au["p_vs_50"] > 0.8


def test_tiny_p_values_print_as_less_than():
    assert html_parts.p_value_text(0.0) == "<0.001" and html_parts.p_value_text(4.2e-9) == "<0.001"
    assert html_parts.p_value_text(0.0123) == "0.0123" and html_parts.p_value_text(None) == ""


def test_replay_page_details_issue_27():
    """The stored p-value is unrounded (rounded only on the page), the calibration chart names its y axis, and a
    hit-rate tile says whether its 95% interval excludes a coin flip."""
    from marketbrief.replay.rule_replay import replay_statistics, rule_charts, rule_html

    p = replay_statistics.binom_p_two_sided(61, 100)
    assert p != float(f"{p:.3g}") and html_parts.p_value_text(p) == f"{p:.3g}"
    svg = rule_charts.svg_calibration({"horizons": {}})
    assert "actual coverage (how often it held)</text>" in svg and "rotate(-90" in svg
    assert rule_html.coin_note([0.52, 0.58]).endswith("the 95% interval excludes 50%")
    assert rule_html.coin_note([0.48, 0.55]).endswith("the 95% interval includes 50%")
    assert rule_html.coin_note(None) == "a coin flip is 50%"


def test_binomial_and_wilson():
    assert replay_statistics.binom_p_two_sided(50, 100) == pytest.approx(1.0)
    assert replay_statistics.binom_p_two_sided(60, 100) == pytest.approx(0.056887, abs=1e-5)
    assert replay_statistics.binom_p_two_sided(0, 10) == pytest.approx(2 / 1024)
    lo, hi = replay_statistics.wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-4) and hi == pytest.approx(0.5962, abs=1e-4)
    # clustered interval: perfectly correlated blocks are as wide as the block count says
    v = np.repeat([1.0, 0.0] * 10, 5)
    lo_c, hi_c = replay_statistics.clustered_ci(v, np.repeat(np.arange(20), 5))
    lo_i, hi_i = replay_statistics.wilson(50, 100)
    assert hi_c - lo_c > hi_i - lo_i


def test_rsi_and_returns_match_indicators():
    rng = np.random.default_rng(3)
    c = pd.Series(fat_tailed_walk(rng, 300, 100, 0.02), index=pd.bdate_range("2024-01-01", periods=300))
    r = inputs.rsi_series(c)
    for i in (14, 15, 40, 150, 299):
        assert r.iloc[i] == pytest.approx(ind.rsi(c.iloc[:i + 1]), abs=1e-9)
    assert math.isnan(r.iloc[13])
    up = pd.Series(np.arange(1.0, 40.0))
    assert inputs.rsi_series(up).iloc[-1] == ind.rsi(up) == 100.0
