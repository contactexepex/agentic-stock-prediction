"""The number check of the gated texts (EOD analyst, research director), after scripts/lessons.py: every number in a
text must equal (to the precision written) a stored fact it may cite. Ids, dates, tickers, strategy ids and the band
names "50% range" / "80% range" are removed first. A number with a % sign may only be a percent fact; a plain number
may be any fact (the analyst writes "the market explains +0.46 points" for market_pct). A signed number (+ or -) that
matches only signed percent facts must carry the sign of one of them."""
from __future__ import annotations

import re

from marketbrief.traders.constants import DATE_TOKEN, ID_TOKEN, NUMBER

STRATEGY_TOKEN = re.compile(r"\b(?:rule|base|ai)\.[a-z0-9_.]+\.v\d+\b")
HORIZON_TOKEN = re.compile(r"\bN\+(\d+)\b")
# the names of the published bands ("the 80% range", "50 % band"): labels, not numbers to check
BAND_LABEL = re.compile(r"(?<![\w.])(?:50|80)\s?(?:%|percent)(?=\s+(?:range|band|interval)\b)", re.I)


def scrub(text: str, extra: list[str]) -> str:
    """The text without ids, dates, strategy ids and the given names (tickers, ids)."""
    for name in sorted({e for e in extra if e}, key=len, reverse=True):
        text = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", " ", text)
    for pattern in (ID_TOKEN, STRATEGY_TOKEN, DATE_TOKEN, BAND_LABEL):
        text = pattern.sub(" ", text)
    return HORIZON_TOKEN.sub(r" \1 ", text)


def facts_of(record: dict, pct_keys: tuple[str, ...], plain_keys: tuple[str, ...]) -> list[tuple[float, bool, str]]:
    """(value, is_percent, name) of a record's numeric facts."""
    out = []
    for key in pct_keys + plain_keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append((float(value), key in pct_keys, key))
    return out


def problems(text: str, facts: list[tuple[float, bool, str]], extra: list[str]) -> list[str]:
    """Numbers of the text that match no fact, and signs that contradict the only facts they match."""
    out = []
    for sign, digits, pct in NUMBER.findall(scrub(text, extra)):
        number = float(digits.replace(",", ""))
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        matches = [(value, is_pct, name) for value, is_pct, name in facts
                   if abs(number - abs(value)) <= tolerance and (is_pct or not pct)]
        if not matches:
            out.append(f"{sign}{digits}{pct.strip()}")
            continue
        if sign and all(is_pct for _, is_pct, _ in matches):
            negative = sign in "-−"
            if not any((value < 0) == negative or value == 0 for value, _, _ in matches):
                out.append(f"{sign}{digits}{pct.strip()} (sign)")
    return out
