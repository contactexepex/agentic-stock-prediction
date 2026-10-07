"""The deterministic gate of the results-analyst's records (results_digest.py validate|add), modelled on
analytics/claim_rules.py: the release is a current one with text, each source id is one of its stored texts, each
quote (<= quote_max_words) is verbatim in that text, every number in a bullet's own words is stated in its quote
or matches one of the release's deterministic numbers, enums are valid, and the text never predicts prices or
recommends trades. Pure: the releases come in as `ReleaseView`s."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from marketbrief.analytics.claim_numbers import plain_number_tokens, quoted_numbers
from marketbrief.analytics.claim_rules import normalise
from marketbrief.results.constants import (
    ADVICE_WORDS,
    AGENT_FIELDS,
    BULLET_FIELDS,
    MSG_ADVICE,
    MSG_KIND_MISMATCH,
    MSG_NOT_DUE,
    MSG_NUMBER,
    MSG_QUOTE,
    MSG_REPEATED,
    MSG_SOURCE,
    PROMPT_VERSION_PATTERN,
    RELEASE_KINDS,
)
from marketbrief.results.sources import TextSource

PCT = "pct"
MARKER_UNITS = (PCT, "bps")
DIGITS = re.compile(r"\d[\d,]*(?:\.(\d+))?")


@dataclass
class ReleaseView:
    """What a record about one release may cite and state: its kind, stored texts by id and its numbers
    (name -> value; names ending in _pct are percentages) plus the digit tokens of its period labels."""

    kind: str
    sources: dict[str, TextSource]
    values: dict[str, float] = field(default_factory=dict)
    label_tokens: set[str] = field(default_factory=set)


def number_values(*blocks: dict) -> dict[str, float]:
    """Every numeric value (not bool) of the given blocks, by name."""
    out = {}
    for block in blocks:
        for name, value in (block or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[name] = float(value)
    return out


def stated_half_step(literal) -> float:
    """Half the last stated decimal place, scale applied: '25%' -> 0.5, '25.0%' -> 0.05, '$95.7 billion' -> 0.05
    billion. Trailing zeros of a whole number are not read as rounding ('30%' is 30 +- 0.5, never 25)."""
    found = DIGITS.search(literal.literal)
    if not found:
        return 0.0
    stated = float(found.group(0).replace(",", "")) or 1.0
    decimals = len(found.group(1) or "")
    return 0.5 * 10.0**-decimals * abs(literal.value / stated)


def stated_in_quote(literal, quote: str, tolerance: float) -> bool:
    """The quote states this number: a bare number as a digit token, a % or bps as the same marker, an amount as
    the same currency or a bare number (a quote need not print the currency), within the text's rounding."""
    if literal.unit is None:
        return re.sub(r"[^\d.]", "", literal.literal.replace(",", "")).strip(".") in plain_number_tokens(quote)
    return any(
        (stated.unit == literal.unit or (stated.unit is None and literal.unit not in MARKER_UNITS))
        and abs(stated.value - literal.value) <= tolerance
        for stated in quoted_numbers(quote)
    )


def number_ok(literal, quote: str, view: ReleaseView) -> bool:
    """A number of the bullet's text is fine when the quote states it, it is a digit of the period labels, or it
    equals a release number as rounded in the text (a % only a percentage, an amount only an amount)."""
    tolerance = stated_half_step(literal) + 1e-9
    if stated_in_quote(literal, quote, tolerance):
        return True
    if literal.unit is None and re.sub(r"[^\d.]", "", literal.literal.replace(",", "")).strip(".") in view.label_tokens:
        return True
    wanted_pct = literal.unit == PCT
    return any(
        abs(literal.value - value) <= tolerance
        for name, value in view.values.items()
        if name.endswith("_pct") == wanted_pct
    )


def bullet_errors(index: int, bullet, view: ReleaseView, conf: dict, release_id: str) -> list[str]:
    """Problems of one bullet."""
    where = f"bullet {index}"
    if not isinstance(bullet, dict):
        return [f"{where}: not a JSON object"]
    errors = [f"{where}: unknown field {name!r}" for name in bullet if name not in BULLET_FIELDS]
    errors += [
        f"{where}: missing {name}"
        for name in BULLET_FIELDS
        if not isinstance(bullet.get(name), str) or not bullet[name].strip()
    ]
    if errors:
        return errors
    topics = list(conf.get("topics") or [])
    if bullet["topic"] not in topics:
        errors.append(f"{where}: topic must be one of {', '.join(topics)} (got {bullet['topic']!r})")
    limit = int(conf.get("text_max_chars", 300))
    if len(bullet["text"]) > limit:
        errors.append(f"{where}: text must be at most {limit} characters")
    words = int(conf.get("quote_max_words", 40))
    if len(bullet["quote"].split()) > words:
        errors.append(f"{where}: quote must be at most {words} words")
    advice = ADVICE_WORDS.search(bullet["text"])
    if advice:
        errors.append(f"{where}: " + MSG_ADVICE.format(word=advice.group(0)))
    source = view.sources.get(bullet["source_id"])
    if source is None:
        return [*errors, f"{where}: " + MSG_SOURCE.format(source_id=bullet["source_id"], release_id=release_id)]
    if normalise(bullet["quote"]) not in normalise(source.text):
        errors.append(f"{where}: " + MSG_QUOTE.format(source_id=bullet["source_id"]))
    wrong = [
        number.literal for number in quoted_numbers(bullet["text"]) if not number_ok(number, bullet["quote"], view)
    ]
    if wrong:
        errors.append(f"{where}: " + MSG_NUMBER.format(numbers=wrong))
    return errors


def check_record(rec, views: dict[str, ReleaseView], seen: set[str], conf: dict) -> tuple[list[str], dict | None]:
    """Problems of one agent record (empty = valid) and, when valid, its bullets to store (source kind added)."""
    if not isinstance(rec, dict):
        return ["not a JSON object"], None
    errors = [f"unknown field {name!r}" for name in rec if name not in AGENT_FIELDS]
    errors += [f"missing {name}" for name in AGENT_FIELDS if rec.get(name) is None]
    if errors:
        return errors, None
    release_id = rec["release_id"]
    view = views.get(release_id) if isinstance(release_id, str) else None
    if view is None:
        return [MSG_NOT_DUE.format(release_id=release_id)], None
    if rec["kind"] not in RELEASE_KINDS or rec["kind"] != view.kind:
        errors.append(MSG_KIND_MISMATCH.format(kind=rec["kind"], release_id=release_id, expected=view.kind))
    if release_id in seen:
        errors.append(MSG_REPEATED.format(release_id=release_id))
    if not isinstance(rec["prompt_version"], str) or not re.fullmatch(PROMPT_VERSION_PATTERN, rec["prompt_version"]):
        errors.append(f"prompt_version must match {PROMPT_VERSION_PATTERN} (got {rec['prompt_version']!r})")
    bullets, limit = rec["bullets"], int(conf.get("max_bullets", 5))
    if not isinstance(bullets, list) or len(bullets) > limit:
        return [*errors, f"bullets must be a list of at most {limit}"], None
    for index, bullet in enumerate(bullets, 1):
        errors += bullet_errors(index, bullet, view, conf, release_id)
    if errors:
        return errors, None
    stored = [
        {**{name: bullet[name] for name in BULLET_FIELDS}, "source_kind": view.sources[bullet["source_id"]].kind}
        for bullet in bullets
    ]
    return [], {"release_id": release_id, "bullets": stored, "prompt_version": rec["prompt_version"]}
