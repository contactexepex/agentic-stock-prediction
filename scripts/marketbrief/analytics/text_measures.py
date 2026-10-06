"""Measures of an article's text (deterministic, no LLM): sentences, normalised numbers, attribution phrases and
the MinHash signature of its 6-word shingles for copy detection. Article text is untrusted data: it is only
measured, never followed as instructions, and never stored (at most 3 key sentences of at most 40 words)."""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from functools import lru_cache

from marketbrief.constants.articles import (
    HEX_DIGITS_PER_HASH,
    KEY_SENTENCE_WORDS,
    KEY_SENTENCES,
    MAX_NUMBERS,
    MIN_SENTENCE_WORDS,
    MINHASH_SEED,
    NUM_PERM,
    SHINGLE,
)
from marketbrief.constants.verification import CURRENCY_UNITS

ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
GLUED_PARAGRAPHS = re.compile(r"(?<=[A-Za-z0-9]{2}[.!?])(?=[A-Z][A-Za-z])")  # 'said.The', 'post.HDFC'
SENTENCE_BREAK = re.compile(r"(?<=[.!?])[\"'”’)]?\s+(?=[\"'“‘(]?[A-Z0-9₹$])")
NUMBER = re.compile(
    r"(?P<cur>US\$|\$|₹|Rs\.?\s?|INR\s?|USD\s?|€|£)?\s?"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<scale>lakh crore|trillion|billion|million|thousand|crore|lakh|tn|bn|mn|cr|k|b|m)\b)?"
    r"\s?(?P<pct>%|per ?cent\b|percent\b|bps\b|basis points\b)?",
    re.I,
)
SCALES = {
    "trillion": 1e12,
    "tn": 1e12,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "million": 1e6,
    "mn": 1e6,
    "m": 1e6,
    "thousand": 1e3,
    "k": 1e3,
    "crore": 1e7,
    "cr": 1e7,
    "lakh": 1e5,
    "lakh crore": 1e12,
}
CURRENCIES = {
    "$": "usd",
    "us$": "usd",
    "usd": "usd",
    "₹": "inr",
    "rs": "inr",
    "rs.": "inr",
    "inr": "inr",
    "€": "eur",
    "£": "gbp",
}
AMBIGUOUS_SCALES = ("m", "b", "k")  # "5m" alone is ambiguous (minutes, metres)
UNIT_PERCENT, UNIT_BASIS_POINTS = "pct", "bps"
MIN_PLAIN_NUMBER, MIN_DISTINCTIVE_NUMBER = 10, 1000
YEAR_RANGE = (1900, 2100)
SOURCES_SAY = re.compile(
    r"\b(?:sources?|people|persons?|officials?|executives?)\s+(?:familiar|aware|close|with (?:direct )?knowledge)\b"
    r"|\bsources?\s+(?:said|say|says|told)\b|\bsaid\s+(?:\w+\s+){0,3}sources?\b|\bciting\s+(?:\w+\s+){0,4}sources?\b"
    r"|\baccording to (?:\w+\s+){0,3}sources?\b|\bwho (?:declined to be|did not want to be|asked not to be) "
    r"(?:named|identified)\b|:\s*sources?\s*$|\bsources say\b",
    re.I,
)
TOKEN = re.compile(r"[a-z0-9$₹%.]+")
TITLE_WORD = re.compile(r"[a-z][a-z0-9&'-]*")
MIN_TITLE_WORD_LENGTH = 3
STOP_WORDS = """a an the and or but of to in on at for from by with as is are was were be been has have
    had it its this that these those after before over under amid into out up down about than vs via per new
    says said say report reports reported live update updates today stock stocks share shares price prices market
    markets ltd inc corp co company limited plc nse bse nyse nasdaq what why how will may could should can
    reuters bloomberg pti ians ap afp ani billion billions million millions crore crores lakh trillion
    here you your why who his her their our more than just now"""


def clean_text(text: str | None) -> str:
    """Plain text: HTML entities decoded (JSON-LD bodies carry '&#39;', '&zwnj;'), zero-width characters
    dropped, whitespace collapsed, and a space put back where paragraphs were glued ('said.The', 'post.HDFC')."""
    text = ZERO_WIDTH.sub("", html_lib.unescape(text or ""))
    text = GLUED_PARAGRAPHS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> list[str]:
    """The sentences of a text."""
    return [sentence.strip() for sentence in SENTENCE_BREAK.split(clean_text(text)) if sentence.strip()]


def normalised_number(match: re.Match) -> str | None:
    """One number match as '<value:.6g>[ unit]' (scale applied), or None for years, plain small numbers."""
    raw = match.group("num")
    value = float(raw.replace(",", ""))
    currency = CURRENCIES.get((match.group("cur") or "").strip().lower().replace(" ", ""))
    scale, percent = (match.group("scale") or "").lower(), (match.group("pct") or "").lower()
    if scale in AMBIGUOUS_SCALES and not currency:
        scale = ""
    value *= SCALES.get(scale, 1)
    unit = UNIT_PERCENT if percent and percent[0] in "%p" else UNIT_BASIS_POINTS if percent else currency
    is_year = YEAR_RANGE[0] <= value <= YEAR_RANGE[1] and "." not in raw and "," not in raw
    if not unit and not scale and (is_year or value < MIN_PLAIN_NUMBER):
        return None
    return f"{value:.6g}" + (f" {unit}" if unit else "")


