"""The deviation explainer's gate (intraday_check.py validate|add), modelled on lessons.py validate: the check
row exists, is flagged and has no stored note; the text is 1-60 words, never predicts or recommends; every cited
id is one of the row's attribution candidates; the attribution enum is valid and backed by a cited id of its
kind; and every number in the text matches a stored measure of the row (or a number in a candidate's text)."""

from __future__ import annotations

import json
import re

from marketbrief.intraday.constants import (
    ATTRIBUTION_IDIOSYNCRATIC,
    ATTRIBUTION_UNEXPLAINED,
    ATTRIBUTIONS,
    EXPLAINER_FIELDS,
    FORBIDDEN_WORDS_RE,
    MSG_ALREADY_EXPLAINED,
    MSG_BAD_ATTRIBUTION,
    MSG_DUPLICATE_IN_FILE,
    MSG_FORBIDDEN_WORD,
    MSG_ID_NOT_CANDIDATE,
    MSG_MISSING_FIELD,
    MSG_NEEDS_CITATION,
    MSG_NOT_A_JSON_OBJECT,
    MSG_NOT_LIST,
    MSG_NOT_TEXT,
    MSG_NUMBER_MATCHES_NOTHING,
    MSG_PROMPT_VERSION,
    MSG_UNKNOWN_FIELD,
    MSG_UNKNOWN_ROW,
    MSG_WORD_COUNT,
    MSG_WRONG_SIGN,
    NUM_RE,
    SKIP_RE,
)

# measures stored as fractions (cited in %), measures cited as plain numbers
PCT_MEASURES = ("ret_since_open", "gap", "bench_ret", "sector_ret", "residual", "sector_residual", "sigma_1d")
SIGNED_PCT = ("ret_since_open", "gap", "bench_ret", "sector_ret", "residual", "sector_residual")
PLAIN_MEASURES = ("last_price", "open_price", "prev_close", "lo80_1d", "lo50_1d", "hi50_1d", "hi80_1d",
                  "lo80_5d", "hi80_5d", "beta")
SIGNED_PLAIN = ("move_z", "residual_z")
TEXT_FIELDS = ("title", "subject", "name")


def allowed_numbers(row: dict) -> list[tuple[float, str, bool, bool]]:
    """(value, what, is_percent, signed) a note on this row may cite."""
    out = [(1.0, "horizon", False, False), (5.0, "horizon", False, False),
           (50.0, "band", True, False), (80.0, "band", True, False), (50.0, "band", False, False),
           (80.0, "band", False, False)]
    out += measure_numbers(row)
    for call in row.get("calls") or []:
        out += call_numbers(call)
    for cand in row.get("candidates") or []:
        out += candidate_numbers(cand)
    return out


def measure_numbers(row: dict) -> list[tuple[float, str, bool, bool]]:
    """The row's own measures, and the last price's % distance from each band edge."""
    out = [(100 * row[key], key, True, key in SIGNED_PCT) for key in PCT_MEASURES if row.get(key) is not None]
    out += [(row[key], key, False, False) for key in PLAIN_MEASURES if row.get(key) is not None]
    out += [(row[key], key, False, True) for key in SIGNED_PLAIN if row.get(key) is not None]
    last = row.get("last_price")
    for key in ("lo80_1d", "lo50_1d", "hi50_1d", "hi80_1d", "lo80_5d", "hi80_5d"):
        if last and row.get(key):
            out.append((100 * (last / row[key] - 1), f"distance from {key}", True, True))
    return out


def call_numbers(call: dict) -> list[tuple[float, str, bool, bool]]:
    """An open call's return and z since entry, its entry open and model probability."""
    out = []
    if call.get("ret") is not None:
        out.append((100 * call["ret"], "call ret", True, True))
    if call.get("z") is not None:
        out.append((call["z"], "call z", False, True))
    if call.get("entry_price") is not None:
        out.append((call["entry_price"], "call entry_price", False, False))
    if call.get("prob_up") is not None:
        out += [(call["prob_up"], "call prob_up", False, False), (100 * call["prob_up"], "call prob_up", True, False)]
    return out


def candidate_numbers(cand: dict) -> list[tuple[float, str, bool, bool]]:
    """Numbers of one candidate: its moves (signed %; the cue's change is its `ret`) and numbers in its text."""
    out = []
    for key in ("ret", "residual"):
        if cand.get(key) is not None:
            out.append((100 * cand[key], f"{cand['kind']} {key}", True, True))
    if cand.get("beta") is not None:
        out.append((cand["beta"], "beta", False, False))
    if cand.get("amount") is not None:
        out.append((cand["amount"], "event amount", False, False))
    texts = [str(cand.get(key) or "") for key in TEXT_FIELDS] + [str(note) for note in cand.get("range_notes") or []]
    for text in texts:
        for _sign, num, _pct in re.findall(NUM_RE, re.sub(SKIP_RE, " ", text)):
            value = float(num.replace(",", ""))
            out += [(value, "candidate text", True, False), (value, "candidate text", False, False)]
    return out


