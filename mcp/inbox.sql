-- The inbox of the web tier (docs/SPEC.md F10; ARCHITECTURE.md section 9; session B5).
-- Database market_brief_inbox in MotherDuck, written only with MOTHERDUCK_INBOX_TOKEN (its own service account, so a
-- leaked inbox token cannot touch market_brief). The tool layer (web/lib/tools/) appends; the importer (session B1:
-- `scripts/company.py import-inbox`, run by onboard.yml and the routines; scripts/marketbrief/lifecycle/inbox.py) reads
-- inbox.company_commands, validates with the same Python validators as the CLI and appends to data/. Rows are never
-- updated or deleted by the web tier. Idempotent: every statement is CREATE ... IF NOT EXISTS or ADD COLUMN IF NOT EXISTS.
-- The owner creates these tables once (docs/ws/b5.md, owner setup). tests/test_b5_tools.py checks the command_log
-- columns against the schema and runs the tool layer's statements (web/lib/tools/sql.ts) on a local DuckDB.

CREATE SCHEMA IF NOT EXISTS inbox;

-- One row per company command (add, deactivate, reactivate, set amount, delete), read by B1's importer. The first
-- eight columns are B1's (scripts/marketbrief/lifecycle/inbox.py INBOX_COLUMNS, an explicit SELECT): inbox_id = the
-- caller's idempotency key (unique per table by the primary key, and across both tables by the tool layer's claim
-- statement; a repeated key returns the first result);
-- arguments = the validated tool arguments (secret values scrubbed); actor = the identity the channel's auth gave,
-- never taken from arguments; command_id = the web tier's command id. B5's own columns follow (B1 ignores them):
-- preview = the identifiers the caller confirmed (add_company), agent, args_sha256 = sha256 of the arguments as JSON
-- with sorted keys (a reused key with other arguments is refused), slack_channel and slack_ts = the visible "request
-- received" message the Slack confirm step posted in #market-brief (null for other channels); after importing, the
-- importer passes them to B6's onboarding reply (scripts/alerts.py onboarding --channel --thread-ts).
CREATE TABLE IF NOT EXISTS inbox.company_commands (
    inbox_id VARCHAR PRIMARY KEY,
    market VARCHAR NOT NULL,
    tool VARCHAR NOT NULL,
    arguments JSON NOT NULL,
    actor VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    command_id VARCHAR,
    preview JSON,
    agent VARCHAR NOT NULL,
    args_sha256 VARCHAR NOT NULL,
    slack_channel VARCHAR,
    slack_ts VARCHAR
);

-- One row per other write request: today only add_paper_trade (kind portfolio_trades). NO IMPORTER YET: these rows
-- wait here until a portfolio importer (WS4, marketbrief/portfolio/) reads them; the caller sees "pending".
-- Same meanings as above; submitted_by is the actor.
CREATE TABLE IF NOT EXISTS inbox.requests (
    inbox_id VARCHAR PRIMARY KEY,
    kind VARCHAR NOT NULL,
    tool VARCHAR NOT NULL,
    market VARCHAR NOT NULL,
    arguments JSON NOT NULL,
    preview JSON,
    channel VARCHAR NOT NULL,
    submitted_by VARCHAR NOT NULL,
    agent VARCHAR NOT NULL,
    command_id VARCHAR NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    args_sha256 VARCHAR NOT NULL,
    slack_channel VARCHAR,
    slack_ts VARCHAR
);

-- Added after the first version (B6's onboarding replies), for tables created before these columns existed.
ALTER TABLE inbox.company_commands ADD COLUMN IF NOT EXISTS slack_channel VARCHAR;
ALTER TABLE inbox.company_commands ADD COLUMN IF NOT EXISTS slack_ts VARCHAR;
ALTER TABLE inbox.requests ADD COLUMN IF NOT EXISTS slack_channel VARCHAR;
ALTER TABLE inbox.requests ADD COLUMN IF NOT EXISTS slack_ts VARCHAR;

-- One row per command from the web tier's channels, the columns of the command_log kind
-- (scripts/marketbrief/core/schema_lifecycle.py). An OPERATIONAL log only (budgets, the owner's view of refusals):
-- it is NOT imported. The canonical data/<market>/command_log/ is written by B1's importer and the CLIs.
CREATE TABLE IF NOT EXISTS inbox.command_log (
    id VARCHAR NOT NULL,
    market VARCHAR,
    received_at TIMESTAMPTZ NOT NULL,
    channel VARCHAR NOT NULL,
    actor VARCHAR NOT NULL,
    agent VARCHAR NOT NULL,
    tool VARCHAR,
    kind VARCHAR,
    arguments JSON,
    idempotency_key VARCHAR,
    result VARCHAR NOT NULL,
    refusal_code VARCHAR,
    message VARCHAR,
    record_ids VARCHAR[],
    budget_left INTEGER,
    completed_at TIMESTAMPTZ
);

-- The owner's kill switch without a deploy: a row with enabled = false stops every call of that agent (agent '*'
-- stops all). Read on every call; the newest row per agent counts. Written by the owner in the MotherDuck UI.
CREATE TABLE IF NOT EXISTS inbox.controls (
    agent VARCHAR NOT NULL,
    enabled BOOLEAN NOT NULL,
    note VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL
);
