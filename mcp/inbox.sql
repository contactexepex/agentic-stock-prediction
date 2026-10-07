-- The inbox of the web tier (docs/SPEC.md F10; ARCHITECTURE.md section 9; session B5).
-- Database market_brief_inbox in MotherDuck, written only with MOTHERDUCK_INBOX_TOKEN (its own service account, so a
-- leaked inbox token cannot touch market_brief). The tool layer (web/lib/tools/) appends; the importer (session B1:
-- onboard.yml and the routine runs) reads, validates with the same Python validators as the CLIs, appends to data/
-- and records each inbox id in data/<market>/inbox_imports/. Rows are never updated or deleted by the web tier.
-- The owner creates these tables once (docs/ws/b5.md, owner setup). tests/test_b5_tools.py checks the command_log
-- columns against the schema and runs the tool layer's statements (web/lib/tools/sql.ts) on a local DuckDB.

CREATE SCHEMA IF NOT EXISTS inbox;

-- One row per write request. inbox_id = the caller's idempotency key (unique: a repeated key returns the first
-- result). kind: the data kind the import appends to (watchlist_events | portfolio_trades). arguments: the
-- validated tool arguments. preview: the resolved identifiers the caller confirmed (add_company), else null.
-- submitted_by: the identity the channel's auth gave, never taken from arguments. args_sha256: sha256 of the
-- arguments as JSON with sorted keys, so a reused key with other arguments is refused.
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
    args_sha256 VARCHAR NOT NULL
);

-- One row per command from the web tier's channels, the columns of the command_log kind
-- (scripts/marketbrief/core/schema_lifecycle.py); the import copies them to data/<market>/command_log/.
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
