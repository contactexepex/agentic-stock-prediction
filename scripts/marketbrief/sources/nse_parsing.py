"""Parsing helpers for NSE payloads (fields are strings; "-", "" and "Nil" mean missing) and the XBRL instance
documents of SEBI PIT and Integrated Filing disclosures."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone

from marketbrief.constants.config_keys import CFG_TICKERS, META_NSE_SYMBOL, META_YAHOO
from marketbrief.constants.sources import NSE_DATE_FORMATS, NSE_MISSING_VALUES, NSE_YAHOO_SUFFIX, TIMEZONE_IST

IST = TIMEZONE_IST
SHORT_HASH_LENGTH = 12

_CONTEXT = re.compile(r"<xbrli:context id=\"([^\"]+)\">(.*?)</xbrli:context>", re.S)
_PERIOD = re.compile(r"<xbrli:(startDate|endDate|instant)>([^<]+)<")
_FACT = re.compile(r"<([A-Za-z][\w-]*):([A-Za-z]\w*)\s+contextRef=\"([^\"]+)\"[^>]*?(?:/>|>([^<]*)</\1:\2>)", re.S)


def pick(row: dict, *keys):
    """The first present value among `keys` of an NSE row (stripped when text), or None."""
    for key in keys:
        value = row.get(key)
        if value not in NSE_MISSING_VALUES:
            return value.strip() if isinstance(value, str) else value
    return None


def parse_ts(text) -> datetime | None:
    """NSE dates/times (IST) -> aware UTC datetime."""
    if not text:
        return None
    text = str(text).strip()
    for fmt in NSE_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def parse_day(text) -> date | None:
    """The IST calendar day of an NSE date or time, or None."""
    stamp = parse_ts(text)
    return stamp.astimezone(IST).date() if stamp else None


def rows_of(payload, key: str | None = None) -> list[dict]:
    """The row dicts of an NSE JSON payload (a list, or a dict holding them under `key`, default "data")."""
    if isinstance(payload, dict):
        payload = payload.get(key) if key else payload.get("data", [])
    return [row for row in payload or [] if isinstance(row, dict)]


def short_hash(*parts) -> str:
    """A 12-character sha256 of the parts (None as empty), for ids."""
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()[:SHORT_HASH_LENGTH]


def iso(value) -> str | None:
    """The ISO text of a date or datetime, or None."""
    return value.isoformat() if value else None


def nse_symbols(cfg: dict) -> dict[str, str]:
    """NSE symbol -> watchlist ticker."""
    return {
        meta.get(META_NSE_SYMBOL, meta[META_YAHOO].removesuffix(NSE_YAHOO_SUFFIX)).upper(): ticker
        for ticker, meta in cfg[CFG_TICKERS].items()
    }


def xbrl(text: str) -> tuple[dict[str, dict], dict[str, dict[str, str]]]:
    """(contexts, facts): contexts[id] = {start, end, instant, dimensional}; facts[context][name] = value."""
    contexts = {}
    for context_id, body in _CONTEXT.findall(text):
        period = dict(_PERIOD.findall(body))
        contexts[context_id] = {
            "start": period.get("startDate"),
            "end": period.get("endDate"),
            "instant": period.get("instant"),
            "dimensional": "xbrldi:" in body,
        }
    facts: dict[str, dict[str, str]] = {}
    for _prefix, name, context, value in _FACT.findall(text):
        facts.setdefault(context, {})[name] = (value or "").strip()
    return contexts, facts
