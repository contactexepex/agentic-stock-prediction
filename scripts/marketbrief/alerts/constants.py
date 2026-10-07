"""Constants and message texts of the Slack notifications (B6)."""
from __future__ import annotations

KIND_SLACK_POSTS = "slack_posts"   # data/<market>/slack_posts/: one row per posted message part (the ledger)

# post kinds, each the first part of a post key
POST_MORNING = "morning"
POST_ALERTS = "alerts"
POST_CLOSE = "close"
POST_WEEKLY = "weekly"
POST_ONBOARDING = "onboarding"
POST_KINDS: tuple[str, ...] = (POST_MORNING, POST_ALERTS, POST_CLOSE, POST_WEEKLY, POST_ONBOARDING)
THREAD_KINDS: tuple[str, ...] = (POST_MORNING, POST_ALERTS, POST_CLOSE)   # posted into the day's thread

ENV_SLACK_BOT_TOKEN = "SLACK_BOT_TOKEN"
SETTING_CHANNEL_ID = "slack_channel_id"
SLACK_API = "https://slack.com/api/"

MAX_MESSAGE_CHARS = 3500   # one Slack message part; Slack truncates text above 40,000 and advises 4,000
TOP_PICKS = 5              # morning picks per market (SPEC F9, decision 30)
PICK_HORIZON = 1           # the picks are ranked at N+1 (decision 39)
WORK_DIR = "work"
DRY_RUN_DIR = "alerts_dryrun"   # under work/: the dry run's messages and its own ledger
DRY_RUN_TS_PREFIX = "dry"

METHOD_VERSION = "alerts-v1"

FAMILY_LABELS = {"rule": "Rule", "baseline": "Baseline", "ai": "AI"}
PICK_RULE_LABELS = {"best_expected_gain": "best expected gain", "highest_probability": "highest probability"}
MARKET_LABELS = {"india": "India", "us": "US"}
BAND_TEXT = {
    "above80": "above its 80% range", "below80": "below its 80% range",
    "above50": "above its 50% range", "below50": "below its 50% range", "inside50": "inside its 50% range",
}
FLAG_TEXT = {
    "outside_range": "outside its predicted range",
    "far_from_target": "far from its target",
    "against_prediction": "moving against the prediction",
}
STATUS_TEXT = {
    "settled": "settled", "no_entry": "no trade: no open price on the entry day",
    "skipped_price_above_amount": "no trade: one share costs more than the amount",
}

PAPER = "[Paper]"
LABEL_PAPER_ONLY = "Paper only — no proven edge yet."
MSG_NO_STRONG = "No proven strong signals today."
MSG_NO_PICKS = "No paper picks today: no strategy buys at N+1."
MSG_NO_PREDICTIONS = "No paper picks today: no strategy predictions are stored for this session."
MSG_NO_HEAD_TO_HEAD = "No head-to-head trades today."
MSG_NO_SETTLED = "No paper trades settled today."
MSG_FOOTER = "Research only, not investment advice. Paper trades are records, never orders."
MSG_CONTINUED = "(continued {part}/{parts})"

ONBOARDING_RESULT_TEXT = {
    "accepted": "Done",
    "pending": "Received, waiting for the import",
    "refused": "Not done",
    "duplicate": "Already done earlier (same request key)",
    "failed": "Failed",
}

MSG_NO_TOKEN = "SLACK_BOT_TOKEN not set: nothing posted (use --dry-run to write the messages to work/)"
MSG_NO_CHANNEL = "slack_channel_id missing in config/settings.yaml"
MSG_NOTHING = "nothing to post"
