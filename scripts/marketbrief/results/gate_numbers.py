"""The number check of the results gate: every number a bullet states in its own words must be stated in its quote
or equal one of the release's deterministic numbers, with the same unit, scale, rounding and direction.

- Dates ("June 30, 2026", "30 June", 2026-06-30) in the text must appear in the quote; dates are removed before
  numbers are read, so a day or year of a date never stands in for an amount ("30 crore" is not "June 30").
- A bare year (1900-2099, no scale) is fine when the quote or the release's period labels name it.
- Every other number is compared by value with its scale applied ("150 crore" = 1.5e9), within the text's own
  rounding (stated decimals only: "30%" is 30 +- 0.5, never 25), a % only with a % (quote) or a `_pct` value.
- Direction: a fall word (fell, declined, down, lower, loss ...) or a minus sign just before the number makes it a
  fall. A fall never matches a positive release value or a rise in the quote, and a negative release value (a
  falling growth rate, a loss) only matches a fall, compared by its absolute value."""

from __future__ import annotations

import re

from marketbrief.analytics.claim_numbers import NUMBER_LITERAL, QuotedNumber, quoted_numbers
from marketbrief.analytics.claim_rules import normalise

PCT, MARKER_UNITS = "pct", ("pct", "bps")
DIGITS = re.compile(r"\d[\d,]*(?:\.(\d+))?")
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(
    rf"\b{MONTH}\s+\d{{1,2}}(?:,?\s*\d{{4}})?\b|\b\d{{1,2}}\s+{MONTH}(?:,?\s*\d{{4}})?\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b",
    re.I,
)
YEAR = re.compile(r"(?:19|20)\d{2}")
FALL_WORDS = {
    "fell",
    "fall",
    "falls",
    "falling",
    "declined",
    "decline",
    "declines",
    "decreased",
    "decrease",
    "decreases",
    "down",
    "lower",
    "loss",
    "losses",
    "dropped",
    "drop",
    "drops",
    "shrank",
    "shrink",
    "contracted",
    "slipped",
    "slid",
    "plunged",
    "negative",
    "minus",
    "worse",
    "lost",
}
RISE_WORDS = {
    "rose",
    "rise",
    "rises",
    "rising",
    "grew",
    "grow",
    "grows",
    "increased",
    "increase",
    "increases",
    "up",
    "higher",
    "gained",
    "gain",
    "gains",
    "jumped",
    "climbed",
    "improved",
    "expanded",
    "surged",
    "positive",
}
WINDOW_WORDS = 6


def numbers_at(text: str) -> list[tuple[QuotedNumber, int]]:
    """Every number literal of a text with its start (same reading as claim_numbers.quoted_numbers)."""
    found = []
    for match in NUMBER_LITERAL.finditer(text):
        start = match.start("cur") if match.group("cur") else match.start("num")
        if start > 0 and (text[start - 1].isalnum() or text[start - 1] == "."):
            continue
        parsed = quoted_numbers(match.group(0))
        if parsed:
            found.append((parsed[0], start))
    return found


def direction(text: str, start: int) -> int:
    """-1 for a fall (a fall word among the few words before the number, or a minus sign right before it), +1 for
    a rise word, 0 when the text says neither."""
    if start > 0 and text[start - 1] in "-−":
        return -1
    for word in reversed(re.findall(r"[a-z]+", text[max(0, start - 80) : start].lower())[-WINDOW_WORDS:]):
        if word in FALL_WORDS:
            return -1
        if word in RISE_WORDS:
            return 1
    return 0


def half_step(literal: QuotedNumber) -> float:
    """Half the last stated decimal place, scale applied ('25%' -> 0.5, '$95.7 billion' -> 0.05 billion)."""
    found = DIGITS.search(literal.literal)
    if not found:
        return 0.0
    stated = float(found.group(0).replace(",", "")) or 1.0
    return 0.5 * 10.0 ** -len(found.group(1) or "") * abs(literal.value / stated)


def units_fit(text_unit: str | None, quote_unit: str | None) -> bool:
    """Same marker, or a bare number on one side for an amount (a text or quote need not print the currency)."""
    if text_unit == quote_unit:
        return True
    return (text_unit is None and quote_unit not in MARKER_UNITS) or (
        quote_unit is None and text_unit not in MARKER_UNITS
    )


def is_year(literal: QuotedNumber) -> bool:
    """A bare four-digit year without scale."""
    digits = literal.literal.replace(",", "")
    return literal.unit is None and bool(YEAR.fullmatch(digits))


def in_quote(literal: QuotedNumber, way: int, quote: str, tolerance: float) -> bool:
    """The quote states this number with a compatible unit and no opposite direction."""
    for stated, start in numbers_at(quote):
        quote_way = direction(quote, start)
        if way and quote_way and way != quote_way:
            continue
        if units_fit(literal.unit, stated.unit) and abs(stated.value - literal.value) <= tolerance:
            return True
    return False


def in_release(literal: QuotedNumber, way: int, values: dict[str, float], tolerance: float) -> bool:
    """A release value of the same kind (% or amount) equals it by absolute value, in the same direction."""
    wanted_pct = literal.unit == PCT
    for name, value in values.items():
        if name.endswith("_pct") != wanted_pct or abs(abs(value) - literal.value) > tolerance:
            continue
        if (value < 0 and way == -1) or (value >= 0 and way != -1):
            return True
    return False


def wrong_numbers(text: str, quote: str, values: dict[str, float], years: set[str]) -> list[str]:
    """The dates and numbers of a bullet's text that neither its quote nor the release states."""
    quoted_text = normalise(quote).lower()
    wrong = [found for found in DATE.findall(text) if normalise(found).lower() not in quoted_text]
    plain_text, plain_quote = DATE.sub(" ", text), DATE.sub(" ", quote)
    quote_years = set(YEAR.findall(plain_quote))
    for literal, start in numbers_at(plain_text):
        if is_year(literal):
            if literal.literal not in quote_years | years:
                wrong.append(literal.literal)
            continue
        way, tolerance = direction(plain_text, start), half_step(literal) + 1e-9
        if not (in_quote(literal, way, plain_quote, tolerance) or in_release(literal, way, values, tolerance)):
            wrong.append(literal.literal)
    return wrong
