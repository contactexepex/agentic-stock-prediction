"""Ticker tagging and article identity for news items (collect_news.py writes, the `news` view
re-tags on read). Standard library only, so core.database.connect can import it.

Matching: a ticker's `news_names` (default: `name` + `aliases` in config/markets/<market>.yaml)
as whole words, case-insensitively, after that ticker's own `news_exclude` regexes were removed
from the text ("Kotak Mahindra" for M&M), plus the ticker symbol in parentheses, case-sensitive
("(DAL)", "(DAL:NYSE)", "(NYSE: DAL)"). Press-release wires (`watchlist_only` outlets) match
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
  "Stocks to watch: HDFC Bank, Kotak Mahindra Bank, ..."; comma or slash separated, not ";")
  where the compared or listed companies are mentioned,
- and except a company acting on another one or holding it (`Tagger.is_actor`): analyst actions
  ("JPMorgan cuts target for Aon", "target raised by JPMorgan", "Bank of America upgrades
  DraftKings"), holdings ("shares of X bought by Bank of America Corp", "takes stake in"), venues
  ("present at Bank of America 2026 conference", "Bank of America Plaza"); for `broker: true`
  tickers also research or securities arms ("BofA Securities"), "at BofA" in analyst news,
  comments ("JPMorgan says/sees ...", "..., says JPMorgan", not "says its ...") and its own
  views ("JPMorgan's October stock picks", "gets a lower JPMorgan target") -> mentioned,
- a company found only in the summary is mentioned.
`tag_confidence`: "high" when the title names exactly one watchlist company and it is primary;
"low" for every other tagged item (several title companies, a comparison or list, a summary-only
match), the hook for a later aboutness check of material items; null when nothing is tagged.
`tickers` = primary + mentioned (what news_ticker_day unnests).

Stored rows are append-only, so rows written before this tagger (no `tag_version`) are re-tagged
on read by `retag_stored` (DuckDB function `news_retag`, registered in core.database.connect; the
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
# a list is comma- or slash-separated ("TCS, Infosys and Wipro"); ";" separates clauses, not items
_LIST_AFTER = re.compile(r"^(?:'s)?\s*[,/]")
_LIST_BEFORE = re.compile(r"(?:[,/]\s*|,[^,:;]{1,60}\s(?:and|&)\s*)$", re.I)

# Actor or holder: the watchlist company acts on another company (analyst action, holding,
# venue), so the item is not about it. See Tagger.is_actor.
_ACTION_WORDS = re.compile(
    r"\b(?:price targets?|targets?|PT|ratings?|upgra\w*|downgra\w*|overweight|"
    r"underweight|equal[- ]weight|outperform|underperform|market perform|sector perform|neutral|"
    r"coverage|(?:buy|sell|hold) (?:on|rating)|top picks?|(?:stock )?picks|ideas|favou?rites|stakes?|"
    r"\d[\d,.]*%? (?:voting rights|shares)|"
    r"voting rights|ownership|shares (?:of|in)|positions?|holdings?|bought|sold|purchased|acquired)\b", re.I)
_ACTIVE = re.compile(
    r"^(?:'s)?\s+(?:(?:analysts?|strategists?|economists?|securities|research|chase(?:\s*&\s*co\.?)?|"
    r"corp(?:oration)?\.?|inc\.?|& co\.?)\s+)*(?:raises?|raised|cuts?|lifts?|lowers?|trims?|boosts?|hikes?|"
    r"ups|keeps?|kept|maintains?|reiterates?|reaffirms?|sets?|initiates?|starts?|resumes?|assumes?|"
    r"adjusts?|revises?|updates?|upgra\w*|downgra\w*|rates?|names?|picks?|adds?|recommends?|buys?|bought|"
    r"sells?|sold|acquires?|takes?|increases?|reduces?|decreases?|holds?|discloses?|reports?)\b",
    re.I)
_PASSIVE_NEXT = re.compile(r"^\s+(?:to|from|by|at|on|in|as)\b", re.I)
_PASSIVE = re.compile(r"\b(?:by|from|after)\s+(?:the\s+)?$", re.I)
# broker-only (`broker: true`): "JPMorgan's October stock picks", "retains JPMorgan's Overweight
# view", "gets a lower JPMorgan target", "..., says JPMorgan", "tells BofA"
_BROKER_OWN = re.compile(r"^(?:'s)?\s+(?:[\w$.,%-]+\s+){0,3}?(?:price\s+)?(?:targets?|ratings?|view|stake|"
                         r"ownership|upgra\w*|downgra\w*|coverage|(?:stock\s+)?picks|ideas|favou?rites|"
                         r"overweight|underweight|neutral|outperform|underperform)\b"
                         r"(?![^;:|]*\b(?:by|from)\b)", re.I)
_TARGET_MOVED = re.compile(r"\b(?:raised|cut|lowered|lifted|trimmed|boosted|hiked|reduced)\b", re.I)
_BROKER_BEFORE = re.compile(r"\b(?:says|said|according to|per|tells?|told)\s+$", re.I)
_AT = re.compile(r"\bat\s+(?:the\s+)?$", re.I)
_VENUE_AFTER = re.compile(r"^(?:'s)?(?:\s+[\w&.'-]+){0,4}?\s+(?:conferences?|summit|forum|symposium)\b", re.I)
_PLACE_AFTER = re.compile(r"^\s+(?:Plaza|Tower|Center|Centre|Stadium|Arena|Building)\b", re.I)
_BROKER_ARM = re.compile(r"^(?:'s)?\s+(?:Securities|Global Research|Global Markets|Asset Management|"
                         r"Wealth Management|Private Bank|Investment Bank)\b", re.I)
_SAYS = re.compile(r"^(?:'s)?\s+(?:(?:analysts?|strategists?|economists?|chief \w+)\s+)?(?:says|said|sees|saw|"
                   r"expects?|predicts?|forecasts?|warns?|flags?|thinks|believes|likes|prefers|bets?|gives|"
                   r"turns|met)\b"
                   r"(?!\s+(?:its|it|Q[1-4]|quarterly|profit|revenue|earnings|results))", re.I)
_CLAUSE = re.compile(r"[;:|]|\s[—–-]\s")
_ANALYST_CONTEXT = re.compile(r"\b(?:analysts?|strategists?|economists?|conferences?)\b", re.I)


def symbol_regex(ticker: str) -> re.Pattern:
    """'(DAL)', '(DAL:NYSE)', '(NYSE: DAL)': the ticker symbol in parentheses, case-sensitive."""
    return re.compile(r"\((?:[A-Z]{2,8}\s*:\s*)?" + re.escape(ticker) + r"(?:\s*:\s*[A-Z]{2,8})?\)")


def norm(text: str) -> str:
    """A text for comparison: lower case, runs of non-word characters as single spaces."""
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def article_id(title: str, source: str) -> str:
    """The id of an article: a hash of its normalised title and source (Google News links are redirect URLs,
    so title + source is the stable identity)."""
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
    """A regex alternation of the distinct names, longest first."""
    return "|".join(map(re.escape, sorted({n.translate(_QUOTES) for n in names if n}, key=len, reverse=True)))


def _regex(patterns: list[str]) -> re.Pattern | None:
    """One case-insensitive regex of the patterns, or None when there are none."""
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


def company_queries(watchlist: dict, template: str) -> list[tuple[str, str]]:
    """(ticker, Google News query) for every company query job."""
    return [(t, q) for t, meta in watchlist.get("tickers", {}).items()
            for q in meta.get("queries", [template.format(name=meta["name"])])]


Rules = dict[str, tuple[re.Pattern, re.Pattern | None]]


def empty_tags() -> dict:
    """The tags of an item that names no company."""
    return {"tickers": [], "primary_tickers": [], "mentioned_tickers": [], "tag_confidence": None}


class Tagger:
    """Tags news items with the watchlist tickers they name (see the module docstring)."""

    def __init__(self, watchlist: dict):
        """Build the ticker patterns of a watchlist."""
        feeds = watchlist.get("news", {}) or {}
        wire_ex = _regex(feeds.get("wire_exclude") or [])
        self.rules: Rules = {}
        self.wire_rules: Rules = {}
        self.symbols: dict[str, re.Pattern] = {}
        self.brokers = {t for t, meta in watchlist.get("tickers", {}).items() if meta.get("broker")}
        for ticker, meta in watchlist.get("tickers", {}).items():
            names = meta.get("news_names") or [meta["name"], *meta.get("aliases", [])]
            self.rules[ticker] = (re.compile(r"\b(?:" + _alternation(names) + r")\b", re.I),
                                  _regex(meta.get("news_exclude") or []))
            wnames = meta.get("wire_names") or [meta["name"], *meta.get("aliases", [])]
            self.wire_rules[ticker] = (re.compile(r"\b(?:" + _alternation(wnames) + r")\b", re.I), wire_ex)
            self.symbols[ticker] = symbol_regex(ticker)
        self.wire_feeds = {o["name"] for o in feeds.get("outlets", []) if o.get("watchlist_only")}

    def matches(self, text: str, rules: Rules) -> list[tuple[int, int, str]]:
        """(start, end, ticker) of every name match, excluded phrases blanked out first, plus the
        ticker symbol in parentheses ('(DAL)', '(DAL:NYSE)', '(NYSE: DAL)'), case-sensitive."""
        text = (text or "").translate(_QUOTES)
        out = []
        for ticker, (pat, ex) in rules.items():
            t = ex.sub(lambda m: " " * len(m.group()), text) if ex else text
            out += [(m.start(), m.end(), ticker) for m in pat.finditer(t)]
            out += [(m.start(), m.end(), ticker) for m in self.symbols[ticker].finditer(text)]
        return sorted(out)

    def is_actor(self, title: str, s: int, e: int, ticker: str) -> bool:
        """True when the company matched at title[s:e] acts on something else instead of being the
        subject: an analyst action ("JPMorgan cuts target for Aon", "target raised by JPMorgan",
        "Bank of America upgrades DraftKings"), a holding ("shares of X bought by Bank of America
        Corp", "Nvidia takes stake in ..."), or a venue ("to present at Bank of America 2026
        conference", "Bank of America Plaza"). Companies marked `broker: true` in the config are
        also actors as a research or securities arm ("BofA Securities", "at BofA" in analyst
        news) and when they comment ("JPMorgan says/sees ...", not "says its ...")."""
        before, after = title[:s], title[e:]
        action = bool(_ACTION_WORDS.search(title))
        # the action word must be in the same clause: "Tesla cuts prices; analysts trim targets"
        # leaves Tesla the subject
        clause_after, clause_before = _CLAUSE.split(after)[0], _CLAUSE.split(before)[-1]
        act = _ACTIVE.search(after)
        # "Costco downgraded from Hold to Sell" is passive: Costco is the object
        if act and _ACTION_WORDS.search(clause_after) and not _PASSIVE_NEXT.search(after[act.end():]):
            return True
        if _PASSIVE.search(before) and _ACTION_WORDS.search(f"{clause_before} {title[s:e]}{clause_after}"):
            return True
        if _PLACE_AFTER.search(after) or (_AT.search(before) and _VENUE_AFTER.search(after)):
            return True
        if ticker in self.brokers:
            # "<stock> faces JPMorgan target cut" is JPMorgan's target; a headline that opens with
            # "JPMorgan price target raised ..." is about JPMorgan's own stock
            own = _BROKER_OWN.search(clause_after) and (before.strip() or not _TARGET_MOVED.search(clause_after))
            if _BROKER_ARM.search(after) or _SAYS.search(after) or _BROKER_BEFORE.search(before) or own:
                return True
            if _AT.search(before) and (action or _ANALYST_CONTEXT.search(title)):
                return True
        return False

    def tag(self, text: str, wire: bool = False) -> set[str]:
        """The tickers named anywhere in a text."""
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
                # an actor or holder is mentioned only when every one of its title matches is one
                actors = {t for t in order if all(self.is_actor(title, s, e, t) for s, e, x in found if x == t)}
                primary = [t for t in order if t not in listed and t not in actors]
            mentioned = [t for t in order if t not in primary]
            conf = "high" if len(order) == 1 and primary else "low"
        else:
            primary, mentioned = [], list(dict.fromkeys(t for _, _, t in self.matches(summary_text or "", rules)))
            conf = "low" if mentioned else None
        return {"tickers": sorted(set(primary) | set(mentioned)), "primary_tickers": sorted(primary),
                "mentioned_tickers": sorted(mentioned), "tag_confidence": conf}

    def classify_item(self, title: str, summary: str | None, source: str | None, wire: bool = False) -> dict:
        """Tags of an RSS item: its title, and its summary as plain text when the title names no company."""
        return self.classify(title, plain_text(summary, source), wire)

    def tag_item(self, title: str, summary: str | None, source: str | None) -> set[str]:
        """The tickers of an RSS item."""
        return set(self.classify_item(title, summary, source)["tickers"])

    def retag_stored(self, feed, title, tickers, primary, mentioned, confidence,  # noqa: PLR0913
                     tag_version) -> dict:
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
