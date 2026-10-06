"""Metadata and body text of one article page: JSON-LD articleBody, then trafilatura, then newspaper4k (per-domain
order in config/news_sources.yaml `extract`). A page whose JSON-LD says isAccessibleForFree=false is paywalled:
only its description and OpenGraph text are read, never the body."""
from __future__ import annotations

import json

from marketbrief.analytics.news_sources import Sources
from marketbrief.analytics.text_measures import clean_text
from marketbrief.constants.articles import (ACCESS_FULL, ACCESS_PARTIAL, ACCESS_PAYWALLED, DEFAULT_EXTRACT_ORDER,
                                            DEFAULT_FULL_CHARS, DEFAULT_MIN_CHARS, EXTRACTOR_DESCRIPTION,
                                            EXTRACTOR_JSONLD, EXTRACTOR_NEWSPAPER, EXTRACTOR_TRAFILATURA,
                                            MSG_UNPARSABLE_HTML)

ARTICLE_TYPES = ("BlogPosting", "LiveBlogPosting")
DATE_PUBLISHED_META = ("article:published_time", "datePublished", "parsely-pub-date", "publish-date", "pubdate")
DATE_MODIFIED_META = ("article:modified_time", "dateModified")
BYLINE_META = ("article:author", "author", "parsely-author")
DESCRIPTION_META = ("og:description", "description")


def is_false_flag(value) -> bool:
    """True for False, "false" and "http://schema.org/False" style values."""
    return value is False or (isinstance(value, str) and value.strip().lower().rsplit("/", 1)[-1] == "false")


def meta_content(document, *names) -> str | None:
    """The first non-empty <meta> content among the given property, name or itemprop values."""
    for name in names:
        found = document.xpath(f'//meta[@property="{name}" or @name="{name}" or @itemprop="{name}"]/@content')
        if found and found[0].strip():
            return found[0].strip()
    return None


def is_article_type(types) -> bool:
    """True when a JSON-LD @type (one or a list) names an article."""
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and ("Article" in t or t in ARTICLE_TYPES) for t in types)


def json_ld_articles(document) -> list[dict]:
    """The JSON-LD objects of a page that are articles (nested @graph included)."""
    found = []
    for script in document.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            parsed = json.loads(script, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        stack = [parsed]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack += node
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack += node["@graph"] if isinstance(node["@graph"], list) else [node["@graph"]]
                if is_article_type(node.get("@type")):
                    found.append(node)
    return found


def person_names(value) -> list[str]:
    """The names in a JSON-LD author or provider value (a string, an object or a list of them)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [value["name"]] if isinstance(value.get("name"), str) else []
    if isinstance(value, list):
        return [name for item in value for name in person_names(item)]
    return []


def extract_jsonld(article: dict | None) -> str:
    """The articleBody of a JSON-LD article as plain text."""
    body = (article or {}).get("articleBody")
    return clean_text(body) if isinstance(body, str) else ""


def extract_trafilatura(html: str, url: str) -> str:
    """The article text trafilatura finds in a page."""
    import trafilatura
    return clean_text(trafilatura.extract(html, url=url, favor_precision=True, include_comments=False) or "")


def extract_newspaper(html: str, url: str) -> str:
    """The article text newspaper4k finds in a page (fetch_images=False: it would otherwise download images)."""
    import newspaper
    article = newspaper.Article(url, fetch_images=False)
    article.download(input_html=html)
    article.parse()
    return clean_text(article.text)


EXTRACTORS = {EXTRACTOR_JSONLD: None, EXTRACTOR_TRAFILATURA: extract_trafilatura,
              EXTRACTOR_NEWSPAPER: extract_newspaper}


def page_info(document, article: dict | None) -> dict:
    """Dates, byline, provider and description of a page (JSON-LD first, then <meta> tags)."""
    article = article or {}
    return {
        "date_published": article.get("datePublished") or meta_content(document, *DATE_PUBLISHED_META),
        "date_modified": article.get("dateModified") or meta_content(document, *DATE_MODIFIED_META),
        "byline": ", ".join(person_names(article.get("author"))) or meta_content(document, *BYLINE_META),
        "provider": ", ".join(person_names(article.get("provider"))) or None,
        "description": clean_text(article.get("description") or meta_content(document, *DESCRIPTION_META)),
    }


def is_paywalled(article: dict | None) -> bool:
    """True when the JSON-LD article, or a part of it, says it is not accessible for free."""
    if not article:
        return False
    parts = article.get("hasPart")
    parts = parts if isinstance(parts, list) else [parts] if parts else []
    return is_false_flag(article.get("isAccessibleForFree")) or any(
        isinstance(part, dict) and is_false_flag(part.get("isAccessibleForFree")) for part in parts)


def best_text(html: str, url: str, article: dict | None, order: list[str],
              min_chars: int) -> tuple[str, str | None, list]:
    """(longest text, the extractor that gave it, errors): extractors are tried in `order` until one gives at
    least `min_chars` characters; an extractor failing on one page is not fatal."""
    best, best_by, errors = "", None, []
    for name in order:
        try:
            text = extract_jsonld(article) if name == EXTRACTOR_JSONLD else EXTRACTORS[name](html, url)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}")
            continue
        if len(text) > len(best):
            best, best_by = text, name
        if len(text) >= min_chars:
            break
    return best, best_by, errors


def parse_article(html: str, url: str, src: Sources, hints: dict | None = None) -> dict:
    """Metadata and body text of one page (the body stays in memory only). access: full | partial |
    paywalled. Paywalled (isAccessibleForFree false on the article or a part of it): only the
    description / OpenGraph text."""
    from lxml import html as lxml_html
    hints = hints or {}
    try:
        document = lxml_html.fromstring(html)
    except (ValueError, Exception):
        return {"access": ACCESS_PARTIAL, "text": "", "extractor": None, "note": MSG_UNPARSABLE_HTML}
    articles = json_ld_articles(document)
    article = next((a for a in articles if a.get("articleBody")), articles[0] if articles else None)
    info = page_info(document, article)
    if is_paywalled(article):
        return {**info, "access": ACCESS_PAYWALLED, "text": info["description"], "extractor": EXTRACTOR_DESCRIPTION}
    order = hints.get("extract") or DEFAULT_EXTRACT_ORDER
    min_chars = int(src.sel.get("min_chars", DEFAULT_MIN_CHARS))
    full_chars = int(src.sel.get("full_chars", DEFAULT_FULL_CHARS))
    best, best_by, errors = best_text(html, url, article, order, min_chars)
    if not best and info["description"]:
        best, best_by = info["description"], EXTRACTOR_DESCRIPTION
    access = ACCESS_FULL if len(best) >= full_chars and best_by != EXTRACTOR_DESCRIPTION else ACCESS_PARTIAL
    return {**info, "access": access, "text": best, "extractor": best_by, "note": "; ".join(errors) or None}
