"""B5 tools and channels (docs/SPEC.md F10, section 10 row B5): the generated tool registry of web/lib/tools/ is current
with mcp/tools.yaml and mcp/agents/*.yaml, every agent respects the channel permissions, and the inbox of
mcp/inbox.sql matches the command_log schema and runs every statement of web/lib/tools/sql.ts. Offline (local DuckDB).
The web tier's own tests run with `npm test` in web/ (.github/workflows/web-tests.yml)."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import duckdb
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.constants.kinds import KIND_COMMAND_LOG  # noqa: E402
from marketbrief.core.schema_lifecycle import LIFECYCLE_SCHEMAS  # noqa: E402

SPEC = importlib.util.spec_from_file_location("build_registry", REPO / "mcp" / "build_registry.py")
build_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_registry)

SQL_TS = REPO / "web" / "lib" / "tools" / "sql.ts"
INBOX_SQL = REPO / "mcp" / "inbox.sql"
CHANNELS = ["dashboard", "slack", "claude_code", "claude_app"]


def statements() -> dict[str, str]:
    return dict(re.findall(r"^\s+(\w+): `([^`]*)`,$", SQL_TS.read_text(encoding="utf-8"), flags=re.M))


def inbox() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    return con


def test_generated_registry_is_current():
    assert build_registry.main(["--check"]) == 0


def test_agents_follow_tool_channels():
    tools = build_registry.load_tools()["tools"]
    agents = {agent["agent"]: agent for agent in build_registry.load_agents(tools, CHANNELS)}
    assert set(agents) == {"assistant", "claude-app", "dashboard", "slack-gateway"}
    kinds = {tool["name"]: tool["kind"] for tool in tools}
    assert [name for name, agent in agents.items() if "delete_company" in agent["tools"]] == ["dashboard"]
    assert not [name for name in agents["assistant"]["tools"] if kinds[name] == "write"]
    assert agents["slack-gateway"]["channels"] == ["slack"]
    assert agents["claude-app"]["channels"] == ["claude_app"]


def test_agent_checks_refuse_a_tool_its_channel_forbids():
    tools = {tool["name"]: tool for tool in build_registry.load_tools()["tools"]}
    agent = yaml.safe_load((REPO / "mcp" / "agents" / "slack-gateway.yaml").read_text(encoding="utf-8"))
    agent["tools"] = [*agent["tools"], "delete_company"]
    problems = build_registry.agent_problems(agent, "slack-gateway", tools, CHANNELS)
    assert problems == ["delete_company is not allowed in channel slack"]
    agent = dict(agent, tools=["add_company"], daily_write_budget=0)
    assert build_registry.agent_problems(agent, "slack-gateway", tools, ["slack"]) == [
        "write tools need a daily_write_budget above 0"]


def test_inbox_command_log_has_the_schema_columns():
    con = inbox()
    described = con.execute("DESCRIBE inbox.command_log").fetchall()
    _, columns = LIFECYCLE_SCHEMAS[KIND_COMMAND_LOG]
    assert [(name, kind) for name, kind, *_ in described] == [
        (name, "TIMESTAMP WITH TIME ZONE" if kind == "TIMESTAMPTZ" else kind) for name, kind in columns.items()]


WIRE_FIXTURE = REPO / "web" / "lib" / "tools" / "tests" / "inbox_wire.fixture.json"
COMPANY_KIND = "watchlist_events"


def compact(value) -> str:
    """JSON as motherduck.ts sends it (JSON.stringify: no spaces, key order kept)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def claim(con, row: dict, since: str = "2026-10-07T00:00:00Z", limit: int = 20) -> list:
    """Run the claim statement of web/lib/tools/sql.ts for one tool-layer row, with motherduck.ts's parameters."""
    sql = statements()
    preview = None if row["preview"] is None else compact(row["preview"])
    if row["kind"] == COMPANY_KIND:
        params = [row["inbox_id"], row["market"], row["tool"], compact(row["arguments"]), row["submitted_by"],
                  row["channel"], row["submitted_at"], row["command_id"], preview, row["agent"], row["args_sha256"],
                  since, limit, row.get("slack_channel"), row.get("slack_ts")]
        return con.execute(sql["claimCompany"], params).fetchall()
    params = [row["inbox_id"], row["kind"], row["tool"], row["market"], compact(row["arguments"]), preview,
              row["channel"], row["submitted_by"], row["agent"], row["command_id"], row["submitted_at"],
              row["args_sha256"], since, limit, row.get("slack_channel"), row.get("slack_ts")]
    return con.execute(sql["claimRequest"], params).fetchall()


