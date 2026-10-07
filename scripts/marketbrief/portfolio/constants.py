"""Names, enums and messages of the paper portfolio (WS4). Kind names live in constants/kinds.py (WS4 block)."""
from __future__ import annotations

FILE_PORTFOLIO_CONFIG = "portfolio.yaml"
DIR_WORK_PORTFOLIO = "work/portfolio"   # temp files before the append (CLAUDE.md data rule 2)

SIDE_BUY, SIDE_SELL, SIDE_CANCEL = "buy", "sell", "cancel"
TRADE_SIDES = (SIDE_BUY, SIDE_SELL)
BASIS_OPEN, BASIS_CLOSE, BASIS_MANUAL = "open", "close", "manual"
BASIS_ORDER = {BASIS_OPEN: 0, BASIS_MANUAL: 1, BASIS_CLOSE: 2}   # within a day: the open first, the close last
STATUS_REQUESTED = "requested"
TRADE_ID_PREFIX, REQUEST_ID_PREFIX = "pt", "wr"

TIER_STRONG_BUY, TIER_BUY, TIER_HOLD, TIER_SELL, TIER_STRONG_SELL = (
    "Strong Buy", "Buy", "Hold/No call", "Sell", "Strong Sell")
STRONG_TIERS = (TIER_STRONG_BUY, TIER_STRONG_SELL)
PROOF_PROVEN, PROOF_NOT_PROVEN = "proven", "not_proven"
LABEL_PAPER_ONLY = "Paper only — no proven edge yet"
LABEL_PROVEN = "Proven by the stored track record (config/portfolio.yaml proof)"
MSG_NO_STRONG = "No proven strong signals today"
SIMULATED_LABEL = "SIMULATED — paper-follow on stored bars, not real trades"

# validation errors (each a short plain sentence; the CLI prints them as a JSON list)
ERR_MARKET = "market {market!r} does not match the market config {config!r}"
ERR_TICKER = "{ticker} is not in the {market} watchlist (config/markets/{market}.yaml); use request-company"
ERR_SIDE = "side must be one of {allowed}"
ERR_QUANTITY = "quantity must be a positive number"
ERR_BASIS = "price_basis must be one of {allowed}"
ERR_SOURCE = "source must be one of {allowed}"
ERR_DATE = "{day} is not a session of the {market} calendar"
ERR_FUTURE = "trade_date {day} is after the run clock's date {today}"
ERR_NO_BAR = "no stored bar for {ticker} on {day} (as of {clock}); record it once the session's bar is collected"
ERR_PRICE_GIVEN = "a price is given only with price_basis manual"
ERR_PRICE_MISSING = "price_basis manual needs a positive price"
ERR_PRICE_RANGE = "manual price {price} is outside {ticker}'s stored low-high {low}-{high} on {day}"
ERR_DUPLICATE = "idempotency_key {key!r} was already used (trade or request {existing})"
ERR_SUPERSEDES_UNKNOWN = "supersedes {target!r}: no such trade in {market} as of the clock"
ERR_SUPERSEDES_DONE = "supersedes {target!r}: that trade is already cancelled or corrected by {by}"
ERR_SUPERSEDES_TICKER = "a correction must keep the ticker of the trade it replaces ({ticker})"
ERR_SHORT = "selling {quantity} {ticker} on {day} would leave {left} held (no paper short selling)"
ERR_REQUEST_NAME = "give a ticker or a name for the company"
ERR_REQUEST_LISTED = "{ticker} is already in the {market} watchlist"
