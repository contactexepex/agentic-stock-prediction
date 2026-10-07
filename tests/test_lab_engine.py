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
from marketbrief.lab.settle import settle
from marketbrief.lab.sizing import qualifies, quantity
from marketbrief.lab.timing import entry_session, exit_session, is_locked, sessions_after_d

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
    assert sessions_after_d(5, "n_plus_k") == 5 and sessions_after_d(5, None) == 4 and sessions_after_d(1, None) == 1


def test_qualifies_and_quantity():
    assert qualifies({"direction": "up", "prob_up": 0.55, "threshold": 0.55})
    assert not qualifies({"direction": "up", "prob_up": 0.549, "threshold": 0.55})
    assert not qualifies({"direction": "down", "prob_up": None, "threshold": None})
    assert qualifies({"direction": "up", "prob_up": None, "threshold": None})          # always-up, momentum
    assert quantity("india", 100000.0, 2000.0) == 50.0 and quantity("india", 100000.0, 150000.0) == 0.0
    assert quantity("us", 1000.0, 300.0) == 3.333333


def test_costs_hand_checked():
    # India N+1 RELIANCE: B = 100000, S = 102000; brokerage .0025 x 202000 = 505.00, STT 202.00, exchange
    # 6.2014 -> 6.20, SEBI 0.202 -> 0.20, stamp 15.00, DP max(30, 40.80) = 40.80, GST .18 x 552.2034 = 99.40
    out = lab_costs.round_trip_costs("india", INDIA_RATES, 100000.0, 102000.0, 50.0)
    assert out == {"total": 868.60, "lines": {"brokerage": 505.0, "stt": 202.0, "exchange": 6.2, "sebi": 0.2,
                                              "stamp_duty": 15.0, "dp_charge": 40.8, "gst": 99.4}}
    # US: EUR 0.99 x 1.10 + 0.99 x 1.20 = 2.277 -> 2.28; SEC fee 0.0000206 x 1020 = 0.021 -> 0.02
    out = lab_costs.round_trip_costs("us", US_RATES, 1000.0, 1020.0, 10.0, (1.10, 1.20))
    assert out == {"total": 2.30, "lines": {"order_fee": 2.28, "sec_fee": 0.02}}
    with pytest.raises(ValueError):
        lab_costs.round_trip_costs("us", US_RATES, 1000.0, 1020.0, 10.0, (None, 1.2))
    # one side each, unrounded, adds up to the round trip before rounding
    both = (lab_costs.side_cost("india", INDIA_RATES, "buy", 50, 2000) +
            lab_costs.side_cost("india", INDIA_RATES, "sell", 50, 2040))
    assert both == pytest.approx(505 + 202 + 6.2014 + 0.202 + 15 + 40.8 + 99.396612)


# (horizon, exit close, net_pnl, return_pct) per US AAPL trade: qty 10, costs 2.28 + 0.02 = 2.30 every time
US_EXPECTED = [(1, 102, 17.70, 1.77), (2, 103, 27.70, 2.77), (3, 104, 37.70, 3.77), (4, 105, 47.70, 4.77),
               (5, 106, 57.70, 5.77)]
# (horizon, exit date, costs, net_pnl, return_pct) per India RELIANCE trade: qty 50, entry 100000 (by hand:
# N+2 both 202300 -> 505.75 + 202.30 + 6.21 + 0.20 + 15 + 40.92 + GST 99.55 = 869.93; N+3 870.83; N+4 873.05;
# N+5 875.29; N+4 return 2126.95 / 1000 = 2.12695, stored as the float 2.1269)
INDIA_EXPECTED = [(1, "2026-10-01", 868.60, 1131.40, 1.1314), (2, "2026-10-05", 869.93, 1430.07, 1.4301),
                  (3, "2026-10-06", 870.83, 1629.17, 1.6292), (4, "2026-10-07", 873.05, 2126.95, 2.1269),
                  (5, "2026-10-08", 875.29, 2624.71, 2.6247)]


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
        assert (row["net_pnl"], row["return_pct"]) == (net, ret)
        assert row["cost_lines"]["dp_charge"] > 30 and "exit_delayed" not in row["flags"]


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
    # 100 shares at 1000; 2:1 split ex 5 Oct -> 200 at 520 = 104000; costs on B 100000 + S 104000 = 877.51
    assert (row["quantity"], row["exit_quantity"], row["exit_price"]) == (100.0, 200.0, 520.0)
    assert row["flags"] == ["split_in_window"] and row["adjustment_ids"] == [SPLIT["id"]]
    assert (row["gross_pnl"], row["costs"], row["net_pnl"], row["return_pct"]) == (4000.0, 877.51, 3122.49, 3.1225)
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


def test_deterministic_and_resettle_on_a_split_correction():
    pred = prediction("india", "HDFCBANK", 3, target_price=1030.0, lo80=950.0, hi80=1100.0)
    assert settle(pred, "accuracy", None, india_data(), NOW) == settle(pred, "accuracy", None, india_data(), NOW)
    # a corrected split record (factor 1 cancels it): the same trade settles to a different row
    fixed = settle(pred, "accuracy", None, india_data(adjustments=[]), NOW)
    assert fixed["exit_quantity"] == 100.0 and fixed["flags"] == []
