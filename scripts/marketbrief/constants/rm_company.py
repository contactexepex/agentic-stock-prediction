"""Constants of the company pages' read models (B12; docs/ws/b12.md): 03-company (`rm.stock`, `rm.bars`,
`rm.lifecycle`, `rm.trades`) and 04-stock-strategies (`rm.stock_strategies`). The field lists are the catalogue
fields each page copies (design/mockups/03-company/notes.md and 04-stock-strategies/notes.md); nested
objects (ranking, candidates, reason_detail, enrichment, luck_test, ...) are copied whole, as the mockups do."""
from __future__ import annotations

RM_TRADES = "trades"
RM_STOCK_STRATEGIES = "stock_strategies"
OWNER = "B12"
MOCKUP_COMPANY = "design/mockups/03-company/data.json"
MOCKUP_STOCK_STRATEGIES = "design/mockups/04-stock-strategies/data.json"
# the company page's news: items about the company first seen in the NEWS_DAYS before the cut-off, the newest
# NEWS_MAX (the mockup sets no window; docs/ws/b12.md "Open questions")
NEWS_DAYS = 30
NEWS_MAX = 50
# the company page's calendar: from the session being predicted to EVENT_DAYS later (the mockup's reach ~7 weeks)
EVENT_DAYS = 60

# the stored sessions the company chart shows, up to the as-of date (the mockup's example holds 60)
BAR_SESSIONS = 250
# calendar days read back to find BAR_SESSIONS sessions (weekends and holidays included)
BAR_LOOKBACK_DAYS = 400

COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "state_since", "added_at", "amount",
                  "amount_overridden", "currency", "yahoo", "nse_symbol", "cik", "last_close", "last_close_date",
                  "change_pct", "agreement_n1", "open_trades")
STRATEGIES_COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "amount", "amount_overridden",
                             "currency", "last_close", "last_close_date", "change_pct", "agreement_n1", "open_trades")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
STRATEGIES_STRATEGY_FIELDS = ("id", "family", "name", "description", "compared_to", "differs_in", "parameters",
                              "threshold", "horizons", "live", "settled_trades")
LIFECYCLE_FIELDS = ("id", "event", "ticker", "market", "effective_from", "recorded_at", "amount", "reason",
                    "requested_by", "channel", "supersedes")
PICK_FIELDS = ("id", "market", "ticker", "made_at", "as_of_date", "session_date", "family", "pick_rule", "status",
               "strategy_id", "strongest_basis", "ranking", "horizon_days", "prediction_id", "base_close", "prob_up",
               "move_pct", "loss_pct", "costs_pct", "expected_gain_pct", "candidates", "amount", "currency")
# 04 adds the pick's method version
STRATEGIES_PICK_FIELDS = (*PICK_FIELDS, "method_version")
PREDICTION_FIELDS = ("id", "strategy_id", "family", "ticker", "made_at", "as_of_date", "session_date", "exit_date",
                     "horizon_days", "direction", "prob_up", "qualifies", "base_close", "target_price", "lo50", "hi50",
                     "lo80", "hi80", "range_widen", "regime", "quality")
STRATEGIES_PREDICTION_FIELDS = ("id", "strategy_id", "family", "ticker", "made_at", "as_of_date", "session_date",
                                "exit_date", "horizon_days", "direction", "prob_up", "confidence", "threshold",
                                "qualifies", "base_close", "target_price", "lo50", "hi50", "lo80", "hi80",
                                "range_widen", "model_prob", "agent_adjustment", "adjustment_reason", "evidence_ids",
                                "reason", "regime", "quality", "amount", "currency")
OPEN_TRADE_FIELDS = ("trade_id", "view", "prediction_id", "strategy_id", "family", "market", "ticker", "horizon_days",
                     "entry_date", "exit_date", "entry_price", "quantity", "amount", "currency", "target_price", "lo80",
                     "lo50", "hi50", "hi80", "last_price", "last_price_date", "unrealised_pnl", "unrealised_pct",
                     "to_target_pct", "paper")
CHECK_FIELDS = ("id", "check_id", "check_row_id", "check_at", "session_date", "market", "ticker", "trade_id",
                "prediction_id", "strategy_id", "view", "horizon_days", "entry_date", "exit_date", "session_number",
                "entry_price", "last_price", "ret_since_entry_pct", "target_price", "to_target_pct", "lo80", "lo50",
                "hi50", "hi80", "band", "target_z", "flags", "flagged", "quality", "target_reached",
                "target_reached_session", "high_since_entry_pct", "low_since_entry_pct", "sessions_left", "last_time")
SETTLED_FIELDS = ("id", "trade_id", "prediction_id", "strategy_id", "family", "view", "pick_rule", "market", "ticker",
                  "horizon_days", "made_at", "entry_date", "exit_date", "exit_date_actual", "status", "flags",
                  "amount", "currency", "entry_price", "exit_price", "quantity", "gross_pnl", "costs", "net_pnl",
                  "return_pct", "prob_up", "target_price", "lo80", "hi80", "range_hit", "target_reached",
                  "target_reached_session", "max_favourable_pct", "max_adverse_pct", "move_pct", "market_pct",
                  "sector_pct", "news_pct", "company_pct", "reason_code", "reason_codes", "news_ids", "reason_detail",
                  "regime", "settled_at")
REASON_FIELDS = ("id", "trade_id", "market", "ticker", "strategy_id", "session_date", "kind", "rank", "text",
                 "cited_ids", "reason_codes", "created_at")
NEWS_FIELDS = ("id", "market", "tickers", "primary_tickers", "title", "source", "source_domain", "url", "published_at",
               "first_seen_at", "enrichment", "status", "status_as_of", "cluster_id", "independent_origins",
               "primary_ids", "headline_history")
DIGEST_FIELDS = ("id", "release_kind", "ticker", "release_at", "release_date", "release_timing", "period_end",
                 "fiscal_label", "basis", "currency", "status", "numbers_status", "numbers_as_of", "numbers",
                 "consensus", "reaction", "bullets", "sources", "created_at")
CALENDAR_FIELDS = ("market", "date", "type", "name", "ticker", "timing", "reaction_sessions", "major", "widens",
                   "provisional", "release", "source", "event_id")
BAR_FIELDS = ("date", "open", "high", "low", "close", "volume", "adjusted")
COMPANY_ROW_FIELDS = ("scope", "market", "view", "strategy_id", "family", "ticker", "horizon_days", "trades",
                      "net_pnl", "win_rate", "sample_badge")
SCOREBOARD_FIELDS = ("scope", "market", "view", "basis", "strategy_id", "family", "ticker", "horizon_days", "trades",
                     "net_pnl", "mean_return_pct", "win_rate", "target_reached_rate", "median_reached_session",
                     "avg_target_error_pct", "range_hit_rate", "worst_losing_streak", "max_drawdown", "sample_badge",
                     "first_entry", "last_exit", "luck_test", "as_of")

SCOPE_STRATEGY = "strategy"
SCOPE_STRATEGY_COMPANY = "strategy_company"
ALL_HORIZONS = "all"
EVENT_TYPE_HOLIDAY = "holiday"
