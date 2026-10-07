"""Constants and messages of the company lifecycle (F8; docs/SPEC.md section 3, docs/ws/b1.md)."""
from __future__ import annotations

VALIDATOR_VERSION = "lifecycle-v1"
EVENT_ID_PREFIX = "we"
COMMAND_ID_PREFIX = "cmd"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
KEY_DIGITS = 8

EVENT_ADD, EVENT_DEACTIVATE, EVENT_REACTIVATE = "add", "deactivate", "reactivate"
EVENT_DELETE, EVENT_SET_AMOUNT = "delete", "set_amount"
STATE_ACTIVE, STATE_INACTIVE, STATE_DELETED = "active", "inactive", "deleted"
STATE_COLLECTED = "collected"   # active + inactive (the accessor's state for collectors)
CHANNEL_SEED, CHANNEL_CLI = "seed", "cli"
# the state each event leads to, from the states it is allowed in (None = never added, or deleted before)
TRANSITIONS: dict[str, tuple[tuple[str | None, ...], str | None]] = {
    EVENT_ADD: ((None, STATE_DELETED), STATE_ACTIVE),
    EVENT_DEACTIVATE: ((STATE_ACTIVE,), STATE_INACTIVE),
    EVENT_REACTIVATE: ((STATE_INACTIVE,), STATE_ACTIVE),
    EVENT_DELETE: ((STATE_ACTIVE, STATE_INACTIVE), STATE_DELETED),
    EVENT_SET_AMOUNT: ((STATE_ACTIVE, STATE_INACTIVE), None),   # None: state unchanged
}
IDENTITY_FIELDS = ("name", "exchange", "sector", "yahoo", "nse_symbol", "cik")

# The environment variable that switches the loader to one candidate company during onboarding (a JSON file with
# the candidate's identity): cfg tickers = only the candidate, no market-level symbols. Set only by onboarding.
ENV_CANDIDATE = "MB_LIFECYCLE_CANDIDATE"
ENV_INBOX_TOKEN = "MOTHERDUCK_INBOX_TOKEN"
INBOX_DATABASE = "market_brief_inbox"
FILE_LIFECYCLE_CONFIG = "lifecycle.yaml"
DIR_WORK_LIFECYCLE = "work/lifecycle"

TICKER_PATTERN = r"^[A-Z0-9.&-]{1,20}$"
KEY_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"

# refusal codes (mcp/tools.yaml add_company `refuses`, plus the lifecycle validator's own)
REFUSE_ETF, REFUSE_BSE_ONLY, REFUSE_UNKNOWN = "etf", "bse_only", "unknown_symbol"
REFUSE_ALREADY_ACTIVE, REFUSE_DELETED_NEEDS_ADD = "already_active", "deleted_needs_new_add"
REFUSE_DUPLICATE, REFUSE_VALIDATION = "duplicate_key", "validation_failed"

ERR_MARKET = "unknown market {market!r} (allowed: {allowed})"
ERR_TICKER = "ticker {ticker!r} is not a valid exchange symbol"
ERR_KEY = "idempotency key {key!r} must be 8-64 characters of A-Z a-z 0-9 _ -"
ERR_CHANNEL = "channel {channel!r} is not one of {allowed}"
ERR_REQUESTED_BY = "requested_by is required (the identity the channel's sign-in gave)"
ERR_EVENT = "event {event!r} is not one of {allowed}"
ERR_NOT_ON_WATCHLIST = "{ticker} was never added to the {market} watchlist"
ERR_TRANSITION = "{event} is not allowed for {ticker} in state {state}"
ERR_ALREADY_ACTIVE = "{ticker} is already on the {market} watchlist ({state}); use reactivate or set-amount"
ERR_DELETED_ONLY_ADD = "{ticker} was deleted; only a new add (with onboarding) brings it back"
ERR_AMOUNT = "amount must be a number >= 1 in the market currency, or empty for the default"
ERR_AMOUNT_ONLY = "amount is only set on add and set_amount"
ERR_CONFIRM = "delete needs the typed confirmation: --confirm must equal the ticker {ticker!r}"
ERR_CONFIRM_CHANNEL = "delete is only allowed from the dashboard or the command line (decisions 15, 20)"
ERR_EFFECTIVE_EARLIER = "effective_from {effective} is before {ticker}'s newest event ({newest})"
ERR_EFFECTIVE_RECORDED = "effective_from {effective} is before recorded_at {recorded} (an event never acts earlier)"
ERR_DUPLICATE = "idempotency key {key!r} was already used by {existing}"
ERR_IDENTITY = "the add event needs {field}"
ERR_EXCHANGE = "exchange {exchange!r} is not allowed in {market} (allowed: {allowed})"
ERR_SUPERSEDES = "supersedes {target!r}: no such event of {ticker}"
ERR_REASON = "reason is at most {limit} characters"
ERR_SEED_EXISTS = "the {market} watchlist already has seed events ({count}); nothing written"
ERR_SEED_NO_HISTORY = "no stored price history for {market}: the seed needs the start of stored history"
REASON_LIMIT = 200
SEED_REASON = "seeded from config/markets"

# onboarding checks (the add event's `onboarding` JSON: check -> ok | failed | skipped)
CHECK_IDENTIFIERS, CHECK_NOT_ETF, CHECK_EXCHANGE = "identifiers", "not_etf", "exchange"
CHECK_SECTOR, CHECK_BACKFILL_PRICES, CHECK_BACKFILL_NEWS = "sector", "backfill_prices", "backfill_news"
CHECK_BACKFILL_FILINGS, CHECK_BACKFILL_ANNOUNCEMENTS = "backfill_filings", "backfill_announcements"
CHECK_LONG_HISTORY, CHECK_COLLECT_GATE = "long_history", "collect_gate"
OK, FAILED, SKIPPED = "ok", "failed", "skipped"

# command_log results
RESULT_ACCEPTED, RESULT_REFUSED, RESULT_DUPLICATE, RESULT_FAILED = "accepted", "refused", "duplicate", "failed"
TOOL_OF_EVENT = {EVENT_ADD: "add_company", EVENT_DEACTIVATE: "deactivate_company",
                 EVENT_REACTIVATE: "reactivate_company", EVENT_SET_AMOUNT: "set_paper_amount",
                 EVENT_DELETE: "delete_company"}
EVENT_OF_TOOL = {tool: event for event, tool in TOOL_OF_EVENT.items()}
