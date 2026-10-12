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
    entry_day = extra.get("entry_day", "2026-10-08")
    return {
        "trade_id": trade_id, "view": view, "strategy_id": f"{family}.x", "family": family, "pick_rule": None,
        "ticker": "AAPL", "horizon_days": 1, "entry_date": entry_day, "exit_date": exit_day,
        "exit_date_actual": exit_day, "status": status, "entry_price": 100.0, "exit_price": 101.0, "quantity": 9.0,
        "amount": 1000.0, "currency": "USD", "net_pnl": pnl, "net_pnl_your": your, "return_pct": 1.0,
        "return_pct_your": 0.5, "settled_at": datetime.fromisoformat("2026-10-09T21:00:00+00:00"),
    }  # fmt: skip


def opened(trade_id, view, family, **extra):
    return {
        "trade_id": trade_id, "view": view, "strategy_id": f"{family}.x", "family": family, "ticker": "AAPL",
        "horizon_days": 3, "entry_date": "2026-10-12", "exit_date": "2026-10-15", "entry_price": 100.0,
        "last_price": 102.0, "last_price_date": "2026-10-12", "quantity": 9.0, "amount": 1000.0, "currency": "USD",
        "unrealised_pnl": 18.0, "unrealised_pct": 2.0, "lo80": 95.0, "lo50": 98.0, "hi50": 103.0, "hi80": 106.0,
        "target_price": 101.5, "to_target_pct": -0.5, **extra,
    }  # fmt: skip


@pytest.fixture
def make(monkeypatch):
    settlements = [
        settled("a1", "accuracy", "rule", 12.5, 10.0),
        settled("a2", "accuracy", "ai", -3.0, -4.0),
        settled("a3", "accuracy", "baseline", 0.0, -1.0),
        settled("a4", "accuracy", "rule", None, status="no_entry"),
        settled("a5", "accuracy", "rule", 5.0, 4.0, entry_day="2026-08-31", exit_day="2026-09-01"),  # before the window
        settled("h1", "head_to_head", "ai", 7.0, None),
    ]
    opens = [
        opened("o1", "accuracy", "rule", entry_price_source="intraday_check", last_price_source="intraday_check",
               last_price_time="2026-10-12T05:00:00Z"),
        opened("o2", "head_to_head", "rule", price_pending=True, entry_price=None, last_price=None, quantity=None,
               unrealised_pnl=None, unrealised_pct=None, entry_price_source=None, last_price_source=None),
        opened("a1", "accuracy", "rule"),  # settled by the cut-off: listed once, as closed
    ]  # fmt: skip
    ledger = {
        "trades": [
            {"id": "m1", "ticker": "AAPL", "side": "buy", "trade_date": "2026-10-01", "quantity": 5, "price": 90.0,
             "open_quantity": 0.0},
            {"id": "m2", "ticker": "AAPL", "side": "sell", "trade_date": "2026-10-09", "quantity": 5, "price": 95.0,
             "realised_net": 20.0},
            {"id": "m3", "ticker": "AAPL", "side": "buy", "trade_date": "2026-10-09", "quantity": 2, "price": 95.0,
             "open_quantity": 2.0, "mark": 96.0, "mark_date": "2026-10-09", "unrealised_gross": 2.0,
             "unrealised_net": 1.5},
            {"id": "m4", "ticker": "GONE", "side": "sell", "trade_date": "2026-10-09", "quantity": 1, "price": 9.0,
             "realised_net": -2.0},
        ]
    }  # fmt: skip
    monkeypatch.setattr(all_trades.rm_common, "settled_trades", lambda _ctx: settlements)
    monkeypatch.setattr(all_trades.rm_common, "open_trades", lambda _ctx: opens)
    monkeypatch.setattr(all_trades.portfolio_service, "pnl_report", lambda _context: ledger)
    checks = [{"trade_id": "o1", "check_at": "2026-10-12T05:00:00Z", "band": "inside_80", "flags": ["far_from_target"],
               "flagged": True, "ret_since_entry_pct": 2.0, "view": "accuracy"}]  # fmt: skip
    monkeypatch.setattr(all_trades.rm_company, "market_trade_checks", lambda _ctx: checks)
    ctx = lab_context("us")
    ctx.__dict__["collected"] = frozenset({"AAPL"})
    ctx.__dict__["dashboard"] = {"as_of": "2026-10-09"}
    ctx.__dict__.pop("as_of", None)
    monkeypatch.setattr(all_trades.rm_common, "status_block", lambda _ctx: {"session": {"session_date": "2026-10-12"}})
    return lambda: (all_trades.all_trades(ctx, None), all_trades.session_pages(ctx, None))


