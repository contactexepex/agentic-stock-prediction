"""Validation of the reflector's lessons: ids exist, word limit, every number matches the call or outcome."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

from marketbrief.constants.lessons import (
    AGENT_FIELDS,
    BOTH_KINDS,
    FACT_FIELDS,
    ID_RE,
    MAX_WORDS,
    MSG_COPIED_FACT_DIFFERS,
    MSG_DUPLICATE_LESSON_IN_FILE,
    MSG_FIELD_MUST_BE_TEXT,
    MSG_LESSON_ALREADY_STORED,
    MSG_LESSON_NUMBER_MATCHES_NOTHING,
    MSG_LESSON_WORD_COUNT,
    MSG_MISSING_AGENT_FIELD,
    MSG_NOT_A_JSON_OBJECT,
    MSG_PATH_DOES_NOT_EXIST,
    MSG_PREDICTION_NOT_SETTLED,
    MSG_RANGE_STILL_OPEN,
    MSG_RETURN_HAS_WRONG_SIGN,
    NUM_RE,
    PCT_KINDS,
    TIME_FIELDS,
)
from marketbrief.core.database import connect
from marketbrief.core.horizons import horizons
from marketbrief.pipeline.lessons.facts import settled, stored_ids


def allowed_numbers(fact: dict) -> list[tuple[float, str]]:
    """(value, what) pairs a lesson's text may cite, as absolute values."""
    allowed_values = [
        *((float(horizon), "horizon") for horizon in horizons()),
        (float(fact["horizon_days"]), "horizon"),
        (50.0, "band"),
        (80.0, "band"),
    ]
    if fact.get("actual_return") is not None:
        allowed_values.append((abs(100 * fact["actual_return"]), "return"))
    if fact.get("confidence") is not None:
        allowed_values += [(fact["confidence"], "confidence"), (100 * fact["confidence"], "confidence_pct")]
    for key in ("base_close", "entry_open", "target_close", "range_actual_close", "lo80", "lo50", "hi50", "hi80"):
        if fact.get(key) is not None:
            allowed_values.append((abs(fact[key]), key))
    for num in NUM_RE.findall(ID_RE.sub(" ", fact.get("rationale") or "")):  # numbers the stored rationale cites
        allowed_values.append((float(num[1].replace(",", "")), "rationale"))
    close = fact.get("range_actual_close")
    if close is not None:
        for key in ("lo80", "lo50", "hi50", "hi80"):
            if fact.get(key):
                allowed_values.append((abs(100 * (close / fact[key] - 1)), f"distance from {key}"))
    return allowed_values


