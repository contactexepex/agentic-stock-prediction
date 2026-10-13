"""B13: rm.portfolio's all_trades block (every paper trade in one place; owner request of 2026-10-12)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import all_trades, trade_pages  # noqa: E402
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
        "prediction_id": f"{family}.x:2026-10-07-AAPL-1d", "move_pct": extra.get("move_pct"),
        "market_pct": extra.get("market_pct"), "sector_pct": None, "news_pct": None, "company_pct": None,
        "reason_code": extra.get("reason_code"),
    }  # fmt: skip


def opened(trade_id, view, family, **extra):
    return {
        "trade_id": trade_id, "view": view, "strategy_id": f"{family}.x", "family": family, "ticker": "AAPL",
        "horizon_days": 3, "entry_date": "2026-10-12", "exit_date": "2026-10-15", "entry_price": 100.0,
        "last_price": 102.0, "last_price_date": "2026-10-12", "quantity": 9.0, "amount": 1000.0, "currency": "USD",
        "unrealised_pnl": 18.0, "unrealised_pct": 2.0, "lo80": 95.0, "lo50": 98.0, "hi50": 103.0, "hi80": 106.0,
        "target_price": 101.5, "to_target_pct": -0.5, "prediction_id": f"{family}.x:2026-10-09-AAPL-3d", **extra,
    }  # fmt: skip


@pytest.fixture
def make(monkeypatch):
    settlements = [
        settled("a1", "accuracy", "rule", 12.5, 10.0),
        settled("a2", "accuracy", "ai", -3.0, -4.0, move_pct=-0.8, market_pct=-0.6, reason_code="market"),
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
    predictions = {
        "rule.x:2026-10-09-AAPL-3d": {"id": "rule.x:2026-10-09-AAPL-3d", "family": "rule", "ticker": "AAPL",
                                      "session_date": "2026-10-12", "direction": "up", "prob_up": 0.58, "reason": None,
                                      "threshold": 0.55, "qualifies": True},
        "ai.x:2026-10-07-AAPL-1d": {"id": "ai.x:2026-10-07-AAPL-1d", "family": "ai", "ticker": "AAPL",
                                    "session_date": "2026-10-08", "direction": "up", "prob_up": 0.6,
                                    "reason": "Order wins, small edge.", "threshold": 0.55, "qualifies": True},
    }  # fmt: skip
    check_rows = {"AAPL": [
        {"check_at": "2026-10-09T15:00:00Z", "session_date": "2026-10-09", "move_pct": 1.0, "market_pct": 0.5,
         "market_pull_pct": 0.6, "sector_pct": 0.2, "own_pct": 0.4, "beta": 1.2, "sector_source": "sector_etf",
         "note": None},
        {"check_at": "2026-10-12T15:00:00Z", "session_date": "2026-10-12", "move_pct": 2.0, "market_pct": 1.0,
         "market_pull_pct": 1.2, "sector_pct": 0.5, "own_pct": 0.8, "beta": 1.2, "sector_source": "sector_etf",
         "note": "Rose with the market."},
    ]}  # fmt: skip
    monkeypatch.setattr(all_trades.trade_why, "predictions", lambda _ctx: predictions)
    monkeypatch.setattr(all_trades.trade_why, "checks_by_ticker", lambda _ctx: check_rows)
    monkeypatch.setattr(all_trades.trade_why, "ai_reasons", lambda _ctx: {"a2": "Fell with the market."})
    monkeypatch.setattr(all_trades.trade_why, "lessons", lambda _ctx: [])
    monkeypatch.setattr(all_trades.trade_why, "latest_review", lambda _ctx: None)
    ctx.__dict__["cutoff_time"] = datetime.fromisoformat("2026-10-12T16:00:00+00:00")
    return lambda: (
        {**all_trades.all_trades(ctx, None), **trade_pages.indexes(ctx, None)},
        all_trades.session_pages(ctx, None),
        trade_pages.open_pages(ctx, None),
        trade_pages.finished_pages(ctx, None),
    )


@pytest.fixture
def built(make):
    return make()


@pytest.fixture
def block(built):
    return built[0]


@pytest.fixture
def pages(built):
    return built[1]


@pytest.fixture
def holds(built):
    return built[2]


@pytest.fixture
def finished(built):
    return built[3]


def every_row(block, pages) -> dict[str, dict]:
    on_pages = [t for page in pages.values() for t in page["trades"]]
    assert len(on_pages) == len({t["id"] for t in on_pages})  # each accuracy trade on one session page only
    assert len(block["trades"]) == len({t["id"] for t in block["trades"]})
    return {t["id"]: t for t in [*block["trades"], *on_pages]}


def summary_of(block, scope, family, period="to_date"):
    return next(r for r in block["summary"] if (r["scope"], r["family"], r["period"]) == (scope, family, period))


def test_step_2_market_page_lists_head_to_head_and_mine_only(block):
    assert all_trades.LIST_ACCURACY_ON_MARKET_PAGE is False
    assert [t["id"] for t in block["trades"]] == ["o2", "m3", "h1", "m2"]  # open first, newest exit/entry, then id
    assert all(t["scope"] != "all" and t["paper"] is True for t in block["trades"])


def test_step_1_listing_kept_behind_the_switch(monkeypatch, make, pages):
    monkeypatch.setattr(all_trades, "LIST_ACCURACY_ON_MARKET_PAGE", True)
    block, *_pages = make()
    assert [t["id"] for t in block["trades"]] == ["o1", "o2", "m3", "a1", "a2", "a3", "a4", "h1", "m2"]
    on_pages = {t["id"]: t for page in pages.values() for t in page["trades"]}
    assert all(t == on_pages[t["id"]] for t in block["trades"] if t["scope"] == "all")


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
    block, pages, *_rest = make()
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


def test_market_page_open_trades_and_checks_are_head_to_head_only_and_pass_price_pending(monkeypatch):
    from marketbrief.warehouse import rm_portfolio

    opens = [opened("o1", "accuracy", "rule"), opened("o2", "head_to_head", "rule")]
    opens.append(opened("o3", "head_to_head", "rule", price_pending=True, entry_price_source=None))
    checks = [{"trade_id": "o1", "view": "accuracy"}, {"trade_id": "o2", "view": "head_to_head"}]
    monkeypatch.setattr(rm_portfolio.rm_common, "open_trades", lambda _ctx: opens)
    monkeypatch.setattr(rm_portfolio.rm_company, "market_trade_checks", lambda _ctx: checks)
    ctx = lab_context("us")
    listed = rm_portfolio.open_trades(ctx)
    assert [t["trade_id"] for t in listed] == ["o2", "o3"]  # the accuracy view is on the session pages
    assert [t["trade_id"] for t in rm_portfolio.trade_checks(ctx)] == ["o2"]
    pending = listed[1]
    assert (pending["price_pending"], pending["entry_price_source"], pending["last_price_time"]) == (True, None, None)


# ---------- UX3: the why of each trade, the pages by hold and by sell day, what the system learns ----------


def test_ux3_rows_carry_their_prediction_and_why(block, pages):
    rows = every_row(block, pages)
    o1 = rows["o1"]
    assert (o1["direction"], o1["prob_up"], o1["reason"]) == ("up", 0.58, None)
    assert o1["why"]["source"] == "intraday_check" and o1["why"]["check_at"] == "2026-10-12T15:00:00Z"
    assert (o1["why"]["market_pct"], o1["why"]["own_pct"], o1["why"]["note"]) == (1.0, 0.8, "Rose with the market.")
    assert rows["o2"]["why"] is not None  # the latest check is of its entry session
    a2 = rows["a2"]
    assert a2["reason"] == "Order wins, small edge." and a2["prob_up"] == 0.6
    assert a2["why"]["source"] == "settlement" and a2["why"]["reason_code"] == "market"
    why = a2["why"]
    assert (why["move_pct"], why["market_pct"], why["ai_reason"]) == (-0.8, -0.6, "Fell with the market.")
    assert rows["a4"]["why"] is None  # never entered
    assert rows["m3"]["why"] is None and rows["m3"]["direction"] is None  # the owner's own trade


def test_ux3_open_why_only_from_a_check_of_the_entry_session_or_later(monkeypatch, make):
    monkeypatch.setattr(all_trades.trade_why, "checks_by_ticker", lambda _ctx: {"AAPL": [
        {"check_at": "2026-10-09T15:00:00Z", "session_date": "2026-10-09", "move_pct": 1.0, "market_pct": 0.5,
         "sector_pct": 0.2, "own_pct": 0.4, "beta": 1.2, "sector_source": "peers", "note": None}]})  # fmt: skip
    block, pages, *_rest = make()
    assert every_row(block, pages)["o1"]["why"] is None  # entered 2026-10-12: a 2026-10-09 check is not its own


def test_ux3_open_pages_by_hold_with_the_split_per_family(block, holds):
    assert sorted(holds) == ["open:3"]
    page = holds["open:3"]
    assert [t["id"] for t in page["trades"]] == ["o1"] and page["paper"] is True and page["horizon_days"] == 3
    assert block["open_holds"] == [page["summary"]]
    hold = page["summary"]
    counts = (hold["open"], hold["going_with"], hold["going_against"], hold["pending"], hold["flagged"])
    assert counts == (1, 1, 0, 0, 1)
    assert (hold["profit"], hold["loss"], hold["unrealised_pnl"]) == (18.0, None, 18.0)
    assert hold["exit_dates"] == ["2026-10-15"]
    by_family = {f["family"]: f for f in hold["by_family"]}
    assert [f["family"] for f in hold["by_family"]] == ["rule", "ai", "baseline"]
    assert by_family["rule"]["open"] == 1 and by_family["ai"]["open"] == 0 and by_family["ai"]["unrealised_pnl"] is None
    assert page["trades"][0]["sessions"] == {"held": 1, "total": 4}  # 12 Oct of 12-15 Oct


def test_ux3_finished_pages_by_sell_day_in_the_window(block, finished):
    assert sorted(finished) == ["finished:2026-10-09"]  # a5 sold before the window
    page = finished["finished:2026-10-09"]
    assert [t["id"] for t in page["trades"]] == ["a1", "a2", "a3", "a4"]
    day = page["summary"]
    assert block["finished_sessions"] == [day]
    assert (day["closed"], day["not_entered"], day["wins"], day["losses"], day["flat"]) == (3, 1, 1, 1, 1)
    assert (day["net_pnl_market"], day["net_pnl_your"]) == (9.5, 5.0)
    by_family = {f["family"]: f for f in day["by_family"]}
    assert (by_family["rule"]["closed"], by_family["rule"]["wins"], by_family["rule"]["net_pnl_market"]) == (1, 1, 12.5)
    assert (by_family["ai"]["losses"], by_family["baseline"]["flat"]) == (1, 1)


def test_ux3_going_flips_for_a_down_call_and_waits_for_a_price():
    base = {"entry_price": 100.0, "exit_or_last_price": 98.0, "price_pending": False, "direction": "up"}
    assert trade_pages.going(base) == "against"
    assert trade_pages.going({**base, "direction": "down"}) == "with"
    assert trade_pages.going({**base, "exit_or_last_price": 100.0}) == "against"  # level is not going as predicted
    assert trade_pages.going({**base, "price_pending": True}) == "pending"


def test_ux3_learning_block(block):
    learning = block["learning"]
    assert learning["lessons"] == {"count": 0, "newest": None, "read_by": "ai.combined.opus.v1"}
    assert learning["review"] is None
    assert learning["next_review_at"] == "2026-10-16T23:30:00Z"  # Friday 19:30 New York (EDT)
    assert learning["rule_today"] == {"session_date": "2026-10-12", "predictions": 1, "qualifying": 1,
                                      "best_prob_up": 0.58, "bar": 0.55}  # fmt: skip


def test_ux3_pages_validate_against_the_contract(block, holds, finished):
    assert schema_errors([block], "AllTrades") == []
    assert schema_errors(list(holds.values()), "PortfolioHold") == []
    assert schema_errors(list(finished.values()), "PortfolioFinished") == []
    assert schema_errors([*holds.values(), *finished.values()], "PaperPortfoliosTable") == []
