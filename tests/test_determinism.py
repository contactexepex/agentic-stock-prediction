"""Queries whose row order or float aggregates reach stored data or published text give the same
result on every run under DuckDB's multi-threading (docs/REFACTOR_PLAN.md, "Known nondeterminism",
fixed). The data is built to expose order: many day files (DuckDB scans files in parallel), many
rows with equal sort keys (a ticker's 1d and 5d calls of one day, equal trade values), confidences,
percentages and dollar values whose float sum depends on the order of addition, and a ticker with
three split factors. Each query runs RUNS times on each of CONNECTIONS connections with THREADS threads,
and every run must equal the first."""
from __future__ import annotations

import json
from fractions import Fraction
import random
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.storage import append_jsonl  # noqa: E402
from marketbrief.utils.markdown import cursor_markdown_table  # noqa: E402
from marketbrief.pipeline import context  # noqa: E402
import html_report  # noqa: E402
from marketbrief.presentation.report import gather, report_parts  # noqa: E402
from marketbrief.pipeline import score_predictions  # noqa: E402
from marketbrief.analytics import scoring  # noqa: E402
from marketbrief.analytics import smart_money  # noqa: E402
import view_data  # noqa: E402
from test_pipeline import MARKET, setup, weekdays  # noqa: E402

THREADS, CONNECTIONS, RUNS = 8, 3, 4   # 12 runs of each query
NOW = "2026-09-15T12:00:00+00:00"
DAYS = weekdays(date(2026, 7, 6), 50)
TICKERS = [f"T{i:02d}" for i in range(40)]
CONFIDENCES = (0.55, 0.6, 0.65, 0.7, 0.62, 0.58, 0.81, 0.73, 0.67, 0.51, 0.6, 0.6)
PCT_COLUMNS = ("is80_pct", "naive_is80_pct", "width80_pct", "naive_width80_pct", "center_err_pct",
               "naive_center_err_pct")


def jl(root: Path, kind: str, day: date, rows: list[dict], part: str = "") -> None:
    path = root / "data" / MARKET / kind / f"{day:%Y}" / f"{day:%m}" / f"{day}{part}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(path, rows)


def build(root: Path) -> None:
    rnd = random.Random(7)
    for i, d in enumerate(DAYS):   # one price file per session
        path = root / "data" / MARKET / "prices" / f"{d:%Y}" / f"{d:%m}" / f"{d}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["date,ticker,open,high,low,close,adj_close,volume,collected_at"]
        for k, t in enumerate(TICKERS):
            c = round(100 + k + i * 0.37 + rnd.uniform(-2, 2), 2)
            lines.append(f"{d},{t},{c},{c + 1},{c - 1},{c},{c},{1000 + k},{d}T21:00:00+00:00")
        path.write_text("\n".join(lines) + "\n")
    jl(root, "adjustments", DAYS[0], [   # three split factors on T00 after every bar: product order matters
        {"id": f"adj-T00-{n}", "ticker": "T00", "ex_date": str(DAYS[-1] + timedelta(days=n + 1)), "factor": f,
         "detected_at": f"{DAYS[-1]}T22:0{n}:00+00:00"} for n, f in enumerate((0.1, 0.3, 0.7))])
    n = 0
    for i, d in enumerate(DAYS[:40]):   # 80 calls a day; a ticker's 1d and 5d calls (same as_of and ticker)
        calls = []                       # are in two files, which DuckDB scans in parallel
        for t in TICKERS:
            for h in (1, 5):
                calls.append({"id": f"{d}-{t}-{h}d", "made_at": f"{d}T20:00:00+00:00", "as_of_date": str(d),
                              "ticker": t, "horizon_days": h, "direction": "up" if n % 3 else "down",
                              "confidence": CONFIDENCES[n % len(CONFIDENCES)], "evidence_ids": ["e"],
                              "prompt_version": "t", "range_widen": 0.0})
                n += 1
        for h in (1, 5):
            jl(root, "predictions", d, [c for c in calls if c["horizon_days"] == h], f".{h}d")
        ranges = [{"id": f"{d}-{t}-{h}d", "made_at": f"{d}T20:00:00+00:00", "as_of_date": str(d),
                   "session_date": str(d), "target_date": str(DAYS[i + h]), "ticker": t, "horizon_days": h,
                   "base_close": 100.0, "center": 0.0, "sigma_h": 0.02, "lo50": 98.0, "hi50": 102.0, "lo80": 96.0,
                   "hi80": 104.0, "naive_lo50": 98.5, "naive_hi50": 101.5, "naive_lo80": 97.0,
                   "naive_hi80": 103.0, "regime": "CALM"}
                  for t in TICKERS for h in (1, 5)]
        jl(root, "ranges", d, ranges)
        if i >= 25:   # the first 25 days are scored, in one outcome file per day; the rest stay open
            continue
        jl(root, "outcomes", DAYS[i + 6], [
            {"prediction_id": c["id"], "scored_at": f"{DAYS[i + 6]}T21:30:00+00:00", "base_date": str(d),
             "base_close": 100.0, "target_date": str(DAYS[i + c["horizon_days"]]), "target_close": 101.0,
             "actual_return": round(rnd.uniform(-0.05, 0.05), 6), "hit": rnd.random() < 0.55} for c in calls])
        jl(root, "range_outcomes", DAYS[i + 6], [
            {"range_id": r["id"], "scored_at": f"{DAYS[i + 6]}T21:30:00+00:00", "target_date": r["target_date"],
             "actual_close": 100.5, "z": 0.25, "hit50": k % 2 == 0, "hit80": k % 5 != 0, "naive_hit50": True,
             "naive_hit80": k % 3 != 0, **{c: rnd.uniform(0, 10) for c in PCT_COLUMNS}}
            for k, r in enumerate(ranges)])
    for d in DAYS[30:50]:   # Form 4 trades: equal values (ties) and fractional dollar values
        jl(root, "insiders", d, [
            {"id": f"f4-{d}-{k:03d}", "ticker": "AAPL", "insider_name": f"Insider {k % 5}", "role": "Officer",
             "code": "P" if k % 2 else "S", "derivative": False, "transaction_date": str(d), "shares": 10.0 + k % 3,
             "price": 12.345, "value": 5000.0 if k % 7 == 0 else round(rnd.uniform(10, 5000), 6),
             "plan_10b5_1": k % 4 == 0, "first_seen_at": f"{d}T22:00:00+00:00"} for k in range(100)])


