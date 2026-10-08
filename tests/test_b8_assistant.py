"""B8 assistant (docs/SPEC.md F11, docs/ws/b8.md): web/lib/assistant/app.sql creates the conversation log, and every
statement of web/lib/assistant/sql.ts runs on DuckDB with the parameters store.ts sends: the question log, the spend
of the logged answers (shown, never enforced: owner decision 2026-10-08), conversations, the kill switch read from
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


def ask(con, question_id: str, at: str, market: str = "us", conversation: str | None = None,
        actor: str = "dashboard:owner") -> None:
    """The ask statement with store.ts's parameter order."""
    con.execute(statements()["ask"], [question_id, market, "dashboard", actor, "assistant", f"Why {question_id}?", None,
                                      None, at, conversation or question_id])


def answer(con, question_id: str, cost: float, status: str = "answered") -> None:
    con.execute(statements()["answer"], [question_id, status, "Text.", '[{"id": "x-1", "kind": "news"}]', "[]", False,
                                         None, "claude-sonnet-5-5", 1000, 0, 0, 200, 2, 1, cost,
                                         "2026-10-07T10:00:05Z"])


def test_every_statement_is_listed():
    assert sorted(statements()) == ["answer", "ask", "enabled", "history", "latestConversation", "list", "owns",
                                    "purgeAnswers", "purgeQuestions", "spend"]


def test_app_sql_is_idempotent():
    con = database()
    con.execute(APP_SQL.read_text(encoding="utf-8"))
    tables = con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'app' ORDER BY 1").fetchall()
    assert tables == [("assistant_answers",), ("assistant_questions",)]


def test_spend_sums_the_logged_answers_per_utc_day_and_month():
    con, sql = database(), statements()
    for n in range(9):
        ask(con, f"q{n}", f"2026-10-07T10:0{n}:00Z")
    ask(con, "q8", "2026-10-07T10:09:00Z")  # a repeated id is not inserted twice
    assert con.execute("SELECT count(*) FROM app.assistant_questions").fetchall() == [(9,)]
    assert con.execute(sql["spend"], [DAY, MONTH]).fetchall() == [(0, 0)]
    answer(con, "q0", 0.02)
    answer(con, "q1", 0.03)
    ask(con, "old", "2026-10-03T10:00:00Z")
    answer(con, "old", 19.95)
    day, month = con.execute(sql["spend"], [DAY, MONTH]).fetchall()[0]
    assert round(day, 6) == 0.05 and round(month, 6) == 20.0
    # no cap: a question is still logged with more than $20 spent this month
    ask(con, "q9", "2026-10-07T10:30:00Z")
    assert con.execute("SELECT count(*) FROM app.assistant_questions WHERE id = 'q9'").fetchall() == [(1,)]
    assert round(con.execute(sql["spend"], ["2026-10-08T00:00:00Z", MONTH]).fetchall()[0][0], 6) == 0.0


def test_list_joins_answers_and_purge_keeps_90_days():
    con, sql = database(), statements()
    ask(con, "a", "2026-10-07T09:00:00Z")
    ask(con, "b", "2026-10-07T09:30:00Z")
    ask(con, "c", "2026-10-07T09:10:00Z", market="india")
    answer(con, "a", 0.02)
    rows = con.execute(sql["list"], ["us", "2026-07-09T10:00:00Z", 100]).fetchall()
    assert [row[0] for row in rows] == ["b", "a"]
    b, a = rows
    assert b[5] == "b"  # conversation_id
    assert b[6] is None and b[12] == 0  # no answer yet: status null, no logged cost
    assert a[6] == "answered" and a[10] is False and a[12] == 0.02
    assert a[8] == '[{"id": "x-1", "kind": "news"}]'
    ask(con, "gone", "2026-07-01T10:00:00Z")
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


def test_conversation_statements():
    con, sql = database(), statements()
    ask(con, "c1", "2026-10-07T09:00:00Z")
    for n, at in ((2, "09:05"), (3, "09:10"), (4, "09:15"), (5, "09:20"), (6, "09:25")):
        ask(con, f"c{n}", f"2026-10-07T{at}:00Z", conversation="c1")
    ask(con, "x1", "2026-10-07T09:30:00Z", actor="slack:U1")
    for n in range(1, 6):
        answer(con, f"c{n}", 0.0, status="not_in_data" if n == 2 else "answered")
    answer(con, "c6", 0.0, status="failed")
    assert con.execute(sql["owns"], ["c1", "dashboard:owner", "us"]).fetchall() == [(1,)]
    assert con.execute(sql["owns"], ["c1", "slack:U1", "us"]).fetchall() == [(0,)]
    assert con.execute(sql["owns"], ["c1", "dashboard:owner", "india"]).fetchall() == [(0,)]
    # the newest 4 finished turns (the failed c6 is left out), newest first; the store reverses them
    rows = con.execute(sql["history"], ["c1", "dashboard:owner", "us", 4]).fetchall()
    assert [row[0] for row in rows] == ["c5", "c4", "c3", "c2"]
    assert rows[0][2] == "Why c5?" and rows[0][3] == "Text."
    assert con.execute(sql["history"], ["c1", "slack:U1", "us", 4]).fetchall() == []
    latest = con.execute(sql["latestConversation"], ["dashboard:owner", "us", "2026-10-07T09:20:00Z"]).fetchall()
    assert latest == [("c1",)]
    assert con.execute(sql["latestConversation"], ["dashboard:owner", "us", "2026-10-07T09:26:00Z"]).fetchall() == []
    assert con.execute(sql["latestConversation"], ["slack:U1", "us", "2026-10-07T09:00:00Z"]).fetchall() == [("x1",)]


def test_app_sql_upgrades_the_batch_1_tables():
    """main's batch-1 app.sql (with the reservation column, without conversation_id) run first, then this one."""
    con = duckdb.connect()
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    con.execute("CREATE SCHEMA app; CREATE TABLE app.assistant_questions (id VARCHAR PRIMARY KEY, market VARCHAR NOT NULL, "
                "channel VARCHAR NOT NULL, actor VARCHAR NOT NULL, agent VARCHAR NOT NULL, question VARCHAR NOT NULL, "
                "ticker VARCHAR, strategy_id VARCHAR, asked_at TIMESTAMPTZ NOT NULL, reserved_usd DOUBLE NOT NULL)")
    con.execute("INSERT INTO app.assistant_questions VALUES ('old', 'us', 'slack', 'slack:U1', 'assistant', 'q', NULL, NULL, "
                "'2026-10-07T09:00:00Z', 0.1)")
    con.execute(APP_SQL.read_text(encoding="utf-8"))
    columns = [row[0] for row in con.execute("DESCRIBE app.assistant_questions").fetchall()]
    assert "reserved_usd" not in columns and columns[-1] == "conversation_id"
    ask(con, "new", "2026-10-07T10:00:00Z")
    sql = statements()
    assert con.execute(sql["latestConversation"], ["slack:U1", "us", "2026-10-07T00:00:00Z"]).fetchall() == [("old",)]
    assert [r[0] for r in con.execute(sql["list"], ["us", "2026-07-01T00:00:00Z", 10]).fetchall()] == ["new", "old"]