def numbers(text: str | None, limit: int = MAX_NUMBERS) -> list[str]:
    """Normalised numbers: value with scale applied, then a unit (usd, inr, eur, gbp, pct, bps):
    '$3.8 billion' -> '3.8e+09 usd', 'Rs 5,77,094 crore' -> '5.77094e+12 inr', '24.7%' -> '24.7 pct',
    '486,532' -> '486532'. Plain years (1900-2100) and plain numbers below 10 are left out."""
    found: list[str] = []
    for match in NUMBER.finditer(text or ""):
        if match.start("num") > 0 and text[match.start("num") - 1].isalnum():
            continue  # Q3, FY26, H1
        number = normalised_number(match)
        if number is None:
            continue
        if number not in found:
            found.append(number)
        if len(found) >= limit:
            break
    return found


def distinctive(normalised: list[str]) -> set[str]:
    """Numbers that identify an event in a headline: a currency amount, a percent with decimals, or a
    plain number >= 1000 (not a year). '2%' or 'Q3' are not distinctive."""
    found = set()
    for number in normalised:
        text, _, unit = number.partition(" ")
        value = float(text)
        is_amount = unit in CURRENCY_UNITS
        is_fractional_percent = unit == UNIT_PERCENT and value != int(value)
        if is_amount or is_fractional_percent or (not unit and value >= MIN_DISTINCTIVE_NUMBER):
            found.add(number)
    return found


def key_sentences(
    text: str, names: list[str] | None = None, count: int = KEY_SENTENCES, max_words: int = KEY_SENTENCE_WORDS
) -> list[str]:
    """At most `count` sentences (each cut to max_words words): the lede, then sentences with a number or
    one of the company names, in text order."""
    candidates = [
        candidate_sentence
        for candidate_sentence in sentences(text)
        if len(candidate_sentence.split()) >= MIN_SENTENCE_WORDS
    ]
    if not candidates:
        candidates = [candidate_sentence for candidate_sentence in sentences(text) if candidate_sentence]
    names_pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b", re.I) if names else None
    chosen = candidates[:1]
    for sentence in candidates[1:]:
        if len(chosen) >= count:
            break
        if re.search(r"\d", sentence) or (names_pattern and names_pattern.search(sentence)):
            chosen.append(sentence)
    for sentence in candidates[1:]:
        if len(chosen) >= count:
            break
        if sentence not in chosen:
            chosen.append(sentence)
    chosen.sort(key=candidates.index)
    return [" ".join(candidate_sentence.split()[:max_words]) for candidate_sentence in chosen[:count]]


def sources_say(*texts: str | None) -> bool:
    """True when any text attributes its claim to unnamed sources ('sources said', 'people familiar with')."""
    return any(text and SOURCES_SAY.search(text) for text in texts)


def shingles(text: str | None, size: int = SHINGLE) -> set[str]:
    """The word shingles (`size` consecutive lower-case tokens) of a text."""
    words = [token.strip(".") for token in TOKEN.findall((text or "").lower()) if token.strip(".")]
    return {" ".join(words[start : start + size]) for start in range(len(words) - size + 1)}


def minhash_hex(shingle_set: set[str]) -> str | None:
    """MinHash signature (datasketch, NUM_PERM permutations, seed 1) as hex: NUM_PERM x 8 hex digits."""
    if not shingle_set:
        return None
    from datasketch import MinHash

    signature = MinHash(num_perm=NUM_PERM, seed=MINHASH_SEED)
    signature.update_batch([shingle.encode("utf-8") for shingle in sorted(shingle_set)])
    return "".join(f"{int(hash_value):0{HEX_DIGITS_PER_HASH}x}" for hash_value in signature.hashvalues)


def signature_values(hex_signature: str) -> list[int]:
    """The integer values of a hex MinHash signature."""
    step = HEX_DIGITS_PER_HASH
    return [int(hex_signature[offset : offset + step], 16) for offset in range(0, len(hex_signature), step)]


def estimated_jaccard(first: str, second: str) -> float:
    """The share of equal values of two MinHash signatures (the Jaccard estimate)."""
    first_values, second_values = signature_values(first), signature_values(second)
    return sum(first_value == second_value for first_value, second_value in zip(first_values, second_values)) / len(
        first_values
    )


def estimated_containment(
    first: str | None, first_count: int | None, second: str | None, second_count: int | None
) -> float | None:
    """Estimated |A∩B| / min(|A|,|B|) from two MinHash signatures and their shingle counts."""
    if not first or not second or not first_count or not second_count:
        return None
    jaccard = estimated_jaccard(first, second)
    intersection = jaccard * (first_count + second_count) / (1 + jaccard)
    return min(1.0, intersection / min(first_count, second_count))


def containment_exact(first: set[str], second: set[str]) -> float:
    """|A∩B| / min(|A|,|B|) of two shingle sets (0 when one is empty)."""
    return len(first & second) / min(len(first), len(second)) if first and second else 0.0


def content_hash(text: str | None) -> str | None:
    """The sha256 of a text's lower-case tokens (None when it has none)."""
    words = TOKEN.findall((text or "").lower())
    return hashlib.sha256(" ".join(words).encode()).hexdigest() if words else None


@lru_cache(maxsize=1)
def stop_words() -> frozenset:
    """Words that say nothing about the event a headline reports."""
    return frozenset(STOP_WORDS.split())


def title_tokens(title: str | None, drop: set[str] | None = None) -> set[str]:
    """The distinctive lower-case words of a headline (stop words and the `drop` words left out)."""
    words = TITLE_WORD.findall((title or "").lower().replace("’", "'"))
    words = [word.removesuffix("'s") for word in words]
    return {
        word
        for word in words
        if len(word) >= MIN_TITLE_WORD_LENGTH and word not in stop_words() and word not in (drop or set())
    }
