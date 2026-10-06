"""Plain text of SEC primary documents for claim checking: an 8-K/6-K main document and its EX-99
exhibits (press releases), read through the Edgar client (throttled; fixtures in tests)."""

from __future__ import annotations

import hashlib
import re

from marketbrief.constants.verification import METHOD_VERSION_CLAIMS
from marketbrief.sources.sec_client import Edgar, archive_url

EXHIBIT_NAME = re.compile(r"ex(?:hibit)?[-_]?99", re.I)
TEXT_SUFFIXES = (".htm", ".html", ".txt")
BLOCK_TAGS = {"p", "div", "td", "th", "tr", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tbody"}
HIDDEN = '//script|//style|//*[contains(translate(@style, " ", ""), "display:none")]'
DOC_PRIMARY, DOC_EXHIBIT = "primary", "EX-99"


def html_to_text(page: bytes | str) -> str:
    """Visible text of an HTML document: scripts, styles and hidden XBRL headers dropped, one line per
    block element, spaces collapsed."""
    from lxml import html as lxml_html

    doc = lxml_html.fromstring(page)
    for hidden in doc.xpath(HIDDEN):
        hidden.drop_tree()
    for element in doc.iter():
        if isinstance(element.tag, str) and element.tag.split("}")[-1].lower() in BLOCK_TAGS:
            element.tail = " \n" + (element.tail or "")
    text = re.sub(r"[ \t\r\f\v ]+", " ", doc.text_content())
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def filing_documents(edgar: Edgar, filing: dict, max_docs: int) -> list[tuple[str, str, str]]:
    """(file name, doc type, url) of a filing's main document and its EX-99 exhibits, at most max_docs."""
    accession, cik = filing["id"], filing["cik"]
    main = filing["url"].rsplit("/", 1)[-1]
    listing = edgar.json(archive_url(cik, accession, "index.json"))["directory"]["item"]
    exhibits = sorted(
        item["name"]
        for item in listing
        if EXHIBIT_NAME.search(item["name"]) and item["name"].lower().endswith(TEXT_SUFFIXES)
    )
    docs = [(main, DOC_PRIMARY, filing["url"])]
    docs += [(name, DOC_EXHIBIT, archive_url(cik, accession, name)) for name in exhibits if name != main]
    return docs[:max_docs]


def filing_text_rows(edgar: Edgar, filing: dict, limits: tuple[int, int], fetched_at: str) -> list[dict]:
    """primary_texts rows of one SEC filing (schema in core/schema_verification.py). limits: (max
    documents, max characters kept per document)."""
    max_docs, max_chars = limits
    rows = []
    for name, doc_type, url in filing_documents(edgar, filing, max_docs):
        text = (
            html_to_text(edgar.get(url))
            if not name.lower().endswith(".txt")
            else edgar.get(url).decode("utf-8", errors="replace")
        )
        rows.append(
            {
                "id": f"{filing['id']}:{name}",
                "primary_id": filing["id"],
                "ticker": filing["ticker"],
                "source": "sec",
                "form": filing["form"],
                "doc": name,
                "doc_type": doc_type,
                "url": url,
                "available_at": filing["accepted_at"],
                "fetched_at": fetched_at,
                "text": text[:max_chars],
                "chars": len(text),
                "truncated": len(text) > max_chars,
                "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "method_version": METHOD_VERSION_CLAIMS,
            }
        )
    return rows
