"""The `news_articles` rows of the articles collector: the empty row of a candidate and the row read from a page.
Stored per row (schema `news_articles` in marketbrief/core/schemas.py): metadata, the origin agency and its
evidence, key sentences, normalised numbers, a content hash and a MinHash signature. Never the article text."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics.article_extraction import parse_article
from marketbrief.analytics.article_pages import FetchResult, host_of
from marketbrief.analytics.news_sources import Sources
from marketbrief.analytics.text_measures import content_hash, key_sentences, minhash_hex, numbers, shingles, sources_say
from marketbrief.constants.article_collection import (
    BYLINE_LIMIT,
    DATE_VALUE_LIMIT,
    MSG_DATE_NOT_STORED,
    PROVIDER_LIMIT,
    TZ_ABBREVIATIONS,
)
from marketbrief.constants.articles import METHOD_VERSION_ARTICLES
from marketbrief.core.clock import utc_now

DATE_FIELDS = ("date_published", "date_modified")


def base_row(candidate: dict, now: str) -> dict:
    """A `news_articles` row of a candidate with no page read (every measure empty)."""
    return {
        "id": candidate["id"],
        "fetched_at": now,
        "ticker": candidate["ticker"],
        "source_url": candidate["url"],
        "final_url": None,
        "domain": candidate["outlet"],
        "tier": candidate["tier"],
        "http_status": None,
        "access": None,
        "extractor": None,
        "chars": None,
        "date_published": None,
        "date_modified": None,
        "byline": None,
        "provider": None,
        "origin_wire": None,
        "origin_evidence": None,
        "sources_say": None,
        "promotional": None,
        "extract": None,
        "numbers": None,
        "content_hash": None,
        "shingle_count": None,
        "minhash": None,
        "note": None,
        "method_version": METHOD_VERSION_ARTICLES,
    }


def iso_utc(value, not_after: pd.Timestamp) -> str | None:
    """An ISO timestamp with an offset, as UTC; None when missing, without a zone, or after the fetch."""
    if not value or not isinstance(value, str):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        try:  # 'Mon Oct 5, 11:56AM CDT' (The Globe and Mail): US and India zone abbreviations only
            from dateutil import parser as date_parser

            stamp = pd.Timestamp(date_parser.parse(value, tzinfos=TZ_ABBREVIATIONS))
        except (ValueError, TypeError, OverflowError):
            return None
    if stamp.tzinfo is None or stamp > not_after:
        return None
    return stamp.tz_convert("UTC").floor("s").isoformat()


def is_promotional(src: Sources, parsed: dict, candidate: dict, domain: str, text: str) -> str | None:
    """Why the page is vendor or promotional content (its provider, byline, outlet or text), or None."""
    return (
        src.is_promotional(name=parsed.get("provider"))
        or src.is_promotional(name=parsed.get("byline"))
        or src.is_promotional(name=candidate["source"], domain=domain, text=text)
    )


def article_row(candidate: dict, page: FetchResult, src: Sources, names: list[str]) -> dict:
    """The row of a page that was read: access, dates, origin, promotional flag, measures of its text."""
    now = utc_now()
    row = base_row(candidate, now)
    final_host = host_of(page.final_url)
    domain, meta = src.lookup(final_host)
    row.update(
        final_url=page.final_url, domain=domain or final_host, tier=src.tier(final_host), http_status=page.status
    )
    parsed = parse_article(page.html, page.final_url, src, meta)
    text = parsed.pop("text") or ""
    fetched = pd.Timestamp(now)
    wire, evidence = src.detect_wire(
        byline=parsed.get("byline"), provider=parsed.get("provider"), text=text, title=candidate["title"]
    )
    promotional = is_promotional(src, parsed, candidate, row["domain"], text)
    shingle_set = shingles(text)
    row.update(
        access=parsed["access"],
        extractor=parsed.get("extractor"),
        chars=len(text),
        date_published=iso_utc(parsed.get("date_published"), fetched),
        date_modified=iso_utc(parsed.get("date_modified"), fetched),
        byline=(parsed.get("byline") or None) and parsed["byline"][:BYLINE_LIMIT],
        provider=(parsed.get("provider") or None) and parsed["provider"][:PROVIDER_LIMIT],
        origin_wire=wire,
        origin_evidence=evidence,
        sources_say=sources_say(text, candidate["title"]),
        promotional=promotional,
        extract=key_sentences(text, names),
        numbers=numbers(text),
        content_hash=content_hash(text),
        shingle_count=len(shingle_set),
        minhash=minhash_hex(shingle_set),
        note=parsed.get("note"),
    )
    for field in DATE_FIELDS:
        if parsed.get(field) and not row[field]:
            unstored = MSG_DATE_NOT_STORED.format(field=field, value=str(parsed[field])[:DATE_VALUE_LIMIT])
            row["note"] = "; ".join(x for x in (row["note"], unstored) if x)
    return row
