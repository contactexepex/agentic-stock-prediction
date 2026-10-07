"""Names, versions, settings and messages of the strategy lab (B2). Enums of the stored kinds live in
marketbrief/contracts/protocol.py (W1); kind names in constants/kinds.py."""
from __future__ import annotations

ENGINE_VERSION = "engine-v1"      # paper_trades_settled.method_version
LAB_VERSION = "lab-v1"            # strategy_predictions / head_to_head_picks.method_version
NEWS_IMPACT_VERSION = "ni-v1"

FAMILY_RULE, FAMILY_BASELINE, FAMILY_AI = "rule", "baseline", "ai"
SIGNAL_MODEL, SIGNAL_ALWAYS_UP, SIGNAL_MOMENTUM = "model", "always_up", "momentum"
UP, DOWN = "up", "down"
VIEW_ACCURACY, VIEW_HEAD_TO_HEAD = "accuracy", "head_to_head"
PICK_GAIN, PICK_PROBABILITY = "best_expected_gain", "highest_probability"
STATUS_PICKED, STATUS_NO_CANDIDATE = "picked", "no_candidate"
BASIS_PER_COMPANY, BASIS_ALL = "per_company", "all_companies"
STATUS_SETTLED, STATUS_NO_ENTRY, STATUS_SKIPPED = "settled", "no_entry", "skipped_price_above_amount"
FLAG_EXIT_DELAYED, FLAG_SPLIT, FLAG_RESETTLED = "exit_delayed", "split_in_window", "resettled"
QUALITY_BLOCKED = "BLOCKED"
FILTERED_REGIMES = ("UNSTABLE", "EVENT_HEAVY")   # regime_filter: no trades in these (F2.1)
VERIFIED_STATUSES = ("confirmed_primary", "corroborated")   # news counted in the automatic reason (F1.10)
EARNINGS_BLOCK_DAYS = 1                           # no prediction with days_to_earnings <= 1 (F2.6)
ABSTAIN_BLOCKED, ABSTAIN_EARNINGS, ABSTAIN_ABSTAINED = "blocked_quality", "earnings_window", "abstained"

# Normal quantile of the 80% band edge (the band is the 10%..90% range of the exit close).
Z80 = 1.2815515655446004
PERCENT = 100.0
MONEY_DIGITS, PCT_DIGITS, PROB_DIGITS, PRICE_DIGITS = 2, 4, 4, 4

# Scoreboard and go-live bar (F7; proposals of the spec until the owner sets them at the first review).
MIN_RANKED_TRADES = 20            # fewer settled trades: sample_badge too_few_to_rank
GO_LIVE_TRADES = 300
GO_LIVE_MONTHS = 2.0
DRAWDOWN_LIMIT_AMOUNTS = 10       # max drawdown proposal: 10 x the market's default amount
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_ALPHA = 0.05
NEWS_IMPACT_MIN_EVENTS = 10       # fewer: "not enough events yet" (enough false)
DAYS_PER_MONTH = 30.4375

MSG_NO_HORIZON_SCORES = ("per-horizon model scores or ranges are not available yet ({error}); session B10 builds "
                         "contracts/horizons.py. Nothing written.")
MSG_NO_CROSS_SCORE = "no cross-market model score for this horizon (needs a cross_market model variant, B10)"
MSG_NOT_LOCKED = "made_at or first commit not before the open of D (F1.8): refused"
MSG_NO_EURUSD = "no stored EUR/USD close by {when}: the BUX order fee cannot be converted"
REASON_NOTE_SKIPPED = "one share at {price} costs more than the amount {amount}"
