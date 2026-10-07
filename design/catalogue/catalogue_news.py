"""News, news impact, results digests, market status, research review and the owner's portfolio (EXAMPLES only)."""
from __future__ import annotations


def news_items() -> list[dict]:
    """A news item as the pages show it: stored news + enrichment + verification status + headline history (Wave 0)."""
    return [
        {"id": "a41c9e07b2d35f18", "market": "us", "tickers": ["NVDA"], "primary_tickers": ["NVDA"],
         "title": "Nvidia wins multi-year data-centre order from cloud provider, sources say",
         "source": "Reuters", "source_domain": "reuters.com", "url": "https://www.reuters.com/technology/example-nvda",
         "published_at": "2026-09-29T21:10:00Z", "first_seen_at": "2026-09-29T22:47:05Z",
         "enrichment": {"event_type": "product", "materiality": "high", "sentiment": 0.6, "relevance": 0.9,
                        "novelty": 0.8, "urgency": "high", "priced_in": False, "analyzed_at": "2026-09-30T11:20:00Z"},
         "status": "corroborated", "status_as_of": "2026-09-30T11:15:00Z", "cluster_id": "nvda-20260929-order",
         "independent_origins": 2, "primary_ids": [],
         "headline_history": [
             {"title": "Nvidia said to win data-centre order", "seen_at": "2026-09-29T22:47:05Z"},
             {"title": "Nvidia wins multi-year data-centre order from cloud provider, sources say",
              "seen_at": "2026-09-30T02:47:11Z"}],
         "headline_history_status": "planned (Wave 0 news de-duplication, kind news_updates)"},
        {"id": "nse-ann-7781203", "market": "india", "tickers": ["RELIANCE"], "primary_tickers": ["RELIANCE"],
         "title": "Reliance Industries: board approves capital raise for retail subsidiary (exchange filing)",
         "source": "NSE announcement", "source_domain": "nseindia.com", "url": "https://nsearchives.nseindia.com/example.pdf",
         "published_at": "2026-09-29T13:05:00Z", "first_seen_at": "2026-09-29T13:20:40Z",
         "enrichment": {"event_type": "ma", "materiality": "high", "sentiment": 0.4, "relevance": 0.95,
                        "novelty": 0.9, "urgency": "medium", "priced_in": False, "analyzed_at": "2026-09-30T02:00:00Z"},
         "status": "confirmed_primary", "status_as_of": "2026-09-30T01:55:00Z", "cluster_id": "reliance-20260929-raise",
         "independent_origins": 1, "primary_ids": ["nse-ann-7781203"], "headline_history": [],
         "headline_history_status": "planned (Wave 0)"},
        {"id": "c0d2e4f6a8b1c3d5", "market": "us", "tickers": ["JPM"], "primary_tickers": ["JPM"],
         "title": "JPMorgan said to weigh sale of payments unit stake",
         "source": "Example Business Wire Blog", "source_domain": "example-blog.com", "url": "https://example-blog.com/jpm",
         "published_at": "2026-10-06T15:00:00Z", "first_seen_at": "2026-10-06T16:47:00Z",
         "enrichment": {"event_type": "ma", "materiality": "medium", "sentiment": 0.2, "relevance": 0.7,
                        "novelty": 0.7, "urgency": "low", "priced_in": False, "analyzed_at": "2026-10-07T11:20:00Z"},
         "status": "rumour", "status_as_of": "2026-10-07T11:15:00Z", "cluster_id": "jpm-20261006-stake",
         "independent_origins": 0, "primary_ids": [], "headline_history": [],
         "headline_history_status": "planned (Wave 0)"},
        {"id": "3a5bd4c4813eb044", "market": "us", "tickers": ["NVDA"], "primary_tickers": ["NVDA"],
         "title": "Should You Buy Nvidia Stock in October?", "source": "Yahoo Finance",
         "source_domain": "finance.yahoo.com",
         "url": "https://finance.yahoo.com/example", "published_at": "2026-10-07T11:22:00Z",
         "first_seen_at": "2026-10-07T12:28:07Z",
         "enrichment": {"event_type": "other", "materiality": "low", "sentiment": 0.0, "relevance": 0.3,
                        "novelty": 0.1, "urgency": "low", "priced_in": True, "analyzed_at": "2026-10-07T13:00:00Z"},
         "status": "promotional", "status_as_of": "2026-10-07T12:40:00Z", "cluster_id": "nvda-20261007-opinion",
         "independent_origins": 0, "primary_ids": [], "headline_history": [],
         "headline_history_status": "planned (Wave 0)"},
    ]