def request_row(inbox_id: str, command_id: str, kind: str = COMPANY_KIND, at: str = "2026-10-07T10:00:00.000Z") -> dict:
    tool = "reactivate_company" if kind == COMPANY_KIND else "add_paper_trade"
    return {"inbox_id": inbox_id, "kind": kind, "tool": tool, "market": "us",
            "arguments": {"market": "us", "ticker": "AAPL"}, "preview": None, "channel": "slack",
            "submitted_by": "slack:U07ABCD123", "agent": "slack-gateway", "command_id": command_id,
            "submitted_at": at, "args_sha256": "f" * 64}


def test_inbox_statements_run_on_duckdb():
    sql = statements()
    assert set(sql) == {"usage", "claimCompany", "claimRequest", "existing", "append", "find"}
    con = inbox()
    assert claim(con, request_row("key-000001", "cmd-1")) == [("key-000001",)]
    assert claim(con, request_row("key-000001", "cmd-2")) == []
    assert claim(con, request_row("key-000001", "cmd-3", kind="portfolio_trades")) == [], "a key spans both tables"
    assert claim(con, request_row("key-000002", "cmd-4", kind="portfolio_trades")) == [("key-000002",)]
    assert claim(con, request_row("key-000002", "cmd-5")) == [], "a key spans both tables"
    assert con.execute(sql["existing"], ["key-000001"]).fetchall() == [
        ("key-000001", "reactivate_company", "slack:U07ABCD123", "cmd-1", "f" * 64)]
    assert con.execute(sql["existing"], ["key-000002"]).fetchall()[0][1] == "add_paper_trade"
    who = ["slack", "slack:U07ABCD123", "slack-gateway"]
    con.execute(sql["append"], ["cmd-1", "us", "2026-10-07T10:00:00.000Z", *who, "reactivate_company", "write",
                                json.dumps({"ticker": "AAPL"}), "key-000001", "pending", None, "Pending: ...",
                                json.dumps(["we-1"]), 19, "2026-10-07T10:00:01.000Z"])
    con.execute(sql["append"], ["cmd-2", "us", "2026-10-07T10:01:00.000Z", *who, "explain", "read_ai", "{}", None,
                                "accepted", None, None, "[]", None, "2026-10-07T10:01:00.000Z"])
    found = con.execute(sql["find"], ["cmd-1"]).fetchall()[0]
    assert json.loads(found[13]) == ["we-1"] and found[14] == 19 and found[10] == "pending"
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-07T00:00:00Z"]).fetchall() == [(2, 1, None)]
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-08T00:00:00Z"]).fetchall() == [(0, 0, None)]
    con.execute("INSERT INTO inbox.controls VALUES ('slack-gateway', false, 'stop', '2026-10-07T09:00:00Z'), "
                "('slack-gateway', true, 'go', '2026-10-07T09:30:00Z'), "
                "('*', false, 'all off', '2026-10-07T09:45:00Z')")
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-07T00:00:00Z"]).fetchall()[0][2] is False
    con.execute("INSERT INTO inbox.controls VALUES ('*', true, 'all on', '2026-10-07T09:50:00Z')")
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-07T00:00:00Z"]).fetchall()[0][2] is True


def test_inbox_sql_is_idempotent():
    con = inbox()
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    tables = con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'inbox' ORDER BY 1").fetchall()
    assert tables == [("command_log",), ("company_commands",), ("controls",), ("requests",)]


