"""The deterministic gate of the claim-checker's records (claims.py validate|add): ids, enums, verbatim
quotes and the numbers in each claim. Pure: the stored sources come in as a `ClaimSources` map."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

from marketbrief.analytics.claim_numbers import literal_for, plain_number_tokens
from marketbrief.constants.verification import (ATTRIBUTIONS, CLAIM_TYPES, FACT_KEY_PATTERN, METHOD_VERSION_CLAIMS,
                                                QUOTE_MAX_WORDS, SOURCE_ARTICLE, STANCE_AFFIRMS, STANCES, UNITS)

AGENT_FIELDS = ("cluster_id", "fact_key", "claim_type", "subject", "predicate", "stance", "value_num", "unit",
                "period", "effective_date", "quote", "quote_source_id", "attribution", "news_ids", "prompt_version")
REQUIRED = ("cluster_id", "fact_key", "claim_type", "subject", "predicate", "quote", "quote_source_id",
            "attribution", "prompt_version")
TEXT_LIMITS = {"subject": 200, "predicate": 300, "period": 40}
QUOTE_CHARS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


@dataclass
class SourceText:
    """One citable source of a cluster: its kind (article | filing | announcement), its texts by field
    (extract, title, primary) and when it became available to us."""
    kind: str
    fields: dict[str, str]
    available_at: str


@dataclass
class ClusterSources:
    """What a claim about one cluster may cite: the cluster row, its news ids and its sources by id."""
    cluster_row_id: str
    ticker: str
    news_ids: set[str]
    sources: dict[str, SourceText] = field(default_factory=dict)


def normalise(text: str | None) -> str:
    """Text for the verbatim comparison: typographic quotes and dashes unified, whitespace collapsed."""
    return re.sub(r"\s+", " ", (text or "").translate(QUOTE_CHARS)).strip()


def quote_field(quote: str, source: SourceText) -> str | None:
    """The field of the source that holds the quote verbatim (after normalising), or None."""
    wanted = normalise(quote)
    return next((name for name, text in source.fields.items() if wanted and wanted in normalise(text)), None)


def claim_id(rec: dict) -> str:
    """<cluster_id>|<fact_key>|<quote_source_id>: one statement of one fact by one source."""
    return f"{rec['cluster_id']}|{rec['fact_key']}|{rec['quote_source_id']}"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def field_errors(rec: dict) -> list[str]:
    """Schema, enum and text-length problems of one record (no source lookups)."""
    errors = [f"unknown field {k!r}" for k in rec if k not in AGENT_FIELDS]
    errors += [f"missing {k}" for k in REQUIRED if rec.get(k) in (None, "")]
    if errors:
        return errors
    if not re.fullmatch(FACT_KEY_PATTERN, str(rec["fact_key"])):
        errors.append(f"fact_key must match {FACT_KEY_PATTERN} (got {rec['fact_key']!r})")
    for key, allowed in (("claim_type", CLAIM_TYPES), ("attribution", ATTRIBUTIONS),
                         ("stance", STANCES)):
        value = rec.get(key, STANCE_AFFIRMS if key == "stance" else None)
        if value not in allowed:
            errors.append(f"{key} must be one of {', '.join(allowed)} (got {value!r})")
    for key, limit in TEXT_LIMITS.items():
        if rec.get(key) is not None and (not isinstance(rec[key], str) or len(rec[key]) > limit):
            errors.append(f"{key} must be text of at most {limit} characters")
    if not isinstance(rec["quote"], str) or len(rec["quote"].split()) > QUOTE_MAX_WORDS:
        errors.append(f"quote must be text of at most {QUOTE_MAX_WORDS} words")
    if rec.get("effective_date") is not None:
        try:
            date.fromisoformat(str(rec["effective_date"]))
        except ValueError:
            errors.append(f"effective_date must be YYYY-MM-DD (got {rec['effective_date']!r})")
    if not isinstance(rec["prompt_version"], str):
        errors.append("prompt_version must be text")
    return errors


def number_errors(rec: dict) -> tuple[list[str], str | None]:
    """The claim's value must be stated in its quote, and every number in subject and predicate too.
    Returns the problems and the literal of the quote that states value_num."""
    errors, literal = [], None
    value, unit = rec.get("value_num"), rec.get("unit")
    if (value is None) != (unit is None):
        errors.append("value_num and unit go together (both or neither)")
    elif value is not None:
        if not _is_number(value):
            errors.append(f"value_num must be a number (got {value!r})")
        elif unit not in UNITS:
            errors.append(f"unit must be one of {', '.join(UNITS)} (got {unit!r})")
        else:
            found = literal_for(float(value), unit, rec["quote"])
            if found is None:
                errors.append(f"value_num {value} {unit} is not a number stated in the quote")
            else:
                literal = found.literal
    in_quote = plain_number_tokens(rec["quote"])
    for key in ("subject", "predicate"):
        missing = sorted(plain_number_tokens(rec.get(key)) - in_quote)
        if missing:
            errors.append(f"numbers in {key} not in the quote: {missing}")
    return errors, literal


def check_claim(rec, clusters: dict[str, ClusterSources], seen: set[str]) -> tuple[list[str], dict | None]:
    """Problems of one claim-checker record (empty = valid) and, when valid, the record to store
    (computed fields added: id, cluster_row_id, ticker, source_kind, quote_field, value_text, news_ids,
    source_available_at, method_version; extracted_at is set when it is appended)."""
    if not isinstance(rec, dict):
        return ["not a JSON object"], None
    errors = field_errors(rec)
    if errors:
        return errors, None
    cluster = clusters.get(rec["cluster_id"])
    if cluster is None:
        return [f"cluster_id {rec['cluster_id']!r} is not a current cluster"], None
    source = cluster.sources.get(rec["quote_source_id"])
    if source is None:
        return [f"quote_source_id {rec['quote_source_id']!r} is not an item or stored primary source of "
                f"cluster {rec['cluster_id']}"], None
    where = quote_field(rec["quote"], source)
    if where is None:
        errors.append(f"quote not found verbatim in the stored text of {rec['quote_source_id']}")
    more, literal = number_errors(rec)
    errors += more
    news_ids = rec.get("news_ids")
    if news_ids is None:
        news_ids = [rec["quote_source_id"]] if source.kind == SOURCE_ARTICLE else []
    if not isinstance(news_ids, list) or not all(isinstance(x, str) for x in news_ids):
        errors.append("news_ids must be a list of ids")
    else:
        unknown = sorted(set(news_ids) - cluster.news_ids)
        if unknown:
            errors.append(f"news_ids not in cluster {rec['cluster_id']}: {unknown}")
    cid = claim_id(rec)
    if cid in seen:
        errors.append(f"claim {cid} already stored or repeated in the file")
    if errors:
        return errors, None
    stored = {k: rec.get(k) for k in AGENT_FIELDS}
    stored.update({"id": cid, "cluster_row_id": cluster.cluster_row_id, "ticker": cluster.ticker,
                   "stance": rec.get("stance", STANCE_AFFIRMS), "value_text": literal, "quote_field": where,
                   "source_kind": source.kind, "news_ids": sorted(news_ids),
                   "source_available_at": source.available_at, "method_version": METHOD_VERSION_CLAIMS})
    return [], stored