def news_impact(row) -> list[dict]:
    base = {"market": "us", "iso_week": "2026-W41", "as_of": "2026-10-10T14:00:00Z", "method_version": "ni-v1",
            "computed_at": "2026-10-10T14:00:00Z"}
    return [
        row("news_impact", id="ni-us-2026-W41-earnings-confirmed_primary-high-1", event_type="earnings",
            status="confirmed_primary", materiality="high", horizon_days=1, n_events=34, mean_abnormal_pct=1.12,
            ci_low_pct=0.21, ci_high_pct=2.03, mean_benchmark_pct=0.08, mean_sector_pct=0.15, enough=True,
            news_ids=["e1f0a2b3c4d5e6f7", "0a1b2c3d4e5f6a7b"], **base),
        row("news_impact", id="ni-us-2026-W41-product-corroborated-high-3", event_type="product",
            status="corroborated", materiality="high", horizon_days=3, n_events=21, mean_abnormal_pct=0.64,
            ci_low_pct=-0.42, ci_high_pct=1.70, mean_benchmark_pct=0.22, mean_sector_pct=0.31, enough=True,
            news_ids=["a41c9e07b2d35f18"], **base),
        row("news_impact", id="ni-us-2026-W41-ma-rumour-medium-1", event_type="ma", status="rumour",
            materiality="medium", horizon_days=1, n_events=4, mean_abnormal_pct=None, ci_low_pct=None,
            ci_high_pct=None, mean_benchmark_pct=None, mean_sector_pct=None, enough=False,
            news_ids=["c0d2e4f6a8b1c3d5"], **base),
    ]


def results_digests(row) -> list[dict]:
    return [row(
        "results_digests", id="JPM-results-2026-07-14", release_kind="results", ticker="JPM",
        release_at="2026-07-14T10:45:12Z", release_date="2026-07-14", release_timing="before_open",
        release_time_basis="sec_acceptance", period_end="2026-06-30", fiscal_label="Q2 2026", basis="consolidated",
        currency="USD", status="ok", numbers_status="ok", numbers_as_of="2026-08-04T20:15:00Z",
        numbers={"revenue": 46100000000.0, "net_profit": 15200000000.0, "eps_diluted": 5.31,
                 "net_margin_pct": 32.97, "revenue_yoy_pct": 6.42, "net_profit_yoy_pct": 4.83, "eps_yoy_pct": 7.27,
                 "revenue_qoq_pct": 1.98, "prev_year_period_end": "2025-06-30", "derived": False},
        consensus={"note": "context only", "status": "before_release", "eps_estimate": 5.05, "eps_reported": 5.31,
                   "surprise_pct": 5.15, "surprise_basis": "yahoo"},
        reaction={"from": "2026-07-11", "to": "2026-07-14", "stock_pct": 1.84, "benchmark_pct": 0.21,
                  "excess_pct": 1.63},
        bullets=[{"topic": "headline_numbers", "text": "Quarterly net income was $15.2 billion.",
                  "quote": "reported net income of $15.2 billion", "source_id": "0000019617-26-000101",
                  "source_kind": "sec_exhibit"},
                 {"topic": "guidance", "text": "Net interest income for the year is still expected near $95 billion.",
                  "quote": "we continue to expect net interest income of approximately $95 billion",
                  "source_id": "0000019617-26-000101", "source_kind": "sec_exhibit"}],
        source_ids=["0000019617-26-000101"],
        sources=[{"id": "0000019617-26-000101", "kind": "sec_8k", "doc": "ex99-1.htm",
                  "url": "https://www.sec.gov/Archives/edgar/data/19617/example/ex99-1.htm",
                  "available_at": "2026-07-14T10:45:12Z"}],
        state_key="texts:1|numbers:ok", inputs_until="2026-08-04T20:15:00Z", created_at="2026-08-05T11:50:00Z",
        prompt_version="results-v1", method_version="rd-v1")]


def market_status() -> list[dict]:
    """MarketStatus (api/openapi.yaml 1.0, rm.status) plus the new runs of SPEC section 7."""
    return [
        {"market": "india", "name": "India (NSE)", "as_of": "2026-10-06", "currency": "INR",
         "session": {"local_time": "2026-10-07T17:30+05:30", "trading_day": True, "session_date": "2026-10-07",
                     "previous_session": "2026-10-06", "calendar_covered": True,
                     "session_open_utc": "2026-10-07T03:45:00+00:00", "session_close_utc": "2026-10-07T10:00:00+00:00",
                     "in_session": False, "late_run": True},
         "regime": "EVENT_HEAVY",
         "runs": {"pre_open": {"at": "2026-10-07T02:10:00Z", "ok": True}, "intraday": [
                      {"at": "2026-10-07T05:43:00Z", "ok": True}, {"at": "2026-10-07T08:43:00Z", "ok": True}],
                  "post_close": {"at": None, "ok": None, "next_at": "2026-10-07T12:15:00Z"},
                  "news": {"at": "2026-10-07T10:17:00Z", "ok": True, "new_items": 37}},
         "freshness": {"state": "fresh", "built_at": "2026-10-07T10:31:00Z", "age_minutes": 29},
         "paper_label": "Paper only - no proven edge yet"},
        {"market": "us", "name": "US (NYSE/Nasdaq)", "as_of": "2026-10-06", "currency": "USD",
         "session": {"local_time": "2026-10-07T08:00-04:00", "trading_day": True, "session_date": "2026-10-07",
                     "previous_session": "2026-10-06", "calendar_covered": True,
                     "session_open_utc": "2026-10-07T13:30:00+00:00", "session_close_utc": "2026-10-07T20:00:00+00:00",
                     "in_session": False, "late_run": False},
         "regime": "TRENDING",
         "runs": {"pre_open": {"at": "2026-10-07T11:45:00Z", "ok": True}, "intraday": [],
                  "post_close": {"at": None, "ok": None, "next_at": "2026-10-07T22:15:00Z"},
                  "news": {"at": "2026-10-07T08:47:00Z", "ok": True, "new_items": 52}},
         "freshness": {"state": "fresh", "built_at": "2026-10-07T11:58:00Z", "age_minutes": 2},
         "paper_label": "Paper only - no proven edge yet"},
    ]


