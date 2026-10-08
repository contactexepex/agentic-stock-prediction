-- The assistant's conversation log (docs/SPEC.md F11; session B8, docs/ws/b8.md).
-- Schema `app` in the MotherDuck database market_brief_inbox, written with MOTHERDUCK_INBOX_TOKEN (the web tier's only
-- writable database: market_brief is read-only for Vercel). An OPERATIONAL log, not a fact store: never imported into
-- data/, kept 90 days (the web tier deletes older rows on each question). It holds each answer's real cost, so the
-- pages can show the spend; no money budget is enforced in code (owner decision 2026-10-08). Idempotent: every
-- statement is CREATE ... IF NOT EXISTS. The owner runs this file once in
-- market_brief_inbox (docs/ws/b8.md, owner setup); tests/test_b8_assistant.py runs it and every statement of
-- web/lib/assistant/sql.ts on a local DuckDB.

CREATE SCHEMA IF NOT EXISTS app;

-- One row per question, inserted before the first model call.
CREATE TABLE IF NOT EXISTS app.assistant_questions (
    id VARCHAR PRIMARY KEY,          -- ask-<market>-<YYYY-MM-DD>-<random>
    market VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,        -- dashboard | slack | claude_app
    actor VARCHAR NOT NULL,          -- the channel's auth identity (dashboard:owner, slack:U..., github:...)
    agent VARCHAR NOT NULL,
    question VARCHAR NOT NULL,       -- at most 500 characters, secret values scrubbed
    ticker VARCHAR,
    strategy_id VARCHAR,
    asked_at TIMESTAMPTZ NOT NULL,
    conversation_id VARCHAR NOT NULL -- the id of the conversation's first question (its own id for a new one)
);

-- One row per finished question (answered, not in the data, declined, stopped or failed) with its real cost.
CREATE TABLE IF NOT EXISTS app.assistant_answers (
    id VARCHAR PRIMARY KEY,          -- the question's id
    status VARCHAR NOT NULL,
    text VARCHAR NOT NULL,
    cited JSON NOT NULL,             -- [{id, kind, as_of, source}]
    sources JSON NOT NULL,           -- [{read_model, page_key, found, as_of}]
    not_in_data BOOLEAN NOT NULL,
    declined VARCHAR,
    model VARCHAR NOT NULL,
    input_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model_calls INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    cost_usd DOUBLE NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL
);
