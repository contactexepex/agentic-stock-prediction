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
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.warehouse import openapi_spec, rm_compare, rm_strategies, rm_track_record, schema_check  # noqa: E402
from test_api_contract import CUTOFF, catalogue, example_context  # noqa: E402

MARKETS = ("india", "us")
REPO = Path(__file__).resolve().parents[1]
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


# ---------- Rule vs AI (rm.compare) against the mockup, built from the catalogue's example kinds ----------
KIND_FILES = {
    "cost_views": "cost_view.json",
    "head_to_head_picks": "head_to_head_pick.json",
    "trade_reasons_ai": "reason_ai.json",
    "eod_analyses": "eod_analysis.json",
    "research_reviews": "research_review.json",
    "news_impact": "news_impact.json",
}
MOCKUP_06 = Path(__file__).resolve().parents[1] / "design/mockups/06-rule-vs-ai/data.json"


def example_kinds(market: str):
    """An in-memory DuckDB holding the catalogue's example rows of the lab kinds (columns of core/schemas.py)."""
    con = duckdb.connect()
    for kind, name in KIND_FILES.items():
        columns = SCHEMAS[kind][1]
        con.execute(f"CREATE TABLE {kind} ({', '.join(f'{c} {t}' for c, t in columns.items())})")
        for record in catalogue(name):
            if record["market"] == market:
                values = [
                    json.dumps(record[c]) if t == "JSON" and record[c] is not None else record[c]
                    for c, t in columns.items()
                ]
                con.execute(f"INSERT INTO {kind} VALUES ({', '.join('?' * len(columns))})", values)
    return con


def compare_context(market: str):
    ctx = lab_context(market)
    ctx.con = example_kinds(market)
    ctx.__dict__["collected"] = frozenset(c["ticker"] for c in catalogue("company.json") if c["market"] == market)
    return ctx


def zulu(value):
    """Times as ISO UTC with a Z (the page's form; the mockup copies some as +00:00)."""
    return json.loads(json.dumps(value).replace("+00:00", "Z"))


@pytest.mark.parametrize("market", MARKETS)
def test_rule_vs_ai_records_are_the_mockups(market):
    ctx = compare_context(market)
    mockup = json.loads(MOCKUP_06.read_text())["markets"][market]
    built = {
        "trades": rm_compare.head_to_head_trades(ctx),
        "your_costs": rm_compare.your_costs(ctx),
        "picks": rm_compare.picks(ctx),
        "reasons": rm_compare.reasons(ctx),
        "eod": rm_compare.eod_analyses(ctx),
        "reviews": rm_compare.reviews(ctx),
        "rows": rm_compare.head_to_head_rows(ctx),
    }
    for key, records in built.items():
        assert canonical(records) == canonical(zulu(mockup[key])), key
    assert [r["created_at"] for r in built["reasons"]] == sorted(
        (r["created_at"] for r in built["reasons"]), reverse=True
    )
    # the W41 reviews (written 10 Oct) are after the cut-off and never read
    assert [r["iso_week"] for r in built["reviews"]] == ["2026-W40"]
    assert (
        rm_compare.review_due(ctx, built["reviews"])
        == mockup["review_due"]
        == {
            "date": "2026-10-10",
            "iso_week": "2026-W41",
        }
    )


def test_review_due_moves_past_a_week_already_reviewed():
    ctx = compare_context("us")
    ctx.cutoff_time = datetime.fromisoformat("2026-10-10T18:00:00+00:00")  # Saturday, after the W41 review
    assert rm_compare.review_due(ctx, [{"iso_week": "2026-W41"}]) == {"date": "2026-10-17", "iso_week": "2026-W42"}
    assert rm_compare.review_due(ctx, []) == {"date": "2026-10-10", "iso_week": "2026-W41"}


# ---------- populated records against the contract (the stored data has no settled trade yet) ----------
def schema_errors(records: list[dict], name: str) -> list[str]:
    document = openapi_spec.spec()
    return [
        e for record in records for e in schema_check.errors(record, {"$ref": f"#/components/schemas/{name}"}, document)
    ]


@pytest.mark.parametrize("market", MARKETS)
def test_example_records_validate_against_the_page_schemas(market):
    lab = lab_context(market)
    ctx = compare_context(market)
    checks = {
        "ScoreboardRow": rm_strategies.scoreboard_rows(lab),
        "HeatmapCell": rm_strategies.heatmaps(lab)["cells"],
        "CumulativeLine": rm_strategies.heatmaps(lab)["lines"],
        "HeadToHeadTrade": rm_compare.head_to_head_trades(ctx),
        "YourCostRow": rm_compare.your_costs(ctx),
        "HeadToHeadPick": rm_compare.picks(ctx),
        "AiReason": rm_compare.reasons(ctx),
        "EodAnalysis": rm_compare.eod_analyses(ctx),
        "ResearchReview": rm_compare.reviews(ctx),
    }
    for name, records in checks.items():
        assert records, name
        assert schema_errors(records, name) == [], name
    body = json.loads((REPO / "design/catalogue/scoreboard_backtest_row.json").read_text())
    backtest = [rm_strategies.backtest_row(r) for r in body["records"] if r["market"] == market]
    assert backtest and schema_errors(backtest, "ScoreboardRow") == []


