"""The hand-checked fixture week of the B2 lab tests (docs/ws/b2.md "Tests"). Research only.

US (XNYS): predictions made Friday 2026-10-02 11:45Z, so D = Friday 2 Oct; N+1 = Monday 5 Oct ... N+5 = Friday 9 Oct.
India (XNSE): made Wednesday 2026-09-30 02:10Z, so D = Wednesday 30 Sep; N+1 = Thursday 1 Oct; 2 Oct is a holiday,
so N+2 = Monday 5 Oct ... N+5 = Thursday 8 Oct.
Bars are (open, high, low, close). Rates are the owner-provided ones of decisions 49-52 (Axis Direct NRI Normal
tier, BUX Basic; the DP charge stays the provisional SPEC F1.6 value), fixed here so a config change does not move
the hand-checked numbers."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.lab.market_data import MarketData  # noqa: E402

INDIA_RATES = {"brokerage_each_side": 0.0075, "brokerage_min_per_order": 50.0, "stt_each_side": 0.001,
               "exchange_txn_each_side": 0.0000307, "sebi_fee_each_side": 0.000001, "stamp_duty_buy": 0.00015,
               "gst_rate": 0.18, "slippage_each_side": 0.0, "nri_reporting_per_trade_date": 200.0,
               "dp_charge_min": 30.0, "dp_charge_rate": 0.0004}
US_RATES = {"commission_each_side": 0.0, "sec_fee_sell": 0.0000206, "finra_taf_per_share_sell": 0.0,
            "finra_taf_max_per_trade": 0.0, "slippage_each_side": 0.0, "order_fee_eur": 0.99, "fx_fee_rate": 0.0075,
            "portfolio_fee_per_year": 0.002}
NOW = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
US_MADE, INDIA_MADE = "2026-10-02T11:45:00+00:00", "2026-09-30T02:10:00+00:00"
US_EXITS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
INDIA_EXITS = ["2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]


def days(rows: dict) -> dict:
    """{date: bar dict} from {'YYYY-MM-DD': (o, h, l, c)}."""
    return {date.fromisoformat(k): dict(zip(("open", "high", "low", "close"), v)) for k, v in rows.items()}


US_BARS = {
    "AAPL": days({"2026-10-02": (100, 101.5, 99, 101), "2026-10-05": (101, 102.5, 100, 102),
                  "2026-10-06": (102, 103.5, 101, 103), "2026-10-07": (103, 104.5, 102, 104),
                  "2026-10-08": (104, 105.5, 103, 105), "2026-10-09": (105, 106.5, 104, 106)}),
    "JPM": days({"2026-10-02": (300, 301, 299, 300), "2026-10-06": (305, 307, 304, 306)}),   # no 5 Oct bar
    "NVDA": days({"2026-10-05": (180, 181, 179, 180), "2026-10-06": (181, 182, 180, 181)}),  # no bar on D
    "SPY": days({"2026-10-02": (500, 501, 499, 500), "2026-10-05": (502, 506, 501, 505),
                 "2026-10-06": (505, 506, 504, 505), "2026-10-07": (505, 506, 504, 505),
                 "2026-10-08": (505, 506, 504, 505), "2026-10-09": (505, 506, 504, 505)}),
    "XLK": days({"2026-10-02": (200, 201, 199, 200), "2026-10-05": (201, 205, 200, 204),
                 "2026-10-06": (204, 205, 203, 204), "2026-10-07": (204, 205, 203, 204),
                 "2026-10-08": (204, 205, 203, 204), "2026-10-09": (204, 205, 203, 204)}),
}
US_EURUSD = {date(2026, 10, 2): 1.10, date(2026, 10, 5): 1.20, date(2026, 10, 6): 1.20, date(2026, 10, 7): 1.20,
             date(2026, 10, 8): 1.20, date(2026, 10, 9): 1.20}
INDIA_BARS = {
    "RELIANCE": days({"2026-09-30": (2000, 2010, 1990, 2005), "2026-10-01": (2005, 2045, 2000, 2040),
                      "2026-10-05": (2040, 2050, 2030, 2046), "2026-10-06": (2045, 2060, 2040, 2050),
                      "2026-10-07": (2050, 2070, 2045, 2060), "2026-10-08": (2060, 2080, 2050, 2070)}),
    "HDFCBANK": days({"2026-09-30": (1000, 1010, 995, 1005), "2026-10-01": (1005, 1020, 1000, 1015),
                      "2026-10-05": (510, 518, 505, 515), "2026-10-06": (515, 525, 512, 520)}),   # 2:1 split 5 Oct
    "ITC": days({"2026-09-30": (1000, 1010, 995, 1005), "2026-10-01": (1005, 1025, 1000, 1020)}),   # min brokerage
    "MARUTI": days({"2026-09-30": (150000, 151000, 149000, 150500), "2026-10-01": (150500, 151000, 150000, 150800)}),
    "NIFTY50": days({"2026-09-30": (25000, 25100, 24900, 25050), "2026-10-01": (25050, 25300, 25000, 25250)}),
}
SPLIT = {"id": "adj-HDFCBANK-2026-10-05", "ticker": "HDFCBANK", "ex_date": "2026-10-05", "factor": 0.5}
RELIANCE_NEWS = {"id": "news-rel-1", "ticker": "RELIANCE", "ts": "2026-10-01T05:00:00+00:00", "status": "corroborated",
                 "sentiment": 0.6}


def us_data() -> MarketData:
    """The US fixture week."""
    return MarketData(market="us", cfg=load_market("us"), now=NOW, rates=US_RATES, bars=US_BARS, adjustments=[],
                      eurusd=US_EURUSD, betas={"AAPL": 1.2}, news=[])


def india_data(adjustments=None) -> MarketData:
    """The India fixture week (the HDFCBANK split by default)."""
    return MarketData(market="india", cfg=load_market("india"), now=NOW, rates=INDIA_RATES, bars=INDIA_BARS,
                      adjustments=[SPLIT] if adjustments is None else adjustments, eurusd={},
                      betas={"RELIANCE": 1.0}, news=[RELIANCE_NEWS])


def prediction(market: str, ticker: str, k: int, **extra) -> dict:
    """A qualifying rule-strategy prediction of the fixture week."""
    us = market == "us"
    row = {"id": f"rule.model_news.v1:{'2026-10-01' if us else '2026-09-29'}-{ticker}-{k}d",
           "strategy_id": "rule.model_news.v1", "family": "rule", "market": market, "ticker": ticker,
           "horizon_days": k, "made_at": US_MADE if us else INDIA_MADE,
           "as_of_date": "2026-10-01" if us else "2026-09-29", "session_date": "2026-10-02" if us else "2026-09-30",
           "exit_date": (US_EXITS if us else INDIA_EXITS)[k - 1], "amount": 1000.0 if us else 100000.0,
           "currency": "USD" if us else "INR", "prob_up": 0.6, "threshold": 0.55, "direction": "up",
           "qualifies": True, "target_price": None, "lo80": None, "hi80": None, "regime": "TRENDING"}
    row.update(extra)
    return row
