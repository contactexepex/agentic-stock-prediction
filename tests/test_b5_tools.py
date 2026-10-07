"""B5 tools and channels (docs/SPEC.md F10, section 10 row B5): the generated tool registry of web/lib/tools/ is current
with mcp/tools.yaml and mcp/agents/*.yaml, every agent respects the channel permissions, and the inbox of
mcp/inbox.sql matches the command_log schema and runs every statement of web/lib/tools/sql.ts. Offline (local DuckDB).
The web tier's own tests run with `npm test` in web/ (.github/workflows/web-tests.yml)."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
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


def request_params(inbox_id: str, command_id: str) -> list:
    arguments = json.dumps({"market": "us", "ticker": "AAPL"})
    return [inbox_id, "watchlist_events", "reactivate_company", "us", arguments, None, "slack", "slack:U07ABCD123",
            "slack-gateway", command_id, "2026-10-07T10:00:00.000Z", "f" * 64]


def test_inbox_statements_run_on_duckdb():
    sql = statements()
    assert set(sql) == {"usage", "claim", "existing", "append", "find"}
    con = inbox()
    assert con.execute(sql["claim"], request_params("key-000001", "cmd-1")).fetchall() == [("key-000001",)]
    assert con.execute(sql["claim"], request_params("key-000001", "cmd-2")).fetchall() == []
    existing = con.execute(sql["existing"], ["key-000001"]).fetchall()
    assert existing[0][9] == "cmd-1" and json.loads(existing[0][4]) == {"market": "us", "ticker": "AAPL"}
    who = ["slack", "slack:U07ABCD123", "slack-gateway"]
    con.execute(sql["append"], ["cmd-1", "us", "2026-10-07T10:00:00.000Z", *who, "reactivate_company", "write",
                                json.dumps({"ticker": "AAPL"}), "key-000001", "pending", None, "Pending: ...",
                                json.dumps(["we-1"]), 19, "2026-10-07T10:00:01.000Z"])
    con.execute(sql["append"], ["cmd-2", "us", "2026-10-07T10:01:00.000Z", *who, "explain", "read_ai", "{}", None,
                                "accepted", None, None, "[]", None, "2026-10-07T10:01:00.000Z"])
    found = con.execute(sql["find"], ["cmd-1"]).fetchall()[0]
    assert json.loads(found[13]) == ["we-1"] and found[14] == 19 and found[10] == "pending"
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-07T00:00:00Z"]).fetchall() == [(1, 1, None)]
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-08T00:00:00Z"]).fetchall() == [(0, 0, None)]
    con.execute("INSERT INTO inbox.controls VALUES ('slack-gateway', false, 'stop', '2026-10-07T09:00:00Z'), "
                "('slack-gateway', true, 'go', '2026-10-07T09:30:00Z'), "
                "('*', false, 'all off', '2026-10-07T09:45:00Z')")
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-07T00:00:00Z"]).fetchall()[0][2] is False
    con.execute("INSERT INTO inbox.controls VALUES ('*', true, 'all on', '2026-10-07T09:50:00Z')")
    assert con.execute(sql["usage"], ["slack-gateway", "2026-10-07T00:00:00Z"]).fetchall()[0][2] is True


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