# ---------- batch 2: per-strategy and per-company pages, rm.review (B5's read tools) ----------
def test_every_strategy_has_its_page_with_its_own_rows():
    ctx = lab_context("us")
    ctx.memo["b13_backtest"] = {"run": {}, "rows": []}
    ctx.memo["status_block"] = {"session": {"session_date": "2026-10-07"}}
    entries = rm_strategies.rm_common.strategies(ctx)
    pages = {sid: rm_strategies.strategy_page(ctx, sid, entry) for sid, entry in entries.items()}
    assert len(pages) == 15
    reference = pages["rule.model_news.v1"]
    expected = [
        r for r in catalogue("scoreboard_row.json") if r["market"] == "us" and r["strategy_id"] == "rule.model_news.v1"
    ]
    assert canonical(reference["rows"]) == canonical(expected)
    accuracy_all = next(
        r for r in expected if r["scope"] == "strategy" and r["view"] == "accuracy" and r["horizon_days"] == "all"
    )
    assert reference["go_live"] == accuracy_all["go_live"]
    assert reference["cells"] and all(c["strategy_id"] == "rule.model_news.v1" for c in reference["cells"])
    assert reference["lines"] and all(line["series"] == "rule.model_news.v1" for line in reference["lines"])
    traded = {r["strategy_id"] for r in catalogue("scoreboard_row.json") if r["market"] == "us"}
    for sid, page in pages.items():  # a strategy without trades: an empty page, never a missing one
        if sid not in traded:
            assert page["rows"] == page["cells"] == page["lines"] == [] and page["go_live"] is None


def test_company_pages_cut_the_head_to_head_records_per_ticker():
    ctx = compare_context("us")
    page = rm_compare.company_page(ctx, "NVDA")
    assert page["trades"] and {t["ticker"] for t in page["trades"]} == {"NVDA"}
    assert {r["trade_id"] for r in page["your_costs"]} <= {t["trade_id"] for t in page["trades"]}
    assert page["picks"] and {p["ticker"] for p in page["picks"]} == {"NVDA"}
    assert page["cells"] and all(
        c["view"] == "head_to_head" and c["dimension"] == "company" and c["column"] == "NVDA" for c in page["cells"]
    )
    quiet = next(t for t in sorted(ctx.collected) if not any(x["ticker"] == t for x in rm_compare.picks(ctx)))
    empty = rm_compare.company_page(ctx, quiet)
    assert [empty[k] for k in ("cells", "trades", "your_costs", "picks", "reasons")] == [[]] * 5


def test_a_deleted_company_has_no_picks_reasons_or_page(monkeypatch):
    ctx = compare_context("us")
    assert any(p["ticker"] == "NVDA" for p in rm_compare.picks(ctx))
    ctx = compare_context("us")
    ctx.__dict__["collected"] = ctx.collected - {"NVDA"}
    assert all(p["ticker"] != "NVDA" for p in rm_compare.picks(ctx))
    assert all(r["ticker"] != "NVDA" for r in rm_compare.reasons(ctx))
    ctx.memo.update(status_block={"session": {"session_date": "2026-10-07"}})
    for name in ("header", "horizons", "go_live"):
        monkeypatch.setattr(rm_compare.rm_common, name, lambda _c: {})
    monkeypatch.setattr(rm_compare, "companies", lambda _c, _f: [])
    pages = rm_compare.compare_pages(ctx)
    assert "NVDA" not in pages and sorted(pages) == sorted(["_", *ctx.collected])


def test_review_page_reads_reviews_and_the_newest_news_impact_week_by_the_cut_off():
    ctx = compare_context("us")
    ctx.__dict__["dashboard"] = {"as_of": EXAMPLE_AS_OF, "name": "United States", "currency": "USD"}
    page = rm_compare.review_pages(ctx)["_"]
    assert [r["iso_week"] for r in page["reviews"]] == ["2026-W40"]
    assert page["news_impact"] == []  # the W41 rows are computed on 10 Oct, after the cut-off
    later = compare_context("us")
    later.cutoff_time = datetime.fromisoformat("2026-10-10T18:00:00+00:00")
    rows = rm_compare.news_impact(later)
    assert rows and {r["iso_week"] for r in rows} == {"2026-W41"}
    assert schema_errors(rows, "NewsImpactRow") == []
    assert schema_errors(page["reviews"], "ResearchReview") == []