def number_errors(text: str, row: dict, cited: list[str]) -> list[str]:
    """Numbers in the text that match no stored measure (dates, times, ids and the ticker skipped)."""
    cleaned = text
    for ident in sorted({*cited, *(row.get("candidate_ids") or []), row["id"]}, key=len, reverse=True):
        cleaned = cleaned.replace(ident, " ")
    cleaned = re.sub(SKIP_RE, " ", cleaned)
    cleaned = re.sub(rf"(?<![\w]){re.escape(row['ticker'])}(?![\w])", " ", cleaned)
    allowed, errs = allowed_numbers(row), []
    for sign, num, pct in re.findall(NUM_RE, cleaned):
        number = float(num.replace(",", ""))
        decimals = len(num.split(".")[1]) if "." in num else 0
        tol = 0.5 * 10**-decimals + 1e-9
        kind = [item for item in allowed if item[2] == bool(pct)]
        matches = [item for item in kind if abs(number - abs(item[0])) <= tol]
        if not matches:
            errs.append(MSG_NUMBER_MATCHES_NOTHING.format(sign=sign, num=num, unit=pct.strip()))
            continue
        if sign:
            negative = sign in "-−"
            signed = [item for item in matches if item[3]]
            if signed and not any(item[0] == 0 or (item[0] < 0) == negative for item in signed):
                errs.append(MSG_WRONG_SIGN.format(sign=sign, num=num, unit=pct.strip(), what=signed[0][1],
                                                  value=signed[0][0]))
    return errs


def field_errors(rec: dict) -> list[str]:
    """Unknown, missing and mistyped fields."""
    errs = [MSG_UNKNOWN_FIELD.format(key=key) for key in rec if key not in EXPLAINER_FIELDS]
    for key in EXPLAINER_FIELDS:
        if key == "cited_ids":
            if not isinstance(rec.get(key), list) or not all(isinstance(item, str) for item in rec[key]):
                errs.append(MSG_NOT_LIST)
        elif rec.get(key) in (None, ""):
            errs.append(MSG_MISSING_FIELD.format(key=key))
        elif not isinstance(rec[key], str):
            errs.append(MSG_NOT_TEXT.format(key=key))
    return errs


def text_errors(text: str, max_words: int) -> list[str]:
    """Word limit and the no-prediction / no-recommendation rule."""
    errs = []
    word_count = len(text.split())
    if word_count == 0 or word_count > max_words:
        errs.append(MSG_WORD_COUNT.format(max_words=max_words, word_count=word_count))
    for match in re.finditer(FORBIDDEN_WORDS_RE, text, flags=re.IGNORECASE):
        errs.append(MSG_FORBIDDEN_WORD.format(word=match.group(0)))
    return errs


def citation_errors(rec: dict, row: dict) -> list[str]:
    """Cited ids are the row's candidates; the attribution is an allowed value backed by a cited id of its kind."""
    cited, attribution = rec["cited_ids"], rec["attribution"]
    kinds = {cand["id"]: cand["kind"] for cand in row.get("candidates") or []}
    errs = [MSG_ID_NOT_CANDIDATE.format(cited=item) for item in cited if item not in kinds]
    if attribution not in ATTRIBUTIONS:
        errs.append(MSG_BAD_ATTRIBUTION.format(attribution=attribution, allowed=list(ATTRIBUTIONS)))
    elif attribution not in (ATTRIBUTION_IDIOSYNCRATIC, ATTRIBUTION_UNEXPLAINED) and not any(
            kinds.get(item) == attribution for item in cited):
        errs.append(MSG_NEEDS_CITATION.format(attribution=attribution))
    return errs


def validate_records(recs: list, rows: dict[str, dict], explained: set[str], settings: dict):
    """(valid records, errors). rows = stored flagged check rows by id; explained = row ids with a stored note;
    settings = config/intraday.yaml (`explainer`: max_words and the prompt_version the notes must carry)."""
    max_words, version = settings["explainer"]["max_words"], settings["explainer"]["prompt_version"]
    good, bad, seen = [], [], set()
    for index, rec in enumerate(recs, 1):
        if not isinstance(rec, dict):
            bad.append({"line": index, "check_row_id": None, "errors": [MSG_NOT_A_JSON_OBJECT]})
            continue
        row_ident = rec.get("check_row_id")
        errs = field_errors(rec)
        row = rows.get(row_ident) if isinstance(row_ident, str) else None
        if isinstance(row_ident, str):
            if row is None:
                errs.append(MSG_UNKNOWN_ROW.format(row_id=row_ident))
            if row_ident in explained:
                errs.append(MSG_ALREADY_EXPLAINED.format(row_id=row_ident))
            if row_ident in seen:
                errs.append(MSG_DUPLICATE_IN_FILE.format(row_id=row_ident))
            seen.add(row_ident)
        if isinstance(rec.get("prompt_version"), str) and rec["prompt_version"] != version:
            errs.append(MSG_PROMPT_VERSION.format(found=rec["prompt_version"], expected=version))
        if not errs and row is not None:
            errs += text_errors(rec["text"], max_words) + citation_errors(rec, row)
            errs += number_errors(rec["text"], row, rec["cited_ids"])
        if errs:
            bad.append({"line": index, "check_row_id": row_ident, "errors": errs})
        else:
            good.append({**rec, "text": rec["text"].strip()})
    return good, bad


def parse_lines(text: str) -> list:
    """One entry per non-empty line: the parsed object, or the raw line (rejected later)."""
    out = []
    for line in text.splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append(line)
    return out