@pytest.fixture
def built(make):
    return make()


@pytest.fixture
def block(built):
    return built[0]


@pytest.fixture
def pages(built):
    return built[1]


def every_row(block, pages) -> dict[str, dict]:
    rows = [*block["trades"], *(t for page in pages.values() for t in page["trades"])]
    assert len(rows) == len({t["id"] for t in rows})  # each trade on one page only
    return {t["id"]: t for t in rows}


def summary_of(block, scope, family, period="to_date"):
    return next(r for r in block["summary"] if (r["scope"], r["family"], r["period"]) == (scope, family, period))


def test_market_page_lists_head_to_head_and_mine_open_first(block):
    ids = [t["id"] for t in block["trades"]]
    assert ids == ["o2", "m3", "h1", "m2"]  # open first, by exit (else entry) date newest first, then id
    assert all(t["scope"] != "all" for t in block["trades"]) and all(t["paper"] is True for t in block["trades"])


def test_accuracy_view_on_one_page_per_entry_session(block, pages):
    assert sorted(pages) == ["trades:2026-08-31", "trades:2026-10-08", "trades:2026-10-12"]
    assert [t["id"] for t in pages["trades:2026-10-08"]["trades"]] == ["a1", "a2", "a3", "a4"]
    assert [t["id"] for t in pages["trades:2026-10-12"]["trades"]] == ["o1"]
    assert all(page["paper"] is True and page["market"] == "us" for page in pages.values())
    index = {entry["session_date"]: entry for entry in block["sessions"]}
    assert [entry["session_date"] for entry in block["sessions"]] == ["2026-10-12", "2026-10-08", "2026-08-31"]
    assert index["2026-10-08"] == pages["trades:2026-10-08"]["summary"]
    day = index["2026-10-08"]
    assert (day["entered"], day["not_entered"], day["open"], day["closed"]) == (4, 1, 0, 3)
    assert (day["wins"], day["losses"], day["flat"], day["net_pnl_market"]) == (1, 1, 1, 9.5)
    assert index["2026-10-12"]["open"] == 1
    assert (index["2026-10-12"]["unrealised_pnl"], index["2026-10-12"]["flagged_open"]) == (18.0, 1)
    assert (day["unrealised_pnl"], day["flagged_open"]) == (None, 0)


def test_sessions_older_than_the_pages_are_dropped_but_still_counted(monkeypatch, make):
    monkeypatch.setattr(all_trades, "SESSION_PAGES", 3)  # 2026-10-08, 09 and 12
    block, pages = make()
    assert sorted(pages) == ["trades:2026-10-08", "trades:2026-10-12"]
    assert [entry["session_date"] for entry in block["sessions"]] == ["2026-10-12", "2026-10-08"]
    assert summary_of(block, "all", "all")["closed"] == 4  # a5 (entered 2026-08-31) still counted to date


def test_outcomes_on_market_cost_and_not_entered_never_counted(block, pages):
    rows = every_row(block, pages)
    assert rows["a1"]["outcome"] == "win" and rows["a2"]["outcome"] == "loss" and rows["a3"]["outcome"] == "flat"
    assert rows["a3"]["pnl_your"] == -1.0  # flat on market cost, a loss on your cost: the market cost decides
    assert rows["a4"]["state"] == "not_entered" and rows["a4"]["outcome"] is None
    assert rows["a4"]["not_entered_reason"] == "no_entry" and rows["a1"]["not_entered_reason"] is None
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