@pytest.fixture(scope="module")
def cons(tmp_path_factory):
    """CONNECTIONS connections with THREADS threads on the built data (MB_NOW frozen)."""
    root, cfg = setup(tmp_path_factory.mktemp("determinism"))
    build(root)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(common, "ROOT", root)
        mp.setattr(common, "CONFIG", cfg)
        mp.setenv("MB_NOW", NOW)
        out = [connect(MARKET) for _ in range(CONNECTIONS)]
        for con in out:
            con.execute(f"SET threads TO {THREADS}")
        yield out


def stable(cons, fn) -> object:
    """fn(con) RUNS times on each connection; every result must equal the first. Returns it."""
    results = [fn(con) for _ in range(RUNS) for con in cons]
    assert all(r == results[0] for r in results[1:])
    return results[0]


def rows(sql: str, params=None):
    return lambda con: con.execute(sql, params or []).fetchall()


def section(title: str):
    sql, params = next((s, p) for t, s, p in context.sections(load_market(MARKET)) if t.startswith(title))
    return lambda con: cursor_markdown_table(con.execute(sql, params))


def test_score_predictions_queries(cons):
    calls = stable(cons, rows(score_predictions.SQL))
    assert len(calls) > 100 and [r[0] for r in calls] == sorted(r[0] for r in calls)
    stable(cons, rows(score_predictions.RANGE_SQL))


def test_scoring_summary(cons):
    s = stable(cons, lambda con: json.dumps(scoring.summary(con), sort_keys=True))
    rel = [r for r in json.loads(s)["calls"]["all"]["reliability"] if r["n"]]
    assert rel and all(r["mean_conf"] is not None for r in rel)


def test_scoring_mean_is_order_independent():
    values = [0.1, 0.7, 0.2, 0.6000000000000001, 0.3] * 7
    means = {scoring.exact_mean(random.Random(i).sample(values, len(values))) for i in range(50)}
    assert means == {float(sum(map(Fraction, values)) / len(values))}
    assert scoring.exact_mean([0.7] * 12) == 0.7 and scoring.exact_mean([0.55, 0.55, float("nan")]) == 0.55