def research_review(row) -> list[dict]:
    return [row(
        "research_reviews", id="rr-us-2026-W41", market="us", iso_week="2026-W41", period_start="2026-10-05",
        period_end="2026-10-09",
        leaders=[{"scope": "rule", "strategy_id": "rule.model_news.v1", "net_pnl": 61.4, "trades": 38},
                 {"scope": "ai", "strategy_id": "ai.combined.opus.v1", "net_pnl": 48.9, "trades": 21}],
        findings=[{"text": "Corroborated product news added about 0.6 points over 3 sessions (21 events, interval "
                           "includes zero).", "cited_ids": ["ni-us-2026-W41-product-corroborated-high-3"]}],
        proposals=[{"proposal_id": "p-2026-W41-1", "kind": "threshold", "file": "config/strategies.yaml",
                    "diff": "+  - id: rule.model_news_p57.v1\n+    threshold: 0.57", "rationale":
                    "Trades between 0.55 and 0.57 lost after costs in 3 of 3 weeks.",
                    "cited_ids": ["rule.model_news.v1"], "status": "proposed"}],
        report_path="reports/us/research-2026-W41.md", prompt_version="director-v1",
        written_at="2026-10-10T14:20:00Z")]


def portfolio(eurusd: float, r2, default_amount) -> dict:
    """The owner's own paper portfolio (WS4 portfolio_trades + positions) with the EUR view of US trades (F1.11)."""
    eur_at_buy = 1.1650   # example EUR/USD on the buy date
    qty, buy, last = 3.0, 330.80, 333.63
    fx_fee_rate = 0.0025   # BUX provisional, EUR -> USD at the buy
    cost_usd = qty * buy
    value_usd = qty * last
    cost_eur = cost_usd / eur_at_buy * (1 + fx_fee_rate)
    value_eur = value_usd / eurusd
    return {
        "owner_trades": [
            {"id": "pt-us-20260930-AAPL-1", "market": "us", "ticker": "AAPL", "side": "buy", "quantity": qty,
             "price": buy, "price_basis": "open", "trade_date": "2026-09-30", "source": "dashboard",
             "idempotency_key": "own-aapl-0930", "entered_at": "2026-09-30T20:30:00Z", "note": "own test",
             "supersedes": None},
            {"id": "pt-india-20260930-RELIANCE-1", "market": "india", "ticker": "RELIANCE", "side": "buy",
             "quantity": 50.0, "price": 1182.0, "price_basis": "open", "trade_date": "2026-09-30", "source": "slack",
             "idempotency_key": "own-rel-0930", "entered_at": "2026-09-30T11:00:00Z", "note": None,
             "supersedes": None}],
        "positions": [
            {"market": "us", "ticker": "AAPL", "quantity": qty, "avg_price": buy, "last_close": last,
             "last_close_date": "2026-10-06", "currency": "USD", "cost": r2(cost_usd), "value": r2(value_usd),
             "pnl": r2(value_usd - cost_usd), "pnl_pct": r2((value_usd / cost_usd - 1) * 100),
             "eur_view": {"eurusd_at_buy": eur_at_buy, "eurusd_now": eurusd, "fx_fee_rate": fx_fee_rate,
                          "cost_eur": r2(cost_eur), "value_eur": r2(value_eur), "pnl_eur": r2(value_eur - cost_eur),
                          "fx_effect_eur": r2(value_usd / eurusd - value_usd / eur_at_buy),
                          "note": "rate change and BUX FX fee included; fee provisional"}},
            {"market": "india", "ticker": "RELIANCE", "quantity": 50.0, "avg_price": 1182.0, "last_close": 1218.0,
             "last_close_date": "2026-10-06", "currency": "INR", "cost": 59100.0, "value": 60900.0, "pnl": 1800.0,
             "pnl_pct": r2((1218.0 / 1182.0 - 1) * 100), "eur_view": None}],
        "default_amounts": default_amount, "paper": True,
        "head_to_head_portfolios": "see scoreboard_row.json rows with view head_to_head (per family and pick rule)"}
