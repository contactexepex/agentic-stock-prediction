"""B13: rm.portfolio's all_trades block (every paper trade in one place; owner request of 2026-10-12)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import all_trades  # noqa: E402
from test_b13_pages import lab_context, schema_errors  # noqa: E402


def settled(trade_id, view, family, pnl, your=None, **extra):
    status, exit_day = extra.get("status", "settled"), extra.get("exit_day", "2026-10-09")
    return {
        "trade_id": trade_id, "view": view, "strategy_id": f"{family}.x", "family": family, "pick_rule": None,
        "ticker": "AAPL", "horizon_days": 1, "entry_date": "2026-10-08", "exit_date": exit_day,
        "exit_date_actual": exit_day, "status": status, "entry_price": 100.0, "exit_price": 101.0, "quantity": 9.0,
        "amount": 1000.0, "currency": "USD", "net_pnl": pnl, "net_pnl_your": your, "return_pct": 1.0,
        "return_pct_your": 0.5, "settled_at": datetime.fromisoformat("2026-10-09T21:00:00+00:00"),
    }  # fmt: skip


def opened(trade_id, view, family, **extra):
    return {
        "trade_id": trade_id, "view": view, "strategy_id": f"{family}.x", "family": family, "ticker": "AAPL",
        "horizon_days": 3, "entry_date": "2026-10-12", "exit_date": "2026-10-15", "entry_price": 100.0,
        "last_price": 102.0, "last_price_date": "2026-10-12", "quantity": 9.0, "amount": 1000.0, "currency": "USD",
        "unrealised_pnl": 18.0, "unrealised_pct": 2.0, **extra,
    }  # fmt: skip


@pytest.fixture
def block(monkeypatch):
    settlements = [
        settled("a1", "accuracy", "rule", 12.5, 10.0),
        settled("a2", "accuracy", "ai", -3.0, -4.0),
        settled("a3", "accuracy", "baseline", 0.0, -1.0),
        settled("a4", "accuracy", "rule", None, status="no_entry"),
        settled("a5", "accuracy", "rule", 5.0, 4.0, exit_day="2026-09-01"),  # before the window
        settled("h1", "head_to_head", "ai", 7.0, None),
    ]
    opens = [
        opened("o1", "accuracy", "rule", entry_source="intraday_check", last_source="intraday_check"),
        opened("o2", "head_to_head", "rule", price_pending=True, entry_price=None, last_price=None, quantity=None,
               unrealised_pnl=None, unrealised_pct=None, entry_source=None, last_source=None),
        opened("a1", "accuracy", "rule"),  # settled by the cut-off: listed once, as closed
    ]  # fmt: skip
    ledger = {
        "trades": [
            {"id": "m1", "ticker": "AAPL", "side": "buy", "trade_date": "2026-10-01", "quantity": 5, "price": 90.0,
             "open_quantity": 0.0},
            {"id": "m2", "ticker": "AAPL", "side": "sell", "trade_date": "2026-10-09", "quantity": 5, "price": 95.0,
             "realised_net": 20.0},
            {"id": "m3", "ticker": "AAPL", "side": "buy", "trade_date": "2026-10-09", "quantity": 2, "price": 95.0,
             "open_quantity": 2.0, "mark": 96.0, "mark_date": "2026-10-09", "unrealised_net": 1.5},
            {"id": "m4", "ticker": "GONE", "side": "sell", "trade_date": "2026-10-09", "quantity": 1, "price": 9.0,
             "realised_net": -2.0},
        ]
    }  # fmt: skip
    monkeypatch.setattr(all_trades.rm_common, "settled_trades", lambda _ctx: settlements)
    monkeypatch.setattr(all_trades.rm_common, "open_trades", lambda _ctx: opens)
    monkeypatch.setattr(all_trades.portfolio_service, "pnl_report", lambda _context: ledger)
    ctx = lab_context("us")
    ctx.__dict__["collected"] = frozenset({"AAPL"})
    ctx.__dict__["dashboard"] = {"as_of": "2026-10-09"}
    ctx.__dict__.pop("as_of", None)
    return all_trades.all_trades(ctx, None)


def summary_of(block, scope, family, period="to_date"):
    return next(r for r in block["summary"] if (r["scope"], r["family"], r["period"]) == (scope, family, period))


def test_every_trade_listed_once_open_first(block):
    ids = [t["id"] for t in block["trades"]]
    assert sorted(ids) == sorted(["a1", "a2", "a3", "a4", "h1", "o1", "o2", "m2", "m3"])  # a5 outside the window
    assert ids[:3] == ["o1", "o2", "m3"]  # open first, by exit (else entry) date newest first, then id
    assert {t["id"]: t["state"] for t in block["trades"]}["a1"] == "closed"
    assert all(t["paper"] is True for t in block["trades"])


def test_outcomes_on_market_cost_and_not_entered_never_counted(block):
    rows = {t["id"]: t for t in block["trades"]}
    assert rows["a1"]["outcome"] == "win" and rows["a2"]["outcome"] == "loss" and rows["a3"]["outcome"] == "flat"
    assert rows["a3"]["pnl_your"] == -1.0  # flat on market cost, a loss on your cost: the market cost decides
    assert rows["a4"]["state"] == "not_entered" and rows["a4"]["outcome"] is None
    everything = summary_of(block, "all", "all")
    assert (everything["open"], everything["closed"]) == (1, 4)  # a1 a2 a3 a5; a4 not entered
    assert (everything["wins"], everything["losses"], everything["flat"]) == (2, 1, 1)
    assert everything["win_rate"] == 50.0
    assert everything["net_pnl_market"] == 14.5 and everything["net_pnl_your"] == 9.0


def test_views_never_pooled_and_families_split(block):
    head = summary_of(block, "head_to_head", "all")
    assert (head["open"], head["closed"], head["wins"]) == (1, 1, 1)
    assert head["net_pnl_your"] is None and head["pnl_your_missing"] == 1
    rule = summary_of(block, "all", "rule")
    assert (rule["open"], rule["closed"], rule["wins"]) == (1, 2, 2)
    assert summary_of(block, "head_to_head", "baseline")["closed"] == 0


def test_window_period_counts_exits_in_the_window_only(block):
    assert block["window"]["sessions"] == all_trades.WINDOW_SESSIONS and block["window"]["to"] == "2026-10-09"
    window = summary_of(block, "all", "rule", "window")
    assert (window["open"], window["closed"]) == (1, 1)  # a5 exited before the window


def test_open_trade_price_sources_and_pending(block):
    rows = {t["id"]: t for t in block["trades"]}
    assert rows["o1"]["entry_source"] == "intraday_check" and rows["o1"]["pnl_market"] == 18.0
    assert rows["o2"]["price_pending"] is True and rows["o2"]["entry_price"] is None
    assert rows["o2"]["pnl_market"] is None


def test_owner_trades_on_your_cost_collected_only(block):
    rows = {t["id"]: t for t in block["trades"]}
    assert "m1" not in rows and "m4" not in rows  # a fully sold buy; a deleted company
    assert rows["m2"]["state"] == "closed" and rows["m2"]["outcome"] == "win" and rows["m2"]["pnl_market"] is None
    assert rows["m3"]["state"] == "open" and rows["m3"]["quantity"] == 2.0 and rows["m3"]["pnl_your"] == 1.5
    mine = summary_of(block, "mine", "mine")
    assert (mine["open"], mine["closed"], mine["wins"], mine["net_pnl_your"]) == (1, 1, 1, 20.0)


def test_block_validates_against_the_contract(block):
    assert schema_errors([block], "AllTrades") == []
