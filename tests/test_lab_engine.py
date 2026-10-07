"""B2 F1 engine on the hand-checked fixture week (tests/lab_fixtures.py; docs/ws/b2.md): both markets, both views,
all five horizons, a Friday buy with N+1 settling on Monday, a holiday and a split inside the window, the skip,
no-entry and delayed-exit cases, costs, the price-reached measures and the automatic reason. Every expected number
below was computed by hand from the fixture bars and rates (the arithmetic is in the comments)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from lab_fixtures import INDIA_MADE, INDIA_RATES, NOW, SPLIT, US_MADE, US_RATES, india_data, prediction, us_data

from marketbrief.core.market_config import load_market
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.cost_views import settlement_row, viability, viability_row
from marketbrief.lab.settle import settle
from marketbrief.lab.sizing import qualifies, quantity
from marketbrief.lab.timing import entry_session, exit_session, is_locked
from marketbrief.portfolio.horizons import resolved_label, sessions_after_d

H2H = {"id": "h2h:2026-10-01-AAPL-rule-highest_probability", "pick_rule": "highest_probability"}


def test_timing_friday_holiday_and_lock():
    us, india = load_market("us"), load_market("india")
    assert entry_session(us, datetime.fromisoformat(US_MADE)) == date(2026, 10, 2)            # Friday
    assert entry_session(us, datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc)) == date(2026, 10, 5)   # at the open
    assert exit_session(us, date(2026, 10, 2), 1) == date(2026, 10, 5)                         # N+1 = Monday
    assert entry_session(india, datetime.fromisoformat(INDIA_MADE)) == date(2026, 9, 30)
    assert [exit_session(india, date(2026, 9, 30), k) for k in (1, 2)] == [date(2026, 10, 1), date(2026, 10, 5)]
    pred = prediction("us", "AAPL", 1)
    assert is_locked(pred, us, None) and is_locked(pred, us, datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc))
    assert not is_locked(pred, us, datetime(2026, 10, 2, 13, 31, tzinfo=timezone.utc))   # committed after the open
    assert not is_locked({**pred, "made_at": "2026-10-02T13:30:00+00:00"}, us, None)
    # issue #94 (B10's call_basis): N+k closes k sessions after D; an unlabelled 5-day row made before
    # call_scoring.n_plus_k_from (2026-10-07T21:19Z) is legacy_5d_d4 and closes at D+4
    assert [sessions_after_d(k, "n_plus_k") for k in (1, 5)] == [1, 5] and sessions_after_d(5, "legacy_5d_d4") == 4
    assert resolved_label(5, None, "2026-10-07T11:45:00+00:00") == "legacy_5d_d4"
    assert resolved_label(5, None, "2026-10-08T11:45:00+00:00") == "n_plus_k"
    assert resolved_label(1, None, "2026-10-07T11:45:00+00:00") == "n_plus_k"
    assert resolved_label(5, "n_plus_k", "2026-10-07T11:45:00+00:00") == "n_plus_k"


def test_qualifies_and_quantity():
    assert qualifies({"direction": "up", "prob_up": 0.55, "threshold": 0.55})
    assert not qualifies({"direction": "up", "prob_up": 0.549, "threshold": 0.55})
    assert not qualifies({"direction": "down", "prob_up": None, "threshold": None})
    assert qualifies({"direction": "up", "prob_up": None, "threshold": None})          # always-up, momentum
    assert quantity("india", 100000.0, 2000.0) == 50.0 and quantity("india", 100000.0, 150000.0) == 0.0
    assert quantity("us", 1000.0, 300.0) == 3.333333


def test_costs_hand_checked_both_views():
    # India N+1 RELIANCE, market view: B = 100000, S = 102000; brokerage .0075 x 100000 + .0075 x 102000 = 1515.00,
    # STT .001 x 202000 = 202.00, exchange 6.2014 -> 6.20, SEBI 0.202 -> 0.20, stamp .00015 x B = 15.00,
    # GST .18 x (1515 + 6.2014 + 0.202) = 273.8526 -> 273.85; total 2012.25
    views = lab_costs.cost_views("india", INDIA_RATES, (100000.0, 102000.0), 50.0)
    assert views["market"] == {"total": 2012.25, "lines": {"brokerage": 1515.0, "stt": 202.0, "exchange": 6.2,
                                                           "sebi": 0.2, "stamp_duty": 15.0, "gst": 273.85}}
    # your view adds Rs 200 on the purchase date and Rs 200 on the sale date, and DP max(30, .0004 x S) = 40.80
    assert views["your"]["total"] == 2453.05
    assert {k: views["your"]["lines"][k] for k in ("nri_reporting_buy", "nri_reporting_sell", "dp_charge")} == {
        "nri_reporting_buy": 200.0, "nri_reporting_sell": 200.0, "dp_charge": 40.8}
    # minimum Rs 50 per order: B 5000 and S 5100 give 37.50 and 38.25 -> 50 + 50; GST .18 x (100 + 0.31007 +
    # 0.0101) = 18.06; market 100 + 10.10 + 0.31 + 0.01 + 0.75 + 18.06 = 129.23; your + 400 + DP 30 = 559.23
    small = lab_costs.cost_views("india", INDIA_RATES, (5000.0, 5100.0), 5.0)
    assert small["market"]["lines"]["brokerage"] == 100.0 and small["market"]["total"] == 129.23
    assert small["your"]["total"] == 559.23
    # US market: EUR 0.99 x 1.10 + 0.99 x 1.20 = 2.277 -> 2.28; SEC fee 0.0000206 x 1020 = 0.021 -> 0.02; your view
    # adds the FX markup .0075 x 2020 = 15.15 and the portfolio fee .002 x 1000 x 3 / 365 = 0.0164 -> 0.02
    views = lab_costs.cost_views("us", US_RATES, (1000.0, 1020.0), 10.0, {"eurusd": (1.10, 1.20), "holding_days": 3})
    assert views["market"] == {"total": 2.30, "lines": {"order_fee": 2.28, "sec_fee": 0.02}}
    assert views["your"]["total"] == 17.47 and views["your"]["lines"]["fx_markup"] == 15.15
    assert lab_costs.round_trip_costs("us", US_RATES, 1000.0, 1020.0, 10.0, (1.10, 1.20)) == views["market"]
    with pytest.raises(lab_costs.MissingEurUsdError):
        lab_costs.round_trip_costs("us", US_RATES, 1000.0, 1020.0, 10.0, (None, 1.2))
    # one side each (market view, unrounded) adds up to the round trip before rounding
    both = (lab_costs.side_cost("india", INDIA_RATES, "buy", 50, 2000) +
            lab_costs.side_cost("india", INDIA_RATES, "sell", 50, 2040))
    assert both == pytest.approx(1515 + 202 + 6.2014 + 0.202 + 15 + 273.852612)


# (horizon, exit close, net_pnl, return_pct) per US AAPL trade: qty 10, costs 2.28 + 0.02 = 2.30 every time
US_EXPECTED = [(1, 102, 17.70, 1.77), (2, 103, 27.70, 2.77), (3, 104, 37.70, 3.77), (4, 105, 47.70, 4.77),
               (5, 106, 57.70, 5.77)]
# (horizon, exit date, market costs, net_pnl, return_pct) per India RELIANCE trade: qty 50, entry 100000; market
# view lines as in test_costs_hand_checked_both_views, e.g. N+2 (S 102300): brokerage 750 + 767.25 = 1517.25, STT
# 202.30, exchange 6.21, SEBI 0.20, stamp 15, GST .18 x 1523.6626 = 274.26 -> 2015.22. N+1's return -12.25 / 1000
# = -0.01225 is a float half, so it is compared within 1e-4.
INDIA_EXPECTED = [(1, "2026-10-01", 2012.25, -12.25, -0.01225), (2, "2026-10-05", 2015.22, 284.78, 0.2848),
                  (3, "2026-10-06", 2017.20, 482.80, 0.4828), (4, "2026-10-07", 2022.14, 977.86, 0.9779),
                  (5, "2026-10-08", 2027.09, 1472.91, 1.4729)]


@pytest.mark.parametrize("view,pick", [("accuracy", None), ("head_to_head", H2H)])
def test_us_week_all_horizons_both_views(view, pick):
    data = us_data()
    for k, close, net, ret in US_EXPECTED:
        row = settle(prediction("us", "AAPL", k), view, pick, data, NOW)
        assert (row["status"], row["entry_date"], row["exit_date_actual"]) == ("settled", "2026-10-02",
                                                                               ["2026-10-05", "2026-10-06",
                                                                                "2026-10-07", "2026-10-08",
                                                                                "2026-10-09"][k - 1])
        assert (row["quantity"], row["entry_price"], row["exit_price"]) == (10.0, 100.0, close)
        assert (row["costs"], row["net_pnl"], row["return_pct"]) == (2.30, net, ret)
        assert row["trade_id"] == (f"acc:{row['prediction_id']}" if view == "accuracy"
                                   else f"h2h:highest_probability:{row['prediction_id']}")
        assert row["pick_id"] == (pick["id"] if pick else None) and row["flags"] == []


@pytest.mark.parametrize("view,pick", [("accuracy", None), ("head_to_head", H2H)])
def test_india_week_all_horizons_holiday_both_views(view, pick):
    data = india_data()
    for k, exit_day, cost, net, ret in INDIA_EXPECTED:
        row = settle(prediction("india", "RELIANCE", k), view, pick, data, NOW)
        assert (row["exit_date_actual"], row["quantity"], row["costs"]) == (exit_day, 50.0, cost)
        assert row["net_pnl"] == net and row["return_pct"] == pytest.approx(ret, abs=1e-4)
        assert "dp_charge" not in row["cost_lines"] and "exit_delayed" not in row["flags"]   # DP: your view only


def test_friday_buy_settles_monday_with_measures_and_reason():
    pred = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0)
    assert settle(pred, "accuracy", None, us_data().__class__(**{**us_data().__dict__,
                                                                 "now": datetime(2026, 10, 5, 21, 0,
                                                                                 tzinfo=timezone.utc)}),
                  NOW) is None                                  # Monday's bar is final only 120 min after the close
    row = settle(pred, "accuracy", None, us_data(), NOW)
    assert (row["entry_date"], row["exit_date"], row["exit_date_actual"]) == ("2026-10-02", "2026-10-05", "2026-10-05")
    # highs 101.5 (D) and 102.5 (Monday) vs target 102.2 -> reached in session 2; lows 99 and 100 vs entry 100
    assert (row["target_reached"], row["target_reached_session"]) == (True, 2)
    assert (row["max_favourable_pct"], row["max_adverse_pct"]) == (2.5, -1.0)
    assert row["target_error_pct"] == -0.1957 and row["range_hit"] is True          # 102 / 102.2 - 1
    # move 2%; SPY 500 -> 505 = +1% x beta 1.2 = 1.2; XLK +2% - 1% = 1.0; rest -0.2, no news -> company
    assert (row["move_pct"], row["market_pct"], row["sector_pct"], row["news_pct"], row["company_pct"]) == (
        2.0, 1.2, 1.0, 0.0, -0.2)
    assert row["reason_code"] == "market_up" and row["reason_codes"] == ["market_up", "target_reached"]
    assert row["reason_detail"]["sector_source"] == "XLK" and row["reason_detail"]["beta_source"] == "features.beta_1y"


def test_news_part_of_the_reason():
    pred = prediction("india", "RELIANCE", 1, target_price=2030.0, lo80=1950.0, hi80=2030.0)
    row = settle(pred, "accuracy", None, india_data(), NOW)
    # move 2%; NIFTY50 +1% x beta 1.0 = 1.0; no sector index or peer bars -> 0; rest 1.0 with positive verified
    # news (sentiment 0.6) -> news 1.0, company 0; the 2040 close is above hi80 2030 -> range_missed
    assert (row["market_pct"], row["sector_pct"], row["news_pct"], row["company_pct"]) == (1.0, 0.0, 1.0, 0.0)
    assert row["news_ids"] == ["news-rel-1"] and row["reason_detail"]["sector_source"] == "none"
    assert row["reason_codes"] == ["market_up", "target_reached", "range_missed"] and row["range_hit"] is False


def test_split_inside_the_window():
    pred = prediction("india", "HDFCBANK", 3, target_price=1030.0, lo80=950.0, hi80=1100.0)
    row = settle(pred, "accuracy", None, india_data(), NOW)
    # 100 shares at 1000; 2:1 split ex 5 Oct -> 200 at 520 = 104000; market costs on B 100000 + S 104000: brokerage
    # 750 + 780 = 1530, STT 204, exchange 6.26, SEBI 0.20, stamp 15, GST .18 x 1536.4668 = 276.56 -> 2032.02
    assert (row["quantity"], row["exit_quantity"], row["exit_price"]) == (100.0, 200.0, 520.0)
    assert row["flags"] == ["split_in_window"] and row["adjustment_ids"] == [SPLIT["id"]]
    assert (row["gross_pnl"], row["costs"], row["net_pnl"], row["return_pct"]) == (4000.0, 2032.02, 1967.98, 1.968)
    # highs on D's basis 1010, 1020, 518 / 0.5 = 1036 (target 1030 reached in session 3), 525 / 0.5 = 1050 (best:
    # +5%); lows 995, 1000, 1010, 1024 (worst: -0.5%); exit 520 / 0.5 = 1040 vs target 1030
    assert (row["target_reached_session"], row["max_favourable_pct"], row["max_adverse_pct"]) == (3, 5.0, -0.5)
    assert row["range_hit"] is True and row["target_error_pct"] == 0.9709 and row["move_pct"] == 4.0


def test_skip_no_entry_and_delayed_exit():
    skipped = settle(prediction("india", "MARUTI", 1), "accuracy", None, india_data(), NOW)
    assert (skipped["status"], skipped["quantity"], skipped["net_pnl"]) == ("skipped_price_above_amount", 0.0, None)
    missing = settle(prediction("us", "NVDA", 1), "accuracy", None, us_data(), NOW)
    assert missing["status"] == "no_entry" and missing["entry_price"] is None
    delayed = settle(prediction("us", "JPM", 1), "accuracy", None, us_data(), NOW)
    # no 5 Oct bar: exit at 6 Oct's close 306; 3.333333 shares; costs 2.28 + 0.02
    assert (delayed["exit_date"], delayed["exit_date_actual"], delayed["flags"]) == (
        "2026-10-05", "2026-10-06", ["exit_delayed"])
    assert (delayed["quantity"], delayed["gross_pnl"], delayed["costs"], delayed["net_pnl"]) == (
        3.333333, 20.0, 2.30, 17.70)


def test_your_cost_view_of_settled_trades():
    # US AAPL N+k: market 2.30 each; your = 2.30 + FX .0075 x (1000 + S) + portfolio fee .002 x 1000 x days / 365
    data = us_data()
    for k, days, your, net in [(1, 3, 17.47, 2.53), (3, 5, 17.63, 22.37), (5, 7, 17.79, 42.21)]:
        row = settle(prediction("us", "AAPL", k), "accuracy", None, data, NOW)
        view = settlement_row(row, prediction("us", "AAPL", k), data)
        assert (view["holding_days"], view["market_costs"], view["your_costs"], view["net_pnl_your"]) == (
            days, 2.30, your, net)
        assert view["net_pnl_market"] == row["net_pnl"] and (view["eurusd_entry"], view["eurusd_exit"]) == (1.1, 1.2)
    # India RELIANCE N+2: Rs 200 on the purchase date (30 Sep) and Rs 200 on the sale date (5 Oct), DP 40.92
    pred = prediction("india", "RELIANCE", 2)
    view = settlement_row(settle(pred, "accuracy", None, india_data(), NOW), pred, india_data())
    assert (view["session_date"], view["exit_date"]) == ("2026-09-30", "2026-10-05")
    assert (view["your_cost_lines"]["nri_reporting_buy"], view["your_cost_lines"]["nri_reporting_sell"]) == (200, 200)
    assert (view["market_costs"], view["your_costs"], view["net_pnl_your"]) == (2015.22, 2456.14, -156.14)
    # minimum brokerage: ITC, Rs 5000 buys 5 shares at 1000, sold at 1020 -> market 129.23, your 559.23
    small = prediction("india", "ITC", 1, amount=5000.0)
    row = settle(small, "accuracy", None, india_data(), NOW)
    view = settlement_row(row, small, india_data())
    assert (row["costs"], row["cost_lines"]["brokerage"], view["your_costs"]) == (129.23, 100.0, 559.23)
    assert settlement_row(settle(prediction("india", "MARUTI", 1), "accuracy", None, india_data(), NOW),
                          prediction("india", "MARUTI", 1), india_data()) is None          # skipped: no costs


def test_cost_viable_flag():
    # C = 100, target 102 (+2%) at N+1 (D Fri 2 Oct, exit Mon 5 Oct: 3 days); 10 shares bought and sold at 100:
    # market 2.18 + 0.02 = 2.20; your + FX .0075 x 2000 = 15.00 + fee .002 x 1000 x 3 / 365 = 0.02 -> 17.22 = 1.722%
    pred = prediction("us", "AAPL", 1, base_close=100.0, target_price=102.0)
    found = viability(pred, US_RATES, 1.10)
    assert (round(found["market_cost_pct"], 4), round(found["your_cost_pct"], 4)) == (0.22, 1.722)
    assert found["expected_move_pct"] == pytest.approx(2.0) and found["cost_viable"] is True
    assert viability({**pred, "target_price": 101.5}, US_RATES, 1.10)["cost_viable"] is False   # 1.5% < 1.722%
    row = viability_row("prediction", pred["id"], pred, US_RATES, 1.10, NOW)
    assert row["id"] == f"cv:prediction:{pred['id']}" and row["cost_viable"] is True and row["your_costs"] == 17.22


def test_deterministic_and_resettle_on_a_split_correction():
    pred = prediction("india", "HDFCBANK", 3, target_price=1030.0, lo80=950.0, hi80=1100.0)
    assert settle(pred, "accuracy", None, india_data(), NOW) == settle(pred, "accuracy", None, india_data(), NOW)
    # a corrected split record (factor 1 cancels it): the same trade settles to a different row
    fixed = settle(pred, "accuracy", None, india_data(adjustments=[]), NOW)
    assert fixed["exit_quantity"] == 100.0 and fixed["flags"] == []
