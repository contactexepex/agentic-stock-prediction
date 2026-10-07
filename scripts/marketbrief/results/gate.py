"""The deterministic gate of the results-analyst's records (results_digest.py validate|add), modelled on
analytics/claim_rules.py: the release is a current one with text, each source id is one of its stored texts, each
quote (<= quote_max_words) is verbatim in that text, every number in a bullet's own words is stated in its quote
or matches one of the release's deterministic numbers, enums are valid, and the text never predicts prices or
recommends trades. Pure: the releases come in as `ReleaseView`s."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
from marketbrief.results.gate_numbers import wrong_numbers
from marketbrief.results.sources import TextSource


@dataclass
class ReleaseView:
    """What a record about one release may cite and state: its kind, stored texts by id and its numbers
    (name -> value; names ending in _pct are percentages) plus the years of its period labels."""

    kind: str
    sources: dict[str, TextSource]
    values: dict[str, float] = field(default_factory=dict)
    label_years: set[str] = field(default_factory=set)


def number_values(*blocks: dict) -> dict[str, float]:
    """Every numeric value (not bool) of the given blocks, by name."""
    out = {}
    for block in blocks:
        for name, value in (block or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[name] = float(value)
    return out


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
    words, least = int(conf.get("quote_max_words", 40)), int(conf.get("quote_min_words", 3))
    if not least <= len(bullet["quote"].split()) <= words:
        errors.append(f"{where}: quote must be {least} to {words} words")
    advice = ADVICE_WORDS.search(bullet["text"])
    if advice:
        errors.append(f"{where}: " + MSG_ADVICE.format(word=advice.group(0)))
    source = view.sources.get(bullet["source_id"])
    if source is None:
        return [*errors, f"{where}: " + MSG_SOURCE.format(source_id=bullet["source_id"], release_id=release_id)]
    if normalise(bullet["quote"]) not in normalise(source.text):
        errors.append(f"{where}: " + MSG_QUOTE.format(source_id=bullet["source_id"]))
    wrong = wrong_numbers(bullet["text"], bullet["quote"], view.values, view.label_years)
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