def test_view_data_bands_and_scored_calls(cons):
    bands = stable(cons, rows(view_data.BANDS_SQL))
    assert [b[0] for b in bands] == sorted(b[0] for b in bands) and sum(b[1] for b in bands) > 200
    stable(cons, lambda con: con.execute(view_data.SCORED_CALLS_SQL).df().to_json())


def test_context_sections(cons):
    table = stable(cons, section("Open predictions"))
    lines = [line.split(" | ") for line in table.splitlines()[2:]]
    assert len(lines) > 100   # (as_of_date, ticker) ties broken by horizon, then id
    assert lines == sorted(lines, key=lambda c: (c[2], c[1], int(c[3]), c[0]))
    stable(cons, section("Track record by horizon"))
    stable(cons, section("Range scorecard"))


def test_report_queries(cons):
    stable(cons, rows(view_data.CONF_BANDS_SQL))
    stable(cons, rows(gather.SCORECARD_SQL))


def test_views_insider_flow_and_split_factors(cons):
    flow = stable(cons, rows("SELECT * FROM insider_flow ORDER BY ticker"))
    assert flow and flow[0][1] > 0
    stable(cons, rows("SELECT ticker, date, factor FROM bar_factors WHERE ticker = 'T00' ORDER BY date"))
    stable(cons, lambda con: cursor_markdown_table(con.execute(smart_money.SECTIONS[1][1])))


SHARES = (0.625, 5 / 8, 0.575, 0.125, 0.5499999999999999, 0.6250000000000001, 0.995, 0.005, 1.0, 0.0, 1e-7)


def test_percent_half_up_same_in_markdown_and_html():
    """The md report (scoring.percent) and the HTML report's JavaScript (pct0) print the same whole
    percent for every share, half up on its decimal value (0.625 and 5/8 -> 63%)."""
    assert scoring.percent(0.625) == scoring.percent(5 / 8) == "63%"
    assert report_parts.percent is scoring.percent and view_data.fmt_call("up", 0.625).endswith("63%")
    assert view_data.record_text(80, 50, "calls").endswith("(63%).")   # 50/80 = 0.625
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    line = next(x for x in (Path(html_report.__file__).read_text().splitlines()) if x.startswith("const pct0 ="))
    js = line.split("//")[0] + f"\nconsole.log(JSON.stringify({json.dumps(SHARES)}.map(pct0)));"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [scoring.percent(v) for v in SHARES]


def test_exact_decimal_sum_limits():
    """TRY_CAST(x AS DECIMAL(38,10)), used for order-independent sums and averages: values round to
    10 decimals before the sum; NaN, infinities and values of 1e28 or more become NULL and are left
    out of avg/sum (count(*) still counts their rows)."""
    con = duckdb.connect()
    con.execute("SET threads TO 8")
    vals = "(VALUES (0.1::DOUBLE), (0.2), ('nan'::DOUBLE), ('inf'::DOUBLE), (1e30), (0.30000000000000004))"
    row = con.execute(f"SELECT count(*), count(TRY_CAST(v AS DECIMAL(38,10))), avg(TRY_CAST(v AS DECIMAL(38,10))), "
                      f"CAST(sum(TRY_CAST(v AS DECIMAL(38,10))) AS DOUBLE) FROM {vals} t(v)").fetchone()
    assert row == (6, 3, 0.2, 0.6)


def test_no_half_to_even_percent_format_left():
    """Every printed share uses scoring.percent (half up): no Python ':.0%' format remains in scripts/,
    and the weekly review prints 0.625 and 5/8 as 63% like the daily report."""
    import re
    from marketbrief.pipeline.review import markdown_cells
    from marketbrief.pipeline.review import summaries
    scripts = Path(scoring.__file__).parent
    hits = [f"{p.relative_to(scripts)}:{i}" for p in sorted(scripts.rglob("*.py"))
            for i, line in enumerate(p.read_text().splitlines(), 1) if re.search(r"\{[^}]*:[+ ]?\.(0|\{[^}]+\})%\}", line)]
    assert hits == []
    assert summaries.band_label(0.625, 5 / 8) == "63%-63%" and markdown_cells.fpct(0.625) == markdown_cells.fpct(5 / 8) == "63%"
    assert scoring.percent(0.125, sign=True) == "+13%" and scoring.percent(float("inf")) == "–"
    assert scoring.percent(0.625, 1) == "62.5%" and scoring.percent(None) == "–"
