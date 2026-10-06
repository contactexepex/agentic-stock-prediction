"""Ticker tagging and article identity for news items (collect_news.py writes, the `news` view
re-tags on read). Standard library only, so common.connect can import it.

Matching: a ticker's `news_names` (default: `name` + `aliases` in config/markets/<market>.yaml)
as whole words, case-insensitively, after that ticker's own `news_exclude` regexes were removed
from the text ("Kotak Mahindra" for M&M). Press-release wires (`watchlist_only` outlets) match
`wire_names` minus `news.wire_exclude` instead.

Headline first (issue #29):
1. The TITLE is the subject. Companies named in the title are tagged; the summary is not used.
2. Only when the title names no watchlist company is the PLAIN-TEXT summary used (HTML tags,
   entities, URLs/domains and the trailing outlet name removed; never links or source names:
   every Google News summary links news.google.com, which once tagged nearly everything GOOGL).
3. A Google News query for a company only finds candidates; the hit alone never tags.

Roles: `primary_tickers` (what the item is about) and `mentioned_tickers` (named in passing):
- a company named in the title is primary; several title companies are all primary,
- except a comparison title ("X vs Y", "versus", "v/s") or a list ("TCS, Infosys and Wipro rise",
  "Stocks to watch: HDFC Bank, Kotak Mahindra Bank, ...") where the compared or listed companies
  are mentioned,
- a company found only in the summary is mentioned.
`tag_confidence`: "high" when the title names exactly one watchlist company and it is primary;
"low" for every other tagged item (several title companies, a comparison or list, a summary-only
match), the hook for a later aboutness check of material items; null when nothing is tagged.
`tickers` = primary + mentioned (what news_ticker_day unnests).

Stored rows are append-only, so rows written before this tagger (no `tag_version`) are re-tagged
on read by `retag_stored` (DuckDB function `news_retag`, registered in common.connect; the
`news` view applies it and `news_stored` keeps the rows as stored). Their summaries were not
stored, so they are tagged from the title; a title without a company leaves them untagged
(Google News summaries repeat the headline, so nothing is lost there). Old wire rows whose title
names no company keep their stored tags as mentioned, low confidence. Rows with `tag_version`
>= TAG_VERSION were tagged by this code and are returned as stored."""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlparse

TAG_VERSION = 2

_TAGS = re.compile(r"<[^>]*>")
_URLS = re.compile(r"(?:https?://|www\.)\S+", re.I)
_DOMAINS = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|in|org|net|co|io|uk|us|news|biz|info)\b(?:/\S*)?", re.I)
_QUOTES = str.maketrans({"’": "'", "‘": "'", " ": " "})
_VS = re.compile(r"\b(?:vs\.?|versus|v/s)(?=\s|$)", re.I)
_LIST_AFTER = re.compile(r"^(?:'s)?\s*[,;/]")
_LIST_BEFORE = re.compile(r"(?:[,;/]\s*|,[^,:;]{1,60}\s(?:and|&)\s*)$", re.I)


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def article_id(title: str, source: str) -> str:
    # Google News links are redirect URLs, so title + source is the stable identity.
    return hashlib.sha256(f"{norm(title)}|{norm(source)}".encode()).hexdigest()[:16]


def source_domain(href: str | None) -> str | None:
    """'https://www.businesstoday.in/' -> 'businesstoday.in' (the RSS <source url>)."""
    if not href:
        return None
    host = urlparse(href if "//" in href else f"//{href}").netloc.lower().split(":")[0]
    return (host[4:] if host.startswith("www.") else host) or None


def item_id(title: str, source: str, domain: str | None) -> str:
    """Identity of an item: normalized title + source domain when the feed gives one (Google News
    <source url>), so "Business Today" and "businesstoday.in" labels of one article are one item;
    else normalized title + source label (the pre-domain `article_id`)."""
    return article_id(title, domain) if domain else article_id(title, source)


def plain_text(summary: str | None, source: str | None = None) -> str:
    """An RSS summary as plain text: HTML tags, entities, URLs and bare domains removed, and the
    outlet name at the end (Google News: '<a ...>headline</a>&nbsp;&nbsp;<font>Outlet</font>')."""
    text = html.unescape(_TAGS.sub(" ", summary or "")).translate(_QUOTES)
    text = _DOMAINS.sub(" ", _URLS.sub(" ", text))
    text = re.sub(r"\s+", " ", text).strip()
    if source:
        src = source.translate(_QUOTES).strip()
        if src and text.lower().endswith(src.lower()):
            text = text[: -len(src)].rstrip(" -|")
    return text