def test_read_model_statement_runs_on_duckdb():
    columns = re.search(r"READ_MODEL_COLUMNS = `([^`]*)`", SQL_TS.read_text(encoding="utf-8")).group(1)
    con = duckdb.connect()
    con.execute("CREATE SCHEMA rm; CREATE TABLE rm.home (market VARCHAR, page_key VARCHAR, as_of TIMESTAMPTZ, "
                "cutoff TIMESTAMPTZ, built_at TIMESTAMPTZ, schema_version VARCHAR, source_commit VARCHAR, "
                "payload_sha256 VARCHAR, payload JSON)")
    con.execute("INSERT INTO rm.home VALUES ('us', '_', '2026-10-07T01:00:00Z', NULL, NULL, '1', NULL, NULL, "
                "'{\"a\": 1}')")
    rows = con.execute(f"SELECT {columns} FROM rm.home WHERE market = $1 AND page_key = $2", ["us", "_"]).fetchall()
    assert len(rows) == 1 and json.loads(rows[0][8]) == {"a": 1}


@pytest.mark.parametrize("path", sorted((REPO / "mcp" / "agents").glob("*.yaml")), ids=lambda path: path.name)
def test_agent_files_use_plain_booleans(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r":\s*(yes|no|on|off)\s*(#|$)", text, flags=re.M | re.I)


def test_fixed_slack_channel_matches_settings():
    settings = yaml.safe_load((REPO / "config" / "settings.yaml").read_text(encoding="utf-8"))
    constants = (REPO / "web" / "lib" / "tools" / "constants.ts").read_text(encoding="utf-8")
    assert f'SLACK_CHANNEL_ID = "{settings["slack_channel_id"]}"' in constants


def test_claim_enforces_the_day_budget_across_both_tables():
    con = inbox()
    assert claim(con, request_row("key-000001", "cmd-1"), limit=2) == [("key-000001",)]
    assert claim(con, request_row("key-000002", "cmd-2", kind="portfolio_trades"), limit=2) == [("key-000002",)]
    assert claim(con, request_row("key-000003", "cmd-3"), limit=2) == [], "over budget"
    assert claim(con, request_row("key-000004", "cmd-4", kind="portfolio_trades"), limit=2) == [], "over budget"
    assert claim(con, request_row("key-000001", "cmd-5"), limit=2) == [], "existing key"
    next_day = request_row("key-000005", "cmd-6", at="2026-10-08T09:00:00.000Z")
    assert claim(con, next_day, since="2026-10-08T00:00:00Z", limit=2) == [("key-000005",)], "resets each UTC day"


