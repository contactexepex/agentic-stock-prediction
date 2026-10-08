"""B8 assistant (docs/SPEC.md F11, docs/ws/b8.md): web/lib/assistant/app.sql creates the conversation log, and every
statement of web/lib/assistant/sql.ts runs on DuckDB with the parameters store.ts sends: the budget reservation
refuses a question over the day's or the month's cap, spend counts real costs over reservations, the kill switch reads
B5's inbox.controls, and the 90-day purge. Offline (local DuckDB)."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
APP_SQL = REPO / "web" / "lib" / "assistant" / "app.sql"
SQL_TS = REPO / "web" / "lib" / "assistant" / "sql.ts"
INBOX_SQL = REPO / "mcp" / "inbox.sql"
DAY = "2026-10-07T00:00:00Z"
MONTH = "2026-10-01T00:00:00Z"


def statements() -> dict[str, str]:
    return dict(re.findall(r"^\s+(\w+): `([^`]*)`,$", SQL_TS.read_text(encoding="utf-8"), flags=re.M))


def database() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    con.execute(APP_SQL.read_text(encoding="utf-8"))
    return con


def reserve(con, question_id: str, at: str, reserved: float = 0.1, day_usd: float = 0.65, month_usd: float = 20.0,
            market: str = "us") -> list:
    """The reserve statement with store.ts's parameter order."""
    return con.execute(statements()["reserve"], [question_id, market, "dashboard", "dashboard:owner", "assistant",
                                                 "Why?", None, None, at, reserved, DAY, MONTH, day_usd,
                                                 month_usd]).fetchall()


def answer(con, question_id: str, cost: float, status: str = "answered") -> None:
    con.execute(statements()["answer"], [question_id, status, "Text.", '[{"id": "x-1", "kind": "news"}]', "[]", False,
                                         None, "claude-sonnet-5-5", 1000, 0, 0, 200, 2, 1, cost,
                                         "2026-10-07T10:00:05Z"])


def test_every_statement_is_listed():
    assert sorted(statements()) == ["answer", "enabled", "list", "purgeAnswers", "purgeQuestions", "reserve", "spend"]


def test_app_sql_is_idempotent():
    con = database()
    con.execute(APP_SQL.read_text(encoding="utf-8"))
    tables = con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'app' ORDER BY 1").fetchall()
    assert tables == [("assistant_answers",), ("assistant_questions",)]


def test_reservation_enforces_the_day_cap_and_counts_real_costs():
    con, sql = database(), statements()
    for n in range(6):
        assert reserve(con, f"q{n}", f"2026-10-07T10:0{n}:00Z") == [(f"q{n}",)]
    # six reservations of $0.10 = $0.60; a seventh would pass $0.65
    assert reserve(con, "q6", "2026-10-07T10:06:00Z") == []
    assert [round(v, 6) for v in con.execute(sql["spend"], [DAY, MONTH]).fetchall()[0]] == [0.6, 0.6]
    answer(con, "q0", 0.02)
    answer(con, "q1", 0.03)
    day, month = con.execute(sql["spend"], [DAY, MONTH]).fetchall()[0]
    assert round(day, 6) == 0.45 and round(month, 6) == 0.45
    assert reserve(con, "q6", "2026-10-07T10:06:00Z") == [("q6",)]
    # $0.45 + $0.10 + $0.10 = $0.65 exactly is still allowed (float sums get 1e-9)
    assert reserve(con, "q7", "2026-10-07T10:07:00Z") == [("q7",)]
    # the next UTC day starts empty, the month keeps counting
    assert round(con.execute(sql["spend"], ["2026-10-08T00:00:00Z", MONTH]).fetchall()[0][0], 6) == 0.0
    # a repeated id is not inserted twice
    assert reserve(con, "q7", "2026-10-07T10:08:00Z", reserved=0.0) == []


def test_reservation_enforces_the_month_cap():
    con = database()
    con.execute("INSERT INTO app.assistant_questions VALUES ('old', 'us', 'slack', 'slack:U1', 'assistant', 'q', NULL, "
                "NULL, '2026-10-03T10:00:00Z', 0.1)")
    answer(con, "old", 19.95)
    assert reserve(con, "new", "2026-10-07T10:00:00Z") == []
    assert reserve(con, "free", "2026-10-07T10:00:00Z", reserved=0.0) == [("free",)]


def test_list_joins_answers_and_purge_keeps_90_days():
    con, sql = database(), statements()
    reserve(con, "a", "2026-10-07T09:00:00Z")
    reserve(con, "b", "2026-10-07T09:30:00Z")
    reserve(con, "c", "2026-10-07T09:10:00Z", market="india")
    answer(con, "a", 0.02)
    rows = con.execute(sql["list"], ["us", "2026-07-09T10:00:00Z", 100]).fetchall()
    assert [row[0] for row in rows] == ["b", "a"]
    b, a = rows
    assert b[5] is None and b[11] == 0.1  # no answer yet: status null, cost = the reservation
    assert a[5] == "answered" and a[9] is False and a[11] == 0.02
    assert a[7] == '[{"id": "x-1", "kind": "news"}]'
    con.execute("INSERT INTO app.assistant_questions VALUES ('gone', 'us', 'slack', 'slack:U1', 'assistant', 'q', NULL, "
                "NULL, '2026-07-01T10:00:00Z', 0.1)")
    answer(con, "gone", 0.01)
    con.execute(sql["purgeAnswers"], ["2026-07-09T10:00:00Z"])
    con.execute(sql["purgeQuestions"], ["2026-07-09T10:00:00Z"])
    assert con.execute("SELECT id FROM app.assistant_questions ORDER BY id").fetchall() == [("a",), ("b",), ("c",)]
    assert con.execute("SELECT id FROM app.assistant_answers").fetchall() == [("a",)]


def test_kill_switch_reads_the_newest_controls_row():
    con, sql = database(), statements()
    assert con.execute(sql["enabled"], ["assistant"]).fetchall() == [(None,)]
    con.execute("INSERT INTO inbox.controls VALUES ('assistant', false, 'stop', '2026-10-07T09:00:00Z')")
    assert con.execute(sql["enabled"], ["assistant"]).fetchall() == [(False,)]
    con.execute("INSERT INTO inbox.controls VALUES ('assistant', true, 'on', '2026-10-07T09:30:00Z')")
    assert con.execute(sql["enabled"], ["assistant"]).fetchall() == [(True,)]
    con.execute("INSERT INTO inbox.controls VALUES ('*', false, 'all off', '2026-10-07T09:40:00Z')")
    assert con.execute(sql["enabled"], ["assistant"]).fetchall() == [(False,)]