def test_open_trade_price_sources_and_pending(block, pages):
    rows = every_row(block, pages)
    assert rows["o1"]["entry_price_source"] == "intraday_check" and rows["o1"]["last_price_source"] == "intraday_check"
    assert rows["o1"]["last_price_time"] == "2026-10-12T05:00:00Z"
    assert rows["o1"]["unrealised_pnl"] == 18.0 and rows["o1"]["pnl_market"] is None and rows["o1"]["outcome"] is None
    assert rows["o2"]["price_pending"] is True and rows["o2"]["entry_price"] is None
    assert rows["o2"]["unrealised_pnl"] is None
    assert (rows["o1"]["lo80"], rows["o1"]["hi80"], rows["o1"]["target_price"], rows["o1"]["to_target_pct"]) == (
        95.0,
        106.0,
        101.5,
        -0.5,
    )
    assert rows["o1"]["check"] == {
        "check_at": "2026-10-12T05:00:00Z",
        "band": "inside_80",
        "flags": ["far_from_target"],
        "flagged": True,
        "ret_since_entry_pct": 2.0,
    }
    assert rows["o2"]["check"] is None and rows["a1"]["check"] is None and rows["a1"]["lo80"] is None
    closed = rows["a1"]
    assert (closed["entry_price_source"], closed["last_price_source"], closed["exit_date"]) == (
        "daily_bar",
        "daily_close",
        "2026-10-09",
    )


def test_owner_trades_on_your_cost_collected_only(block, pages):
    rows = every_row(block, pages)
    assert "m1" not in rows and "m4" not in rows  # a fully sold buy; a deleted company
    assert rows["m2"]["state"] == "closed" and rows["m2"]["outcome"] == "win" and rows["m2"]["pnl_market"] is None
    assert (rows["m2"]["side"], rows["m2"]["entry_date"], rows["m2"]["strategy_id"]) == ("sell", None, None)
    assert rows["m3"]["state"] == "open" and rows["m3"]["side"] == "buy" and rows["m3"]["quantity"] == 2.0
    assert rows["m3"]["unrealised_pnl"] == 2.0 and rows["m3"]["unrealised_pct"] == 1.05  # 2.0 / (95 x 2), before costs
    assert rows["m3"]["pnl_your"] is None
    everything = summary_of(block, "all", "all")
    assert (everything["unrealised_pnl"], everything["flagged_open"]) == (18.0, 1)  # o1 only
    head = summary_of(block, "head_to_head", "all")
    assert (head["unrealised_pnl"], head["flagged_open"]) == (None, 0)  # o2 is price pending
    mine = summary_of(block, "mine", "mine")
    assert mine["unrealised_pnl"] == 2.0
    assert (mine["open"], mine["closed"], mine["wins"], mine["net_pnl_your"]) == (1, 1, 1, 20.0)


def test_block_and_pages_validate_against_the_contract(block, pages):
    assert schema_errors([block], "AllTrades") == []
    assert schema_errors(list(pages.values()), "PortfolioSession") == []
    assert schema_errors(list(pages.values()), "PaperPortfoliosTable") == []


def test_market_page_open_trades_and_checks_are_head_to_head_only(monkeypatch):
    from marketbrief.warehouse import rm_portfolio

    opens = [opened("o1", "accuracy", "rule"), opened("o2", "head_to_head", "rule")]
    checks = [{"trade_id": "o1", "view": "accuracy"}, {"trade_id": "o2", "view": "head_to_head"}]
    monkeypatch.setattr(rm_portfolio.rm_common, "open_trades", lambda _ctx: opens)
    monkeypatch.setattr(rm_portfolio.rm_company, "market_trade_checks", lambda _ctx: checks)
    ctx = lab_context("us")
    assert [t["trade_id"] for t in rm_portfolio.open_trades(ctx)] == ["o2"]
    pending = opened("o3", "head_to_head", "rule", price_pending=True, entry_price_source=None)
    opens.append(pending)
    passed = rm_portfolio.open_trades(ctx)[-1]
    assert (passed["price_pending"], passed["entry_price_source"], passed["last_price_time"]) == (True, None, None)
    assert [t["trade_id"] for t in rm_portfolio.trade_checks(ctx)] == ["o2"]
