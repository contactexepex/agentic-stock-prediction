"""UX3: the "why" of each paper trade and what the system learns (scripts/marketbrief/warehouse/trade_why.py), on an
in-memory DuckDB: every read is as of the cut-off (no look-ahead), the first computation of a check counts, notes and
lessons only once written, the next weekly review's time, and the lifecycle page's additions."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import trade_why  # noqa: E402

CUTOFF = datetime.fromisoformat("2026-10-12T10:00:00+00:00")


class Ctx:
    """The parts of a BuildContext trade_why reads."""

    def __init__(self, con, cutoff=CUTOFF):
        self.con, self.cutoff_time, self.market = con, cutoff, "india"
        self.collected = frozenset({"LT", "ITC"})
        self._shared: dict = {}

    def shared(self, name, compute):
        if name not in self._shared:
            self._shared[name] = compute()
        return self._shared[name]


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute("""CREATE TABLE intraday_checks (id VARCHAR, ticker VARCHAR, session_date DATE, check_at TIMESTAMPTZ,
        computed_at TIMESTAMPTZ, ret_since_open DOUBLE, bench_ret DOUBLE, sector_ret DOUBLE, sector_source VARCHAR,
        beta DOUBLE, residual DOUBLE)""")
    day, check_1, check_2 = "2026-10-12", "2026-10-12T05:44:00Z", "2026-10-12T08:44:00Z"
    rows = [
        # id, ticker, session, check_at, computed_at, ret, bench, sector, beta, residual
        ("c1", "LT", day, check_1, "2026-10-12T05:50:00Z", -0.0186, -0.008, -0.0002, 1.45, -0.007),
        ("c1", "LT", day, check_1, "2026-10-12T06:30:00Z", -0.5, -0.5, -0.5, 1.0, -0.5),  # recomputed later: ignored
        ("c2", "LT", day, check_2, "2026-10-12T08:50:00Z", -0.0233, -0.0100, -0.0084, 1.45, -0.0088),
        ("c3", "LT", day, "2026-10-12T11:00:00Z", "2026-10-12T11:05:00Z", 0.01, 0.0, 0.0, 1.45, 0.01),  # late
        ("c4", "GONE", day, check_2, "2026-10-12T08:50:00Z", 0.0, 0.0, 0.0, 1.0, 0.0),  # not collected
    ]  # fmt: skip
    for r in rows:
        con.execute("INSERT INTO intraday_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sector_etf', ?, ?)", list(r))
    con.execute("""CREATE TABLE intraday_explanations (id VARCHAR, check_row_id VARCHAR, ticker VARCHAR,
        check_at TIMESTAMPTZ, text VARCHAR, cited_ids VARCHAR[], created_at TIMESTAMPTZ)""")
    notes = [
        ("e1", "c2", "LT", check_2, "LT fell with the market.", "2026-10-12T09:00:00Z"),
        ("e2", "c1", "LT", check_1, "Written after the cut-off.", "2026-10-12T12:00:00Z"),
    ]
    for n in notes:
        con.execute("INSERT INTO intraday_explanations VALUES (?, ?, ?, ?, ?, [], ?)", list(n))
    con.execute("""CREATE TABLE lessons (id VARCHAR, prediction_id VARCHAR, ticker VARCHAR, horizon_days INTEGER,
        lesson VARCHAR, written_at TIMESTAMPTZ, available_from TIMESTAMPTZ)""")
    lessons = [
        ("l1", "2026-10-08-LT-1d", "Market days dominate.", "2026-10-10T03:00:00Z", "2026-10-10T02:00:00Z"),
        ("l2", "2026-10-09-LT-1d", "Not yet usable.", "2026-10-12T03:00:00Z", "2026-10-12T11:00:00Z"),
    ]
    for lesson_id, prediction_id, text, written, available in lessons:
        con.execute(
            "INSERT INTO lessons VALUES (?, ?, 'LT', 1, ?, ?, ?)", [lesson_id, prediction_id, text, written, available]
        )
    return con


def test_checks_by_ticker_as_of_the_cut_off_first_computation_collected_only(con):
    rows = trade_why.checks_by_ticker(Ctx(con))
    assert list(rows) == ["LT"]
    assert [r["check_at"] for r in rows["LT"]] == ["2026-10-12T05:44:00Z", "2026-10-12T08:44:00Z"]
    first, latest = rows["LT"]
    assert (first["move_pct"], first["market_pct"], first["own_pct"], first["beta"]) == (-1.86, -0.8, -0.7, 1.45)
    assert first["note"] is None  # its note was written after the cut-off
    assert (latest["move_pct"], latest["market_pct"], latest["sector_pct"], latest["own_pct"]) == (
        -2.33,
        -1.0,
        -0.84,
        -0.88,
    )
    assert latest["note"] == "LT fell with the market." and latest["sector_source"] == "sector_etf"


def test_open_why_is_the_latest_check_of_the_entry_session_or_later(con):
    ctx = Ctx(con)
    why = trade_why.open_why(ctx, "LT", "2026-10-12")
    assert set(why) == set(trade_why.WHY_KEYS) and why["source"] == "intraday_check"
    assert why["check_at"] == "2026-10-12T08:44:00Z" and why["note"] == "LT fell with the market."
    assert trade_why.open_why(ctx, "LT", "2026-10-13") is None  # entered after the latest check
    assert trade_why.open_why(ctx, "ITC", "2026-10-12") is None and trade_why.open_why(ctx, "LT", None) is None


def test_lessons_only_once_written_and_available(con):
    assert [row["id"] for row in trade_why.lessons(Ctx(con))] == ["l1"]
    later = Ctx(con, datetime.fromisoformat("2026-10-12T12:00:00+00:00"))
    assert [row["id"] for row in trade_why.lessons(later)] == ["l1", "l2"]


@pytest.mark.parametrize(
    ("cutoff", "expected"),
    [
        ("2026-10-12T10:00:00+00:00", "2026-10-16T23:30:00Z"),  # Monday: this Friday, 19:30 EDT
        ("2026-10-16T23:00:00+00:00", "2026-10-16T23:30:00Z"),  # Friday before 19:30 New York
        ("2026-10-16T23:30:00+00:00", "2026-10-23T23:30:00Z"),  # at the review: the next week's
        ("2026-11-02T10:00:00+00:00", "2026-11-07T00:30:00Z"),  # after the switch to EST
    ],
)
def test_next_review_is_friday_1930_new_york(cutoff, expected):
    assert trade_why.next_review_at(datetime.fromisoformat(cutoff)) == expected


def test_settled_why_and_prediction_fields(monkeypatch, con):
    ctx = Ctx(con)
    monkeypatch.setattr(trade_why, "ai_reasons", lambda _ctx: {"t1": "The market fell."})
    monkeypatch.setattr(
        trade_why, "predictions", lambda _ctx: {"p1": {"direction": "up", "prob_up": 0.55, "reason": "Orders."}}
    )
    why = trade_why.settled_why(ctx, {"trade_id": "t1", "exit_date_actual": "2026-10-13", "move_pct": -1.234,
                                      "market_pct": -1.0, "sector_pct": None, "news_pct": 0.1, "company_pct": -0.334,
                                      "reason_code": "market"})  # fmt: skip
    assert why["source"] == "settlement" and why["session_date"] == "2026-10-13"
    assert (why["move_pct"], why["company_pct"], why["ai_reason"], why["check_at"]) == (
        -1.23,
        -0.33,
        "The market fell.",
        None,
    )
    assert trade_why.prediction_fields(ctx, "p1") == {"direction": "up", "prob_up": 0.55, "reason": "Orders."}
    assert trade_why.prediction_fields(ctx, None) == {"direction": None, "prob_up": None, "reason": None}


def test_lifecycle_additions_in_the_trade_window_with_the_forecaster_lessons(monkeypatch, con):
    ctx = Ctx(con)
    monkeypatch.setattr(trade_why, "predictions", lambda _ctx: {
        "ai.combined.opus.v1:2026-10-08-LT-1d": {"reason": "Calm market."},
        "base.always_up.v1:2026-10-08-LT-1d": {"reason": None},
    })  # fmt: skip
    page = {"predictions": [
        {"id": "ai.combined.opus.v1:2026-10-08-LT-1d", "strategy_id": "ai.combined.opus.v1", "exit_date": "2026-10-12"},
        {"id": "base.always_up.v1:2026-10-08-LT-1d", "strategy_id": "base.always_up.v1", "exit_date": "2026-10-12"},
    ]}  # fmt: skip
    extra = trade_why.lifecycle_additions(ctx, "LT", "2026-10-12", page)
    assert [r["check_at"] for r in extra["checks_attribution"]] == ["2026-10-12T05:44:00Z", "2026-10-12T08:44:00Z"]
    assert "note" not in extra["checks_attribution"][0]
    assert extra["deviation_notes"] == [
        {"check_at": "2026-10-12T08:44:00Z", "session_date": "2026-10-12", "text": "LT fell with the market."}
    ]
    assert [row["id"] for row in extra["lessons"]] == ["l1"]  # the opus forecaster's prediction 2026-10-08-LT-1d
    assert extra["prediction_reasons"] == [
        {"prediction_id": "ai.combined.opus.v1:2026-10-08-LT-1d", "reason": "Calm market."}
    ]
    older = trade_why.lifecycle_additions(ctx, "LT", "2026-10-13", {"predictions": []})
    assert older["checks_attribution"] == [] and older["lessons"] == []
