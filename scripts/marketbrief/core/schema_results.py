"""Column types of the results digests kind (WS6; scripts/results_digest.py, docs/ws/ws6.md)."""

from __future__ import annotations

from marketbrief.core.schema_base import Schemas
from marketbrief.results.constants import KIND_RESULTS_DIGESTS

RESULTS_SCHEMAS: Schemas = {
    # One digest of one release (results_digest.py add), appended when new or when its inputs changed
    # (state_key: the stored texts and numbers status). id = release id: <TICKER>-results-<period end> (India),
    # <TICKER>-results-<release date> (US), <TICKER>-concall-<announcement id | release date>; the newest row
    # per id wins (results_digests_asof). Deterministic, computed by the script: numbers (as of numbers_as_of:
    # the release time, or the first 10-Q/10-K of the quarter in the US; a later restatement is never used),
    # consensus (the newest Yahoo point collected before release_at; context only), reaction (close-to-close
    # from the session before the earnings window to the latest close by created_at). bullets (JSON list of
    # {topic, text, quote, source_id, quote_field}) are the results-analyst's, each quote verbatim in a stored
    # text. sources: JSON [{id, kind, doc, url, available_at}]. inputs_until = the newest input's availability.
    KIND_RESULTS_DIGESTS: (
        "jsonl",
        {
            "id": "VARCHAR",
            "release_kind": "VARCHAR",
            "ticker": "VARCHAR",
            "release_at": "TIMESTAMPTZ",
            "release_date": "DATE",
            "release_timing": "VARCHAR",
            "release_time_basis": "VARCHAR",
            "period_end": "DATE",
            "fiscal_label": "VARCHAR",
            "basis": "VARCHAR",
            "currency": "VARCHAR",
            "status": "VARCHAR",
            "numbers_status": "VARCHAR",
            "numbers_as_of": "TIMESTAMPTZ",
            "numbers": "JSON",
            "consensus": "JSON",
            "reaction": "JSON",
            "bullets": "JSON",
            "source_ids": "VARCHAR[]",
            "sources": "JSON",
            "state_key": "VARCHAR",
            "inputs_until": "TIMESTAMPTZ",
            "created_at": "TIMESTAMPTZ",
            "prompt_version": "VARCHAR",
            "method_version": "VARCHAR",
        },
    ),
}
