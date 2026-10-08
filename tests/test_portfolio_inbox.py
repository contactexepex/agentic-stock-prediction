"""The paper-trade inbox import (issue #112; scripts/portfolio.py import-inbox, marketbrief/portfolio/inbox_import.py)
on a local inbox built from mcp/inbox.sql and the synthetic data root of tests/test_portfolio.py (offline): accepted,
refused (validation, channel, missing fields) and duplicate rows, identity and channel from the row, one command_log
row each, and nothing imported twice; plus the inbox-only sources the CLI refuses (issue #119), a key used by a
watchlist request (refused, not a trade duplicate) and a trade row stored twice by concurrent imports (read once)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date  # noqa: E402

from test_portfolio import buy, ctx_for, make_root, run_cli, write_bars, write_jsonl  # noqa: E402

from marketbrief.core.database import connect  # noqa: E402
from marketbrief.portfolio import reads, service  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def request(inbox_id: str, args: dict, channel: str = "slack", market: str = "us",
            actor: str = "slack:U07ABCD123") -> tuple:
    return (inbox_id, "portfolio_trades", "add_paper_trade", market, json.dumps({"market": market, **args}), None,
            channel, actor, "slack-gateway", f"cmd-20261007T100000Z-{inbox_id[-4:]}", "2026-10-07T10:00:00Z", "sha")


def make_inbox(path: Path, rows: list[tuple]) -> None:
    """The web tier's inbox tables (mcp/inbox.sql, B5's schema) with these inbox.requests rows."""
    con = duckdb.connect(str(path))
    con.execute((REPO / "mcp" / "inbox.sql").read_text())
    con.executemany("INSERT INTO inbox.requests (inbox_id, kind, tool, market, arguments, preview, channel, "
                    "submitted_by, agent, command_id, submitted_at, args_sha256) VALUES "
                    "(?, ?, ?, ?, CAST(? AS JSON), ?, ?, ?, ?, ?, CAST(? AS TIMESTAMPTZ), ?)", rows)
    con.close()


@pytest.fixture
def root(tmp_path, monkeypatch):
    return make_root(tmp_path, monkeypatch)


TRADE = {"ticker": "AAPL", "side": "buy", "quantity": 2, "trade_date": "2026-10-01", "price_basis": "open"}


def test_import_accepts_refuses_and_is_idempotent(root):
    buy(ctx_for(), quantity=1, idempotency_key="used-key")                       # a CLI trade already holding a key
    inbox = root / "web_inbox.duckdb"
    make_inbox(inbox, [
        request("inbox-ok-0001", TRADE),
        request("inbox-app-0002", {**TRADE, "quantity": 1.5, "price_basis": "close"}, channel="claude_app",
                actor="github:owner-login"),
        request("inbox-msft-0003", {**TRADE, "ticker": "MSFT"}),                      # not on the watchlist
        request("inbox-cli-0004", TRADE, channel="cli"),                               # channel not allowed
        request("inbox-part-0005", {"ticker": "AAPL", "quantity": 1}),                 # fields missing
        request("used-key", TRADE),                                                    # key already a trade's
        request("inbox-ind-0006", {**TRADE, "ticker": "HDFCBANK"}, market="india"),   # another market
    ])
    code, first, _ = run_cli(["--market", "us", "import-inbox", "--inbox", str(inbox)])
    assert code == 0 and first["imported"] == 6
    by_id = {row["inbox_id"]: row for row in first["results"]}
    assert by_id["inbox-ok-0001"]["result"] == "accepted" and by_id["inbox-app-0002"]["result"] == "accepted"
    assert by_id["inbox-msft-0003"]["refusal_code"] == "validation_failed"
    assert "not in the us watchlist" in by_id["inbox-msft-0003"]["errors"][0]
    assert by_id["inbox-cli-0004"]["refusal_code"] == "not_allowed_in_channel"
    assert by_id["inbox-part-0005"]["errors"] == ["the request needs side, trade_date, price_basis"]
    assert by_id["used-key"]["result"] == "duplicate" and by_id["used-key"]["ok"] is True
    trades = connect("us").execute("SELECT idempotency_key, source, submitted_by, command_id, quantity, price "
                                   "FROM portfolio_trades ORDER BY entered_at, id").fetchall()
    assert ("inbox-ok-0001", "slack", "slack:U07ABCD123", "cmd-20261007T100000Z-0001", 2.0, 200.0) in trades
    assert ("inbox-app-0002", "claude_app", "github:owner-login", "cmd-20261007T100000Z-0002", 1.5, 202.0) in trades
    assert len(trades) == 3                                          # the CLI trade and the two accepted ones
    log = connect("us").execute("SELECT idempotency_key, result, actor, channel, tool FROM command_log "
                                "ORDER BY idempotency_key").fetchall()
    assert len(log) == 6 and ("inbox-ok-0001", "accepted", "slack:U07ABCD123", "slack", "add_paper_trade") in log
    code, again, _ = run_cli(["--market", "us", "import-inbox", "--inbox", str(inbox)])
    assert code == 0 and again["imported"] == 0                      # every row settled: nothing twice
    code, india, _ = run_cli(["--market", "india", "import-inbox", "--inbox", str(inbox)])
    assert india["imported"] == 1 and india["results"][0]["result"] == "accepted"


@pytest.mark.usefixtures("root")
def test_import_needs_a_token_or_a_file(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_INBOX_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="MOTHERDUCK_INBOX_TOKEN is not set"):
        run_cli(["--market", "us", "import-inbox"])


def test_import_reads_as_of_the_clock_and_retries_trades_not_decidable_yet(root, monkeypatch):
    # the clock is 7 Oct 12:00Z (tests/test_portfolio.py NOW); 7 Oct has no stored AAPL bar yet
    inbox = root / "web_inbox.duckdb"
    late = request("inbox-late-0001", TRADE)
    late = (*late[:10], "2026-10-09T10:00:00Z", late[11])                        # submitted after the clock
    make_inbox(inbox, [late, request("inbox-today-0002", {**TRADE, "trade_date": "2026-10-07"}),
                       request("inbox-future-0003", {**TRADE, "trade_date": "2026-10-08"}),
                       request("inbox-old-0004", {**TRADE, "trade_date": "2026-09-01"})])   # before any stored bar
    code, first, _ = run_cli(["--market", "us", "import-inbox", "--inbox", str(inbox)])
    by_id = {row["inbox_id"]: row for row in first["results"]}
    assert code == 0 and set(by_id) == {"inbox-today-0002", "inbox-future-0003", "inbox-old-0004"}   # not the late row
    # an old session whose bar can never arrive (later bars are stored): refused at once, never retried
    assert by_id["inbox-old-0004"]["refusal_code"] == "validation_failed"
    assert "later sessions are stored" in by_id["inbox-old-0004"]["errors"][0]          # the importer's own text
    assert not any("once the session's bar is collected" in e for e in by_id["inbox-old-0004"]["errors"])
    assert by_id["inbox-today-0002"]["result"] == "failed" and "tried again" in by_id["inbox-today-0002"]["errors"][0]
    assert by_id["inbox-future-0003"]["result"] == "failed"
    # the next run, after the 7 Oct bar is collected (clock 8 Oct 12:00Z): the same request is now stored
    write_bars(root, "us", {"AAPL": {date(2026, 10, 7): (215, 216, 213, 214)}}, collected="2026-10-07T22:00:00+00:00")
    monkeypatch.setenv("MB_NOW", "2026-10-08T12:00:00+00:00")
    code, second, _ = run_cli(["--market", "us", "import-inbox", "--inbox", str(inbox)])
    results = {row["inbox_id"]: row for row in second["results"]}
    assert results["inbox-today-0002"]["result"] == "accepted"
    assert results["inbox-future-0003"]["result"] == "failed"                     # the 8 Oct bar is not stored yet
    assert "inbox-late-0001" not in results                                        # still after the clock
    assert "inbox-old-0004" not in results                                         # settled: not tried again


def test_import_applies_add_trade_checks(root):
    inbox = root / "web_inbox.duckdb"
    make_inbox(inbox, [
        request("inbox-bool-0001", {**TRADE, "quantity": True}),                       # not a number
        request("inbox-sell-0002", {**TRADE, "side": "sell", "quantity": 5}),           # nothing held
        request("inbox-man-0003", {**TRADE, "price_basis": "manual", "price": 201.5}),  # inside 198-205
        request("inbox-manx-0004", {**TRADE, "price_basis": "manual", "price": 250.0}),  # outside the bar
    ])
    _, out, _ = run_cli(["--market", "us", "import-inbox", "--inbox", str(inbox)])
    by_id = {row["inbox_id"]: row for row in out["results"]}
    assert by_id["inbox-bool-0001"]["refusal_code"] == "validation_failed"
    assert "would leave" in by_id["inbox-sell-0002"]["errors"][0]
    assert by_id["inbox-man-0003"]["result"] == "accepted"
    assert "outside" in by_id["inbox-manx-0004"]["errors"][0]


@pytest.mark.parametrize("command", [
    ["add-trade", "--ticker", "AAPL", "--side", "buy", "--quantity", "1", "--date", "2026-10-01", "--basis", "open"],
    ["request-company", "--ticker", "MSFT", "--reason", "test"]])
@pytest.mark.parametrize("source", ["dashboard", "claude_app"])
def test_cli_refuses_the_inbox_only_sources(root, command, source):
    code, out, _ = run_cli(["--market", "us", *command, "--source", source])
    assert code == 2 and out["ok"] is False and "only by the inbox import" in out["errors"][0]
    assert not (root / "data" / "us" / "portfolio_trades").exists()
    assert not (root / "data" / "us" / "watchlist_requests").exists()


def test_a_key_used_by_a_watchlist_request_is_refused_not_a_trade_duplicate(root):
    stored = service.request_company(ctx_for(), "claude_code", "test", ticker="MSFT", idempotency_key="inbox-req-0001")
    inbox = root / "web_inbox.duckdb"
    make_inbox(inbox, [request("inbox-req-0001", TRADE)])
    _, out, _ = run_cli(["--market", "us", "import-inbox", "--inbox", str(inbox)])
    row = out["results"][0]
    assert (row["result"], row["refusal_code"], row["trade_ids"]) == ("refused", "validation_failed", [])
    assert stored["request"]["id"] in row["errors"][0] and "not of a trade" in row["errors"][0]


def test_a_trade_row_stored_twice_counts_once(root):
    # two concurrent imports (onboard.yml and a routine) may each append the same inbox trade (same key, same id)
    first = buy(ctx_for(), quantity=2)["trade"]
    copy = {**first, "entered_at": "2026-10-07T11:30:00+00:00"}                      # the other import's row
    write_jsonl(root, "us", "portfolio_trades", date(2026, 10, 7), [copy])
    assert connect("us").execute("SELECT count(*) FROM portfolio_trades").fetchone()[0] == 2
    rows = reads.trade_rows(connect("us"), ctx_for().clock)
    assert list(rows["id"]) == [first["id"]]                                          # once, at its first entry
    assert rows["entered_at"].iloc[0] == pd.Timestamp(copy["entered_at"])
    assert [p["quantity"] for p in service.positions_report(ctx_for())["positions"]] == [2.0]
