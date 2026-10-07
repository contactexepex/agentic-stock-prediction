"""Number formatting and message splitting for the Slack notifications."""
from __future__ import annotations

import math
from datetime import date

from marketbrief.alerts.constants import MARKET_LABELS, MAX_MESSAGE_CHARS, MSG_CONTINUED
from marketbrief.utils.money import format_money

MARKET_CURRENCY = {"india": "INR", "us": "USD"}


def missing(value) -> bool:
    """True for None and NaN."""
    return value is None or (isinstance(value, float) and math.isnan(value))


def money(currency: str, amount) -> str:
    """'$1,000.00' / '₹100,000.00' (utils.money.format_money); a dash when missing."""
    return format_money(currency, None if missing(amount) else float(amount))


def signed_money(currency: str, amount) -> str:
    """'+$4.60' / '-₹120.50'; a dash when missing."""
    if missing(amount):
        return money(currency, None)
    sign = "-" if amount < 0 else "+"
    return sign + money(currency, abs(float(amount)))


def pct(value, digits: int = 2) -> str:
    """'+1.25%' for percent points; a dash when missing."""
    return "—" if missing(value) else f"{float(value):+.{digits}f}%"


def prob(value) -> str:
    """'0.571' for a probability; 'none' when the strategy gives none (always-up, momentum)."""
    return "none" if missing(value) else f"{float(value):.3f}"


def horizon(days) -> str:
    """'N+3'."""
    return f"N+{int(days)}"


def who(strategy_id: str, names: dict) -> str:
    """'Model + news (rule.model_news.v1)', or the id alone when the registry has no name for it."""
    name = names.get(strategy_id)
    return f"{name} ({strategy_id})" if name and name != strategy_id else strategy_id


def market_label(market: str) -> str:
    """'India' / 'US' (the config name otherwise)."""
    return MARKET_LABELS.get(market, market)


def day_label(day) -> str:
    """'Wed 7 Oct 2026'."""
    day = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    return f"{day:%a} {day.day} {day:%b %Y}"


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split on line boundaries into parts of at most `limit` characters; parts after the first start with
    '(continued i/n)'. A single line longer than the room left is cut into pieces."""
    room = limit - len(MSG_CONTINUED.format(part=999, parts=999)) - 1
    pieces: list[str] = []
    for line in text.rstrip("\n").split("\n"):
        while len(line) > room:
            pieces.append(line[:room])
            line = line[room:]
        pieces.append(line)
    parts: list[list[str]] = [[]]
    size = 0
    for line in pieces:
        if parts[-1] and size + len(line) + 1 > room:
            parts.append([])
            size = 0
        parts[-1].append(line)
        size += len(line) + 1
    if len(parts) == 1:
        return ["\n".join(parts[0])]
    total = len(parts)
    return ["\n".join(lines) if i == 0 else MSG_CONTINUED.format(part=i + 1, parts=total) + "\n" + "\n".join(lines)
            for i, lines in enumerate(parts)]
