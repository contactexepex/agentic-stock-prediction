"""Wire (press-release) matching on its own: the tickers a wire text names. The collector gets the same
names and exclusions through the Tagger's wire rules (marketbrief/analytics/news_tags.py), which also split
primary and mentioned."""
from __future__ import annotations

import re

from marketbrief.constants.config_keys import CFG_TICKERS


def wire_patterns(watchlist: dict) -> dict[str, re.Pattern]:
    """For `watchlist_only` (press-release wire) feeds: a ticker's `wire_names` (full company
    names, so single ambiguous words such as "Apple" or "Meta" are left out), else its name and
    aliases; case-insensitive, whole words ("NVIDIA", "JPMORGAN CHASE" match)."""
    patterns = {}
    for ticker, meta in watchlist.get(CFG_TICKERS, {}).items():
        names = meta.get("wire_names") or [meta["name"], *meta.get("aliases", [])]
        patterns[ticker] = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I)
    return patterns


def wire_exclusions(feeds: dict) -> re.Pattern | None:
    """`news.wire_exclude`: regexes for phrases that name another company or no company at all
    ("Apple Hospitality", "Merck KGaA", "meta-analysis"); removed from wire text before matching."""
    patterns = feeds.get("wire_exclude") or []
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


def wire_tickers(text: str, patterns: dict[str, re.Pattern], exclude: re.Pattern | None) -> set[str]:
    """The tickers a wire text names, after the excluded phrases are removed."""
    if exclude:
        text = exclude.sub(" ", text)
    return {ticker for ticker, pattern in patterns.items() if pattern.search(text)}
