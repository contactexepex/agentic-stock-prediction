"""Column types of the news verification phase B kinds (docs/DESIGN.md section 3b)."""

from __future__ import annotations

from marketbrief.constants.verification import KIND_NEWS_CLAIMS, KIND_NEWS_VERIFIED, KIND_PRIMARY_TEXTS
from marketbrief.core.schema_base import Schemas

VERIFICATION_SCHEMAS: Schemas = {
    # Plain text of a primary source document (claims.py prepare): an SEC 8-K/6-K main document or its
    # EX-99 exhibits, cut at `claims.primary_max_chars` (truncated true). One row per document, written
    # once; available_at = the filing's acceptance time. Quotes of claims are checked against `text`.
    KIND_PRIMARY_TEXTS: (
        "jsonl",
        {
            "id": "VARCHAR",
            "primary_id": "VARCHAR",
            "ticker": "VARCHAR",
            "source": "VARCHAR",
            "form": "VARCHAR",
            "doc": "VARCHAR",
            "doc_type": "VARCHAR",
            "url": "VARCHAR",
            "available_at": "TIMESTAMPTZ",
            "fetched_at": "TIMESTAMPTZ",
            "text": "VARCHAR",
            "chars": "INTEGER",
            "truncated": "BOOLEAN",
            "content_hash": "VARCHAR",
            "method_version": "VARCHAR",
        },
    ),
    # One statement of one fact by one source (claim-checker agent, gated and appended by claims.py):
    # id = <cluster_id>|<fact_key>|<quote_source_id>. Statements of one fact share fact_key. quote (<= 40
    # words) is verbatim in the source's stored text (quote_field: extract | title | primary);
    # value_text is the literal in the quote that equals value_num. source_kind, quote_field,
    # value_text, source_available_at (when its stored text was available to us) and source_published_at
    # (when the source was public: SEC acceptance, NSE dissemination, news publication) are computed by
    # claims.py, never copied from the agent.
    KIND_NEWS_CLAIMS: (
        "jsonl",
        {
            "id": "VARCHAR",
            "cluster_id": "VARCHAR",
            "cluster_row_id": "VARCHAR",
            "ticker": "VARCHAR",
            "fact_key": "VARCHAR",
            "claim_type": "VARCHAR",
            "subject": "VARCHAR",
            "predicate": "VARCHAR",
            "stance": "VARCHAR",
            "value_num": "DOUBLE",
            "unit": "VARCHAR",
            "value_text": "VARCHAR",
            "period": "VARCHAR",
            "effective_date": "DATE",
            "quote": "VARCHAR",
            "quote_source_id": "VARCHAR",
            "quote_field": "VARCHAR",
            "source_kind": "VARCHAR",
            "news_ids": "VARCHAR[]",
            "attribution": "VARCHAR",
            "source_available_at": "TIMESTAMPTZ",
            "source_published_at": "TIMESTAMPTZ",
            "extracted_at": "TIMESTAMPTZ",
            "prompt_version": "VARCHAR",
            "method_version": "VARCHAR",
        },
    ),
    # Verification status (news_status.py), appended per run when new or changed: one row per cluster
    # (level cluster, claim_id null) and one per fact (level claim, claim_id = fact_key). Every input
    # (cluster row, claims by extracted_at, sources by availability) is <= inputs_until <= as_of. Read
    # through news_verified_asof(ts) / news_status_ids_asof(ts). status_ids/id_statuses are parallel
    # lists: each news id of the cluster with its own status (the cluster's, unless the id is
    # promotional, unvetted, opinion or disagrees with a filing). conflicts: JSON [{value, unit, ids}].
    KIND_NEWS_VERIFIED: (
        "jsonl",
        {
            "id": "VARCHAR",
            "as_of": "TIMESTAMPTZ",
            "cluster_id": "VARCHAR",
            "cluster_row_id": "VARCHAR",
            "claim_id": "VARCHAR",
            "level": "VARCHAR",
            "ticker": "VARCHAR",
            "status": "VARCHAR",
            "primary_ids": "VARCHAR[]",
            "outlet_ids": "VARCHAR[]",
            "mismatch_ids": "VARCHAR[]",
            "status_ids": "VARCHAR[]",
            "id_statuses": "VARCHAR[]",
            "independent_origins": "INTEGER",
            "unread_vetted_origins": "INTEGER",
            "origins": "VARCHAR[]",
            "conflicts": "JSON",
            "flags": "VARCHAR[]",
            "first_reported_at": "TIMESTAMPTZ",
            "confirmed_at": "TIMESTAMPTZ",
            "inputs_until": "TIMESTAMPTZ",
            "state_hash": "VARCHAR",
            "method_version": "VARCHAR",
        },
    ),
}