def test_b1_imports_the_rows_the_tool_layer_writes(tmp_path, monkeypatch):
    """The wire: rows written by web/lib/tools (inbox_wire.fixture.json, checked by inbox_wire.test.ts) go through the
    real claim statements into a DuckDB file built from mcp/inbox.sql, and B1's import-inbox appends the company
    commands to data/ with the identity from the row; B2's portfolio reader finds the paper trade in inbox.requests and
    builds its trade input from the row (B2's own tests cover storing it)."""
    import common
    from marketbrief.lifecycle import inbox as b1_inbox
    from marketbrief.lifecycle.cli import main as company_cli
    from marketbrief.lifecycle.events import stored_events

    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setenv("MB_NOW", "2026-10-07T12:00:00+00:00")
    prices = tmp_path / "data" / "us" / "prices" / "2026" / "07" / "2026-07-01.csv"
    prices.parent.mkdir(parents=True)
    prices.write_bytes(b"date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"
                       b"2026-07-01,AAPL,1,1,1,1,1,1,2026-07-02T00:00:00+00:00\r\n")
    rows = json.loads(WIRE_FIXTURE.read_text(encoding="utf-8"))
    assert [row["tool"] for row in rows] == ["deactivate_company", "set_paper_amount", "add_company", "add_paper_trade"]
    path = tmp_path / "web_inbox.duckdb"   # not inbox.duckdb: the catalog would clash with schema inbox
    con = duckdb.connect(str(path))
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    for row in rows:
        assert claim(con, row) == [(row["inbox_id"],)]
    con.close()

    reader = b1_inbox.open_inbox(str(path))
    pending = b1_inbox.pending_rows(reader, "us")
    reader.close()
    assert sorted(row["tool"] for row in pending) == ["add_company", "deactivate_company", "set_paper_amount"]
    add = b1_inbox.request_of(next(row for row in pending if row["tool"] == "add_company"))
    assert (add["event"], add["ticker"], add["requested_by"], add["channel"], add["idempotency_key"]) == (
        "add", "MSFT", "slack:U07ABCD123", "slack", "wire-add-msft-01")
    # the add's onboarding needs B1's fixture sources (tests/test_lifecycle.py covers it)
    con = duckdb.connect(str(path))
    con.execute("DELETE FROM inbox.company_commands WHERE tool = 'add_company'")
    con.close()

    out = io.StringIO()
    with redirect_stdout(out):
        code = company_cli(["--market", "us", "import-inbox", "--inbox", str(path), "--skip-backfill"])
    result = json.loads(out.getvalue())
    by_tool = {item["tool"]: item for item in result["results"]}
    assert by_tool["deactivate_company"]["ok"] and by_tool["set_paper_amount"]["ok"], result
    events = {row["event"]: row for row in stored_events("us")}
    assert (events["deactivate"]["ticker"], events["deactivate"]["requested_by"], events["deactivate"]["channel"],
            events["deactivate"]["idempotency_key"], events["deactivate"]["command_id"]) == (
        "DAL", "slack:U07ABCD123", "slack", "wire-deact-dal-01", rows[0]["command_id"])
    assert (events["set_amount"]["ticker"], events["set_amount"]["amount"], events["set_amount"]["requested_by"],
            events["set_amount"]["channel"]) == ("AAPL", 1500.0, "github:owner-login", "claude_app")
    assert code == 0 and result["imported"] == 2 and "add_paper_trade" not in by_tool
    con = duckdb.connect(str(path), read_only=True)   # B6's onboarding reply reads these two after the import
    stored = con.execute("SELECT inbox_id, slack_channel, slack_ts FROM inbox.company_commands "
                         "ORDER BY inbox_id").fetchall()
    con.close()
    assert stored == [("wire-amount-aapl-01", None, None),
                      ("wire-deact-dal-01", "C0C6REB7QS2", "1791400000.000101")]

    # The paper trade: B2's reader (marketbrief/portfolio/inbox_import.py) finds the row and builds its trade input
    # with the row's identity, channel and key (B2's own tests cover validation and storing).
    from datetime import datetime, timezone

    from marketbrief.portfolio import inbox_import as b2_inbox
    reader = b1_inbox.open_inbox(str(path))
    trades = b2_inbox.pending_requests(reader, "us", datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
    reader.close()
    assert [row["inbox_id"] for row in trades] == ["wire-trade-aapl-01"]
    entry = b2_inbox.trade_input(trades[0], b2_inbox.arguments_of(trades[0]))
    assert (entry.ticker, entry.side, entry.quantity, str(entry.trade_date), entry.price_basis, entry.source,
            entry.idempotency_key, entry.submitted_by) == (
        "AAPL", "buy", 2, "2026-10-06", "close", "claude_app", "wire-trade-aapl-01", "github:owner-login")


def test_inbox_sql_adds_the_slack_columns_to_older_tables():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA inbox; CREATE TABLE inbox.company_commands (inbox_id VARCHAR PRIMARY KEY, "
                "market VARCHAR, tool VARCHAR, arguments JSON, actor VARCHAR, channel VARCHAR, "
                "submitted_at TIMESTAMPTZ, command_id VARCHAR, preview JSON, agent VARCHAR, args_sha256 VARCHAR)")
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    con.execute(INBOX_SQL.read_text(encoding="utf-8"))
    columns = [row[0] for row in con.execute("DESCRIBE inbox.company_commands").fetchall()]
    assert columns[-2:] == ["slack_channel", "slack_ts"]
