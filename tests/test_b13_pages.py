"""B13's read models (docs/ws/b13.md): Strategy lab (rm.strategies) and Track record (rm.track_record). The
scoreboard rows, heatmap cells and cumulative lines equal W1's catalogue examples built with B2's engine from the
example trades; the back-test rows and run facts are B2's back-test in the catalogue's fields (a refused run keeps
its reason); the weekly call series keeps the scoring bases apart, reads only calls scored by the cut-off and
computes hit rate, Wilson interval and Brier per ISO week of the target date. The end-to-end contract check of both
pages on the synced stored data is tests/test_api_contract.py."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.analytics import scoring  # noqa: E402
from marketbrief.warehouse import rm_strategies, rm_track_record  # noqa: E402
from test_api_contract import CUTOFF, catalogue, example_context  # noqa: E402

MARKETS = ("india", "us")
EXAMPLE_AS_OF = "2026-10-06"  # the catalogue's scoreboard rows carry the examples' as-of date


def lab_context(market: str):
    ctx = example_context(market)
    ctx.__dict__["dashboard"] = {"as_of": EXAMPLE_AS_OF}
    return ctx


def canonical(records: list[dict]) -> list[str]:
    return sorted(json.dumps(record, sort_keys=True) for record in records)


@pytest.mark.parametrize("market", MARKETS)
def test_forward_rows_are_the_catalogues_scoreboard_rows(market):
    rows = rm_strategies.scoreboard_rows(lab_context(market))
    expected = [r for r in catalogue("scoreboard_row.json") if r["market"] == market]
    assert canonical(rows) == canonical(expected)
    assert rows == sorted(rows, key=rm_strategies.row_order)
    assert all(("go_live" in r) == (r["scope"] == "strategy") for r in rows)


@pytest.mark.parametrize("market", MARKETS)
def test_heatmap_cells_and_lines_are_the_catalogues(market):
    data = rm_strategies.heatmaps(lab_context(market))
    assert data["cells"] == [c for c in catalogue("heatmap_cell.json") if c["market"] == market]
    assert data["lines"] == [c for c in catalogue("cumulative_line.json") if c["market"] == market]


def test_backtest_rows_and_run_in_the_catalogues_fields(monkeypatch):
    body = json.loads(
        (Path(__file__).resolve().parents[1] / "design/catalogue/scoreboard_backtest_row.json").read_text()
    )
    records = [r for r in body["records"] if r["market"] == "india"]
    run = body["runs"]["india"]
    engine_rows = [{**r, "as_of": "2026-10-07T12:00:00+00:00", "go_live": {"proven": False}} for r in records]
    result = {
        "market": "india",
        "basis": "backtest",
        "splice": None,
        "rows": engine_rows,
        **{k: run[k] for k in ("history", "first_date", "last_date", "eurusd", "note")},
    }
    monkeypatch.setattr(rm_strategies.lab_reports, "run_backtest", lambda *_a, **_k: result)
    tested = rm_strategies.backtest(lab_context("india"))
    # no as_of, no go_live; pick rule, company and regime null (05-strategy-lab notes.md)
    expected = [{**r, "pick_rule": None, "ticker": None, "regime": None} for r in records]
    assert canonical(tested["rows"]) == canonical(expected)
    assert tested["run"] == {k: run[k] for k in rm_strategies.BACKTEST_RUN_FIELDS}


def test_a_refused_backtest_has_no_rows_and_says_why(monkeypatch):
    message = "no stored EURUSD bars to convert the BUX order fee"
    monkeypatch.setattr(rm_strategies.lab_reports, "run_backtest", lambda *_a, **_k: {"ok": False, "message": message})
    tested = rm_strategies.backtest(lab_context("us"))
    assert tested == {
        "rows": [],
        "run": {"history": False, "first_date": None, "last_date": None, "eurusd": None, "note": message},
    }


def test_strategy_lab_page_pools_no_bases_and_opens_on_all(monkeypatch):
    ctx = lab_context("india")
    ctx.memo.update(status_block={"session": {"session_date": "2026-10-07"}, "market": "india"})
    monkeypatch.setattr(rm_strategies.rm_common, "header", lambda _c: {"market": "india"})
    monkeypatch.setattr(rm_strategies, "companies", lambda _c: [])
    ctx.memo["b13_backtest"] = {"run": {"history": False}, "rows": []}
    page = rm_strategies.strategy_lab_pages(ctx)["_"]
    assert page["default_horizon"] == "all" and page["horizons"] == [1, 2, 3, 4, 5]
    assert page["bases"] == ["forward"]
    assert page["reference_strategy"] == "rule.model_news.v1"
    assert len(page["strategies"]) == 15


CALLS = [  # id, scored_at, label_basis, horizon_label, target_date, confidence, hit
    ("a", "2026-09-29T02:00:00Z", "close_to_close", "legacy_cc", "2026-09-28", 0.6, True),
    ("b", "2026-09-30T02:00:00Z", "close_to_close", "legacy_cc", "2026-09-29", 0.7, False),
    ("c", "2026-10-06T02:00:00Z", "close_to_close", "legacy_cc", "2026-10-05", 0.55, True),
    ("d", "2026-10-06T22:00:00Z", "open_to_close", "n_plus_k", "2026-10-06", 0.6, True),
    ("e", "2026-10-08T02:00:00Z", "close_to_close", "legacy_cc", "2026-10-07", 0.8, False),  # after the cut-off
]


def calls_connection():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE track_record (id VARCHAR, scored_at TIMESTAMPTZ, label_basis VARCHAR, horizon_label VARCHAR, "
        "target_date DATE, confidence DOUBLE, hit BOOLEAN)"
    )
    con.executemany("INSERT INTO track_record VALUES (?, ?, ?, ?, ?, ?, ?)", CALLS)
    return con


def test_weekly_series_keeps_bases_apart_and_reads_only_scored_calls():
    series = rm_track_record.weekly_series(calls_connection(), datetime.fromisoformat(CUTOFF).isoformat())
    assert [(s["key"], [w["week"] for w in s["weeks"]]) for s in series] == [
        ("close_to_close", ["2026-W40", "2026-W41"]),
        ("open_to_close", ["2026-W41"]),
    ]
    first = series[0]["weeks"][0]
    low, high = scoring.wilson(1, 2)
    assert first == {
        "week": "2026-W40",
        "n": 2,
        "hits": 1,
        "share": 0.5,
        "wilson_lo": low,
        "wilson_hi": high,
        "brier": round((0.4**2 + 0.7**2) / 2, 4),
        "log_loss": first["log_loss"],
    }
    assert series[0]["weeks"][1]["n"] == 1  # call e (scored after the cut-off) is left out
    assert series[1]["label"] and series[1]["basis"] == "open_to_close"


def test_weekly_series_is_empty_without_scored_calls():
    con = calls_connection()
    con.execute("DELETE FROM track_record")
    assert rm_track_record.weekly_series(con, CUTOFF) == []
