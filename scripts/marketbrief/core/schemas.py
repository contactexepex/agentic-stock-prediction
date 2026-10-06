"""The single source of truth for data-kind schemas: kind -> (file format, column types).

The tables themselves live in schema_base, schema_filings and schema_sources; this module joins them."""

from __future__ import annotations

from marketbrief.constants.kinds import KIND_FUNDAMENTALS, KIND_SEC_TIMES
from marketbrief.core.schema_base import BASE_SCHEMAS, FEATURE_COLS, Schemas
from marketbrief.core.schema_filings import (
    ACCEPTED_KEYS,
    FUNDAMENTALS_SCHEMA,
    SEC_RELATIONSHIP_SCHEMAS,
    SEC_TIMES_SCHEMA,
)
from marketbrief.core.schema_sources import FREE_SOURCE_SCHEMAS, RELATION_SCHEMAS
from marketbrief.core.schema_verification import VERIFICATION_SCHEMAS


def build_schemas() -> Schemas:
    """All kinds' schemas. A relationship kind that another collector already defines (e.g. US Form 4
    rows in `insiders`) becomes the union of both column sets, the earlier column keeping its type."""
    schemas: Schemas = {
        **BASE_SCHEMAS,
        **SEC_RELATIONSHIP_SCHEMAS,
        KIND_SEC_TIMES: SEC_TIMES_SCHEMA,
        KIND_FUNDAMENTALS: FUNDAMENTALS_SCHEMA,
        **FREE_SOURCE_SCHEMAS,
        **VERIFICATION_SCHEMAS,
    }
    for kind, (file_format, columns) in RELATION_SCHEMAS.items():
        if kind in schemas:
            schemas[kind] = (schemas[kind][0], {**columns, **schemas[kind][1]})
        else:
            schemas[kind] = (file_format, columns)
    return schemas


SCHEMAS: Schemas = build_schemas()

__all__ = ["ACCEPTED_KEYS", "FEATURE_COLS", "RELATION_SCHEMAS", "SCHEMAS", "Schemas", "build_schemas"]
