"""Numbers quoted in claims: number literals with scale and unit, their stated rounding, and matching."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from marketbrief.constants.verification import CURRENCY_UNITS, RELATIVE_TOLERANCE

NUMBER_LITERAL = re.compile(
    r"(?P<cur>US\$|\$|₹|Rs\.?\s?|INR\s?|USD\s?|€|£)?\s?"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<scale>lakh crore|trillion|billion|million|thousand|crore|lakh|tn|bn|mn|cr|k|b|m)\b)?"
    r"\s?(?P<pct>%|per ?cent\b|percent\b|bps\b|basis points\b)?", re.I)
PLAIN_NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d[\d,]*(?:\.\d+)?")
SCALES = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6,
          "m": 1e6, "thousand": 1e3, "k": 1e3, "crore": 1e7, "cr": 1e7, "lakh": 1e5, "lakh crore": 1e12}
CURRENCIES = {"$": "usd", "us$": "usd", "usd": "usd", "₹": "inr", "rs": "inr", "rs.": "inr", "inr": "inr",
              "€": "eur", "£": "gbp"}
EXACT = 1e-9


@dataclass(frozen=True)
class QuotedNumber:
    """One number literal of a text: its text, value with the scale applied, unit marker and half rounding step."""
    literal: str
    value: float
    unit: str | None
    half_step: float


def _unit_of(match: re.Match) -> str | None:
    """pct, bps, a currency code, or None for a bare number."""
    pct = (match.group("pct") or "").lower()
    if pct:
        return "pct" if pct[0] in "%p" else "bps"
    return CURRENCIES.get((match.group("cur") or "").strip().lower().replace(" ", ""))


def _half_step(digits: str, scale: float) -> float:
    """Half the last stated digit's place: '486,532' -> 0.5, '480' K -> 5,000, '3.8' bn -> 0.05 bn."""
    plain = digits.replace(",", "")
    if "." in plain:
        step = 10.0 ** -len(plain.split(".")[1])
    else:
        step = 10.0 ** (len(plain) - len(plain.rstrip("0"))) if plain.strip("0") else 1.0
    return step * scale / 2


def quoted_numbers(text: str | None) -> list[QuotedNumber]:
    """Every number literal in a text (not inside a token like Q3 or FY26), scale applied."""
    found = []
    for match in NUMBER_LITERAL.finditer(text or ""):
        start = match.start("cur") if match.group("cur") else match.start("num")
        if start > 0 and (text[start - 1].isalnum() or text[start - 1] == "."):
            continue
        scale = SCALES.get((match.group("scale") or "").lower(), 1.0)
        digits = match.group("num")
        value = float(digits.replace(",", "")) * scale
        found.append(QuotedNumber(match.group(0).strip(), value, _unit_of(match), _half_step(digits, scale)))
    return found


def plain_number_tokens(text: str | None) -> set[str]:
    """Digit tokens of a text without thousands separators ('486,532' -> '486532'), for presence checks."""
    return {token.replace(",", "").rstrip(".") for token in PLAIN_NUMBER.findall(text or "")}


def unit_fits(claim_unit: str, literal_unit: str | None) -> bool:
    """A claim's unit is compatible with the literal's marker: the same marker, or a bare number
    (a count, or an amount whose currency the quote does not print) for a count or currency unit."""
    if literal_unit is None:
        return claim_unit == "count" or claim_unit in CURRENCY_UNITS
    return claim_unit == literal_unit


def literal_for(value: float, unit: str, text: str) -> QuotedNumber | None:
    """The literal of the text that states this value in this unit, or None."""
    for number in quoted_numbers(text):
        if math.isclose(number.value, value, rel_tol=EXACT, abs_tol=EXACT) and unit_fits(unit, number.unit):
            return number
    return None


def half_step_of(literal: str | None) -> float:
    """Half the rounding step a stored literal states (0 when it cannot be read)."""
    numbers = quoted_numbers(literal)
    return numbers[0].half_step if numbers else 0.0


def values_match(first: tuple[float, str | None], second: tuple[float, str | None],
                 relative: float = RELATIVE_TOLERANCE) -> bool:
    """Two stated values agree within `relative` of the larger, or within either literal's stated rounding."""
    (a, a_text), (b, b_text) = first, second
    tolerance = max(relative * max(abs(a), abs(b)), half_step_of(a_text), half_step_of(b_text))
    return abs(a - b) <= tolerance + EXACT