def text_number_errors(text: str, fact: dict) -> list[str]:
    """Numbers in the lesson that match nothing in the call or its outcome (dates, ids, the ticker skipped)."""
    cleaned_text = text
    for number in [fact["prediction_id"], *(fact.get("evidence_ids") or [])]:
        cleaned_text = cleaned_text.replace(number, " ")
    cleaned_text = ID_RE.sub(" ", cleaned_text)
    cleaned_text = re.sub(rf"(?<![\w]){re.escape(fact['ticker'])}(?![\w])", " ", cleaned_text)
    errs = []
    for sign, num, pct in NUM_RE.findall(cleaned_text):
        # a percentage may only be a return, a % distance, confidence in %, a band name or a rationale
        # number; a plain number only a close, band edge, confidence, horizon or a rationale number
        allowed_values = [
            (allowed_value, what)
            for allowed_value, what in allowed_numbers(fact)
            if (what in PCT_KINDS or what.startswith("distance")) == bool(pct) or what in BOTH_KINDS
        ]
        number = float(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        tol = 0.5 * 10**-dec + 1e-9
        matches = [what for allowed_value, what in allowed_values if abs(number - allowed_value) <= tol]
        if not matches:
            errs.append(MSG_LESSON_NUMBER_MATCHES_NOTHING.format(sign=sign, num=num, unit=pct.strip()))
            continue
        if (
            sign
            and pct
            and "return" in matches
            and fact.get("actual_return")
            and not any(
                abs(number - allowed_value) <= tol
                for allowed_value, what in allowed_values
                if what.startswith("distance")
            )
        ):
            neg = sign in "-−"
            if neg != (fact["actual_return"] < 0):
                errs.append(MSG_RETURN_HAS_WRONG_SIGN.format(sign=sign, num=num, actual_return=fact["actual_return"]))
    return errs


def same(key: str, copied, stored) -> bool:
    """A copied fact equals the stored one (numbers to 1e-9, timestamps as instants)."""
    if key in TIME_FIELDS and isinstance(copied, str) and isinstance(stored, str):
        try:
            return pd.Timestamp(copied) == pd.Timestamp(stored)
        except ValueError:
            return False
    if isinstance(copied, bool) or isinstance(stored, bool):
        return copied is stored
    if isinstance(stored, float) or isinstance(copied, float):
        try:
            return (
                copied is not None
                and stored is not None
                and math.isclose(float(copied), float(stored), rel_tol=1e-9, abs_tol=1e-9)
            )
        except (TypeError, ValueError):
            return False
    return copied == stored


def agent_field_problems(record: dict) -> list[str]:
    """Unknown fields and missing or non-text agent fields of one lesson record."""
    errs = [f"unknown field {key!r}" for key in record if key not in AGENT_FIELDS and key not in FACT_FIELDS]
    for key in AGENT_FIELDS:
        if record.get(key) in (None, ""):
            errs.append(MSG_MISSING_AGENT_FIELD.format(key=key))
        elif not isinstance(record[key], str):
            errs.append(MSG_FIELD_MUST_BE_TEXT.format(key=key))
    return errs


def prediction_problems(prediction_id, facts: dict, stored: set[str], seen: set[str]) -> list[str]:
    """The cited prediction must exist, be settled, have no stored lesson and not repeat in the file."""
    if not isinstance(prediction_id, str):
        return []
    errs = []
    if prediction_id not in facts:
        errs.append(MSG_PREDICTION_NOT_SETTLED.format(prediction_id=prediction_id))
    elif facts[prediction_id] is None:
        errs.append(MSG_RANGE_STILL_OPEN.format(prediction_id=prediction_id))
    if f"lesson-{prediction_id}" in stored:
        errs.append(MSG_LESSON_ALREADY_STORED.format(prediction_id=prediction_id))
    if prediction_id in seen:
        errs.append(MSG_DUPLICATE_LESSON_IN_FILE.format(prediction_id=prediction_id))
    seen.add(prediction_id)
    return errs


def lesson_text_problems(text, record: dict, fact: dict | None) -> list[str]:
    """Word limit of the lesson text, copied facts equal to the stored ones, numbers matching the call."""
    errs = []
    if isinstance(text, str):
        word_count = len(text.split())
        if word_count == 0 or word_count > MAX_WORDS:
            errs.append(MSG_LESSON_WORD_COUNT.format(max_words=MAX_WORDS, word_count=word_count))
    if fact:
        for key in FACT_FIELDS:
            if key in record and not same(key, record[key], fact[key]):
                errs.append(MSG_COPIED_FACT_DIFFERS.format(key=key, copied=record[key], stored=fact[key]))
        if isinstance(text, str):
            errs += text_number_errors(text, fact)
    return errs


def validate_records(recs: list, facts: dict, stored: set[str]) -> tuple[list[dict], list[dict]]:
    """(valid full records, errors). facts = settled(); stored = lesson ids already in data/."""
    good, bad, seen = [], [], set()
    for index, rec in enumerate(recs, 1):
        if not isinstance(rec, dict):
            bad.append({"line": index, "prediction_id": None, "errors": [MSG_NOT_A_JSON_OBJECT]})
            continue
        pid = rec.get("prediction_id")
        fact = facts.get(pid) if isinstance(pid, str) else None
        text = rec.get("lesson")
        errs = agent_field_problems(rec) + prediction_problems(pid, facts, stored, seen)
        errs += lesson_text_problems(text, rec, fact)
        if errs:
            bad.append({"line": index, "prediction_id": pid, "errors": errs})
        else:
            good.append({**fact, "lesson": text.strip(), "prompt_version": rec["prompt_version"]})
    return good, bad


def read_file(path: Path) -> list:
    """One entry per non-empty line: the parsed object, or the raw text when it is not JSON
    (validate_records then rejects it as not a JSON object)."""
    if not path.exists():
        raise SystemExit(MSG_PATH_DOES_NOT_EXIST.format(path=path))
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                recs.append(line)
    return recs


def check(cfg: dict, path: Path) -> tuple[list[dict], list[dict], int]:
    """Read the reflector's file and validate its records against the settled calls."""
    con = connect(cfg["market"])
    recs = read_file(path)
    good, bad = validate_records(recs, settled(cfg, con), stored_ids(con))
    return good, bad, len(recs)