def _alternation(names: list[str]) -> str:
    return "|".join(map(re.escape, sorted({n.translate(_QUOTES) for n in names if n}, key=len, reverse=True)))


def _regex(patterns: list[str]) -> re.Pattern | None:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


def company_queries(watchlist: dict, template: str) -> list[tuple[str, str]]:
    """(ticker, Google News query) for every company query job."""
    return [(t, q) for t, meta in watchlist.get("tickers", {}).items()
            for q in meta.get("queries", [template.format(name=meta["name"])])]


Rules = dict[str, tuple[re.Pattern, re.Pattern | None]]


def empty_tags() -> dict:
    return {"tickers": [], "primary_tickers": [], "mentioned_tickers": [], "tag_confidence": None}


class Tagger:
    def __init__(self, watchlist: dict):
        feeds = watchlist.get("news", {}) or {}
        wire_ex = _regex(feeds.get("wire_exclude") or [])
        self.rules: Rules = {}
        self.wire_rules: Rules = {}
        for ticker, meta in watchlist.get("tickers", {}).items():
            names = meta.get("news_names") or [meta["name"], *meta.get("aliases", [])]
            self.rules[ticker] = (re.compile(r"\b(?:" + _alternation(names) + r")\b", re.I),
                                  _regex(meta.get("news_exclude") or []))
            wnames = meta.get("wire_names") or [meta["name"], *meta.get("aliases", [])]
            self.wire_rules[ticker] = (re.compile(r"\b(?:" + _alternation(wnames) + r")\b", re.I), wire_ex)
        self.wire_feeds = {o["name"] for o in feeds.get("outlets", []) if o.get("watchlist_only")}

    @staticmethod
    def matches(text: str, rules: Rules) -> list[tuple[int, int, str]]:
        """(start, end, ticker) of every name match, excluded phrases blanked out first."""
        text = (text or "").translate(_QUOTES)
        out = []
        for ticker, (pat, ex) in rules.items():
            t = ex.sub(lambda m: " " * len(m.group()), text) if ex else text
            out += [(m.start(), m.end(), ticker) for m in pat.finditer(t)]
        return sorted(out)

    def tag(self, text: str, wire: bool = False) -> set[str]:
        return {t for _, _, t in self.matches(text, self.wire_rules if wire else self.rules)}

    def classify(self, title: str, summary_text: str | None = None, wire: bool = False) -> dict:
        """Tags of one item from its title and (plain-text) summary; see the module docstring."""
        rules = self.wire_rules if wire else self.rules
        title = (title or "").translate(_QUOTES)
        found = self.matches(title, rules)
        if found:
            order = list(dict.fromkeys(t for _, _, t in found))
            if _VS.search(title):
                primary = []
            else:
                listed = {t for s, e, t in found
                          if _LIST_AFTER.search(title[e:]) or _LIST_BEFORE.search(title[:s])}
                primary = [t for t in order if t not in listed]
            mentioned = [t for t in order if t not in primary]
            conf = "high" if len(order) == 1 and primary else "low"
        else:
            primary, mentioned = [], list(dict.fromkeys(t for _, _, t in self.matches(summary_text or "", rules)))
            conf = "low" if mentioned else None
        return {"tickers": sorted(set(primary) | set(mentioned)), "primary_tickers": sorted(primary),
                "mentioned_tickers": sorted(mentioned), "tag_confidence": conf}

    def classify_item(self, title: str, summary: str | None, source: str | None, wire: bool = False) -> dict:
        return self.classify(title, plain_text(summary, source), wire)

    def tag_item(self, title: str, summary: str | None, source: str | None) -> set[str]:
        return set(self.classify_item(title, summary, source)["tickers"])

    def retag_stored(self, feed, title, tickers, primary, mentioned, confidence, tag_version) -> dict:
        """Corrected tags of a stored row (see the module docstring)."""
        if tag_version is not None and tag_version >= TAG_VERSION:
            return {"tickers": list(tickers or []), "primary_tickers": list(primary or []),
                    "mentioned_tickers": list(mentioned or []), "tag_confidence": confidence}
        wire = feed in self.wire_feeds
        out = self.classify(title or "", None, wire)
        if wire and not out["tickers"] and tickers:
            out = {"tickers": sorted(tickers), "primary_tickers": [], "mentioned_tickers": sorted(tickers),
                   "tag_confidence": "low"}
        return out


RETAG_TYPE = {"tickers": "VARCHAR[]", "primary_tickers": "VARCHAR[]", "mentioned_tickers": "VARCHAR[]",
              "tag_confidence": "VARCHAR"}
