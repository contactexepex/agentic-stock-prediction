"""Names of the stored data kinds (data/<market>/<kind>/...) and their file formats."""
KIND_NEWS = "news"
KIND_NEWS_RUNS = "news_runs"   # one row per collect_news.py run: its catch-up window and outcome
KIND_FUNDAMENTALS = "fundamentals"
KIND_SEC_TIMES = "sec_times"

NEWS_STORED_VIEW = "news_stored"   # the view over the stored news rows; `news` re-tags them (views.sql)
FILE_FORMAT_JSONL = "jsonl"
KIND_PRICES = "prices"
KIND_PRICE_SOURCES = "price_sources"
KIND_ADJUSTMENTS = "adjustments"
KIND_QUOTES = "quotes"
KIND_EVENTS = "events"
KIND_EARNINGS_ESTIMATES = "earnings_estimates"
KIND_FILINGS = "filings"
KIND_OPTIONS = "options"
KIND_INSIDERS = "insiders"
KIND_STAKES = "stakes"
KIND_HOLDINGS = "holdings"
EXT_CSV = "csv"
KIND_MACRO = "macro"
KIND_SHORTS = "shorts"
KIND_SHORT_INTEREST = "short_interest"
KIND_FPI = "fpi"
KIND_INDICES = "indices"
KIND_DEALS = "deals"
KIND_ANNOUNCEMENTS = "announcements"
KIND_FINANCIALS = "financials"
KIND_FLOWS = "flows"
KIND_DELIVERY = "delivery"

# ---------- WS4: paper portfolio (scripts/portfolio.py; marketbrief/portfolio/) ----------
KIND_PORTFOLIO_TRADES = "portfolio_trades"
KIND_WATCHLIST_REQUESTS = "watchlist_requests"

# ---------- W1: strategy lab and lifecycle kinds (docs/SPEC.md section 4; schemas in core/schema_lab.py and
# core/schema_lifecycle.py; docs/DATA_CATALOGUE.md) ----------
KIND_WATCHLIST_EVENTS = "watchlist_events"
KIND_COMMAND_LOG = "command_log"
KIND_STRATEGY_PREDICTIONS = "strategy_predictions"
KIND_STRATEGY_ABSTENTIONS = "strategy_abstentions"
KIND_PAPER_TRADES_SETTLED = "paper_trades_settled"
KIND_HEAD_TO_HEAD_PICKS = "head_to_head_picks"
KIND_TRADE_REASONS_AI = "trade_reasons_ai"
KIND_TRADE_CHECKS = "trade_checks"
KIND_EOD_ANALYSES = "eod_analyses"
KIND_RESEARCH_REVIEWS = "research_reviews"
KIND_NEWS_IMPACT = "news_impact"

# ---------- B2: strategy lab cost views (owner decisions 50-51; schema in core/schema_b2.py; docs/ws/b2.md) ----------
KIND_COST_VIEWS = "cost_views"
