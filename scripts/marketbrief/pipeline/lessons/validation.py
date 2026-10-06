"""Validation of the reflector's lessons: ids exist, word limit, every number matches the call or outcome."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
import pandas as pd
from marketbrief.core.database import connect
from marketbrief.constants.lessons import AGENT_FIELDS, BOTH_KINDS, FACT_FIELDS, ID_RE, MAX_WORDS, NUM_RE, PCT_KINDS, TIME_FIELDS
from marketbrief.pipeline.lessons.facts import settled, stored_ids


def allowed_numbers(f: dict) -> list[tuple[float, str]]:
    """(value, what) pairs a lesson's text may cite, as absolute values."""
    vals = [(1.0, "horizon"), (5.0, "horizon"), (float(f["horizon_days"]), "horizon"),
            (50.0, "band"), (80.0, "band")]
    if f.get("actual_return") is not None:
        vals.append((abs(100 * f["actual_return"]), "return"))
    if f.get("confidence") is not None:
        vals += [(f["confidence"], "confidence"), (100 * f["confidence"], "confidence_pct")]
    for k in ("base_close", "target_close", "range_actual_close", "lo80", "lo50", "hi50", "hi80"):
        if f.get(k) is not None:
            vals.append((abs(f[k]), k))
    for num in NUM_RE.findall(ID_RE.sub(" ", f.get("rationale") or "")):   # numbers the stored rationale cites
        vals.append((float(num[1].replace(",", "")), "rationale"))
    y = f.get("range_actual_close")
    if y is not None:
        for k in ("lo80", "lo50", "hi50", "hi80"):
            if f.get(k):
                vals.append((abs(100 * (y / f[k] - 1)), f"distance from {k}"))
    return vals


def text_number_errors(text: str, f: dict) -> list[str]:
    """Numbers in the lesson that match nothing in the call or its outcome (dates, ids, the ticker skipped)."""
    t = text
    for x in [f["prediction_id"], *(f.get("evidence_ids") or [])]:
        t = t.replace(x, " ")
    t = ID_RE.sub(" ", t)
    t = re.sub(rf"(?<![\w]){re.escape(f['ticker'])}(?![\w])", " ", t)
    errs = []
    for sign, num, pct in NUM_RE.findall(t):
        # a percentage may only be a return, a % distance, confidence in %, a band name or a rationale
        # number; a plain number only a close, band edge, confidence, horizon or a rationale number
        vals = [(v, what) for v, what in allowed_numbers(f)
                if (what in PCT_KINDS or what.startswith("distance")) == bool(pct) or what in BOTH_KINDS]
        x = float(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        tol = 0.5 * 10 ** -dec + 1e-9
        matches = [what for v, what in vals if abs(x - v) <= tol]
        if not matches:
            errs.append(f"number {sign}{num}{pct.strip()} in the lesson matches nothing in the call or its outcome")
            continue
        if sign and pct and "return" in matches and f.get("actual_return") and \
                not any(abs(x - v) <= tol for v, what in vals if what.startswith("distance")):
            neg = sign in "-−"
            if neg != (f["actual_return"] < 0):
                errs.append(f"return {sign}{num}% has the wrong sign (actual_return {f['actual_return']:+.6f})")
    return errs


def same(key: str, a, b) -> bool:
    """A copied fact equals the stored one (numbers to 1e-9, timestamps as instants)."""
    if key in TIME_FIELDS and isinstance(a, str) and isinstance(b, str):
        try:
            return pd.Timestamp(a) == pd.Timestamp(b)
        except ValueError:
            return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(b, float) or isinstance(a, float):
        try:
            return a is not None and b is not None and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b


def validate_records(recs: list, facts: dict, stored: set[str]) -> tuple[list[dict], list[dict]]:
    """(valid full records, errors). facts = settled(); stored = lesson ids already in data/."""
    good, bad, seen = [], [], set()
    for i, rec in enumerate(recs, 1):
        if not isinstance(rec, dict):
            bad.append({"line": i, "prediction_id": None, "errors": ["not a JSON object"]})
            continue
        pid = rec.get("prediction_id")
        errs = [f"unknown field {k!r}" for k in rec if k not in AGENT_FIELDS and k not in FACT_FIELDS]
        for k in AGENT_FIELDS:
            if rec.get(k) in (None, ""):
                errs.append(f"missing {k}")
            elif not isinstance(rec[k], str):
                errs.append(f"{k} must be text")
        f = facts.get(pid) if isinstance(pid, str) else None
        if not isinstance(pid, str):
            pass
        elif pid not in facts:
            errs.append(f"prediction {pid!r} does not exist or is not settled (no stored outcome)")
        elif f is None:
            errs.append(f"prediction {pid!r} is settled but its range is still open; wait for it")
        if isinstance(pid, str):
            if f"lesson-{pid}" in stored:
                errs.append(f"a lesson for {pid} is already stored")
            if pid in seen:
                errs.append(f"duplicate lesson for {pid} in this file")
            seen.add(pid)
        text = rec.get("lesson")
        if isinstance(text, str):
            n = len(text.split())
            if n == 0 or n > MAX_WORDS:
                errs.append(f"lesson must be 1-{MAX_WORDS} words (got {n})")
        if f:
            for k in FACT_FIELDS:
                if k in rec and not same(k, rec[k], f[k]):
                    errs.append(f"{k} is {rec[k]!r} but the stored value is {f[k]!r}")
            if isinstance(text, str):
                errs += text_number_errors(text, f)
        if errs:
            bad.append({"line": i, "prediction_id": pid, "errors": errs})
        else:
            good.append({**f, "lesson": text.strip(), "prompt_version": rec["prompt_version"]})
    return good, bad


def read_file(path: Path) -> list:
    """One entry per non-empty line: the parsed object, or the raw text when it is not JSON
    (validate_records then rejects it as not a JSON object)."""
    if not path.exists():
        raise SystemExit(f"{path} does not exist")
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                recs.append(line)
    return recs


def check(cfg: dict, path: Path) -> tuple[list[dict], list[dict], int]:
    con = connect(cfg["market"])
    recs = read_file(path)
    good, bad = validate_records(recs, settled(cfg, con), stored_ids(con))
    return good, bad, len(recs)
