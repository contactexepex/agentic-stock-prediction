"""Fetching the primary texts a results digest quotes, into the existing primary_texts kind (one row per document,
written once; quotes are checked against `text`).

US: the documents (main 8-K/6-K document and EX-99 exhibits: press release, prepared remarks) of the ticker's SEC
filings accepted from the release date to `concall_days` after it, through the Edgar client (SEC_USER_AGENT,
throttled; marketbrief/sources/primary_text.py). The filings come from the stored `filings` rows; when none is
stored for the release date, from the ticker's SEC submissions (8-K/6-K with item 2.02 that day, and the filings of
the following days). India: the attachment of each results or transcript announcement, from NSE's archive host
only (https://nsearchives.nseindia.com); PDF attachments only when `texts.pdf_parser` names an installed parser.
Fetched text is data: it is stored and quoted, never run or followed."""

from __future__ import annotations

import hashlib
import io
import os
import urllib.parse
from datetime import timedelta

import pandas as pd

from marketbrief.collectors.event_timing import timing
from marketbrief.constants.environment import ENV_SEC_USER_AGENT
from marketbrief.constants.events import ITEM_RESULTS
from marketbrief.constants.sources import ACCEPT_LANGUAGE_NSE, NSE_ARCHIVES_HOST, NSE_BASE_URL, NSE_USER_AGENT
from marketbrief.results.constants import (
    ATTACH_NOT_ARCHIVE,
    ATTACH_PDF_NOT_PARSED,
    ATTACH_UNSUPPORTED,
    DOC_ATTACHMENT,
    METHOD_VERSION_RESULTS,
    PDF_PARSER_PYPDF,
    PDF_SUFFIX,
    SOURCE_NSE,
    TEXT_SUFFIXES,
)
from marketbrief.sources.primary_text import filing_text_rows, html_to_text
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.sources.sec_filings import related_ciks, ticker_submissions

FILINGS_SQL = """
SELECT DISTINCT ON (id) id, ticker, cik, form, url, accepted_at FROM filings
WHERE ticker = ? AND list_contains(?, form) AND accepted_at IS NOT NULL AND first_seen_at <= ?::TIMESTAMPTZ
  AND accepted_at <= ?::TIMESTAMPTZ ORDER BY id, first_seen_at"""
STORED_SQL = "SELECT DISTINCT primary_id FROM primary_texts"
ACCEPT_ATTACHMENT = "application/pdf,text/plain,application/xml,text/html,*/*"
PDF_MAX_PAGES = 60


def stored_primary_ids(con) -> set[str]:
    """Primary ids (accession or announcement id) that already have stored text."""
    return {row[0] for row in con.execute(STORED_SQL).fetchall()}


def stored_filings(con, cfg: dict, ticker: str, days: tuple, forms: list[str], now: pd.Timestamp) -> list[dict]:
    """Stored SEC filings of a ticker of the given forms accepted on a local date in days (first, last)."""
    rows = con.execute(FILINGS_SQL, [ticker, forms, now.isoformat(), now.isoformat()]).df().to_dict("records")
    out = []
    for row in rows:
        stamp = pd.Timestamp(row["accepted_at"]).tz_convert("UTC")
        if days[0] <= timing(cfg, stamp)[0] <= days[1]:
            out.append({**row, "accepted_at": stamp.isoformat()})
    return out


def submitted_filings(edgar: Edgar, cfg: dict, ticker: str, days: tuple, forms: list[str]) -> list[dict]:
    """Filings of a ticker from its SEC submissions: the 8-K/6-K with item 2.02 on days[0], and every filing of
    the forms on the following days up to days[1] (prepared remarks are often filed apart)."""
    meta = cfg["tickers"][ticker]
    cik = edgar.cik_map().get(str(meta.get("sec_ticker", ticker)).upper())
    if cik is None:
        return []
    recent, _ = ticker_submissions(edgar, ticker, cik, related_ciks(cfg))
    if recent is None:
        return []
    out, items = [], recent.get("items") or [""] * len(recent["form"])
    for index, form in enumerate(recent["form"]):
        accepted = recent["acceptanceDateTime"][index]
        if form not in forms or not accepted:
            continue
        stamp = pd.Timestamp(accepted).tz_convert("UTC")
        day = timing(cfg, stamp)[0]
        is_results = day == days[0] and ITEM_RESULTS in (items[index] or "")
        if is_results or days[0] < day <= days[1]:
            accession, listing_cik = recent["accessionNumber"][index], recent["cik"][index]
            out.append(
                {
                    "id": accession,
                    "ticker": ticker,
                    "cik": str(listing_cik),
                    "form": form,
                    "url": archive_url(listing_cik, accession, recent["primaryDocument"][index]),
                    "accepted_at": stamp.isoformat(),
                }
            )
    return out


def sec_texts(con, cfg: dict, releases: list, conf: dict, now: pd.Timestamp, fetch: bool) -> tuple[list[dict], dict]:
    """primary_texts rows of the SEC filings around the US releases not stored yet (and a summary)."""
    summary = {"filings": 0, "documents": 0, "failed": [], "skipped": None, "requests": 0}
    if not fetch:
        summary["skipped"] = "--no-fetch"
        return [], summary
    user_agent = os.environ.get(ENV_SEC_USER_AGENT)
    stored, forms = stored_primary_ids(con), list(conf.get("sec_forms") or ["8-K", "8-K/A", "6-K"])
    span = timedelta(days=int(conf.get("concall_days", 3)))
    todo: dict[str, dict] = {}
    edgar = Edgar(user_agent) if user_agent else None
    for release in releases:
        days = (release.release_date, release.release_date + span)
        found = stored_filings(con, cfg, release.ticker, days, forms, now)
        if not any(timing(cfg, pd.Timestamp(row["accepted_at"]))[0] == days[0] for row in found) and edgar:
            try:
                found += submitted_filings(edgar, cfg, release.ticker, days, forms)
            except Exception as exc:  # noqa: BLE001 - one ticker failing is listed, the run goes on
                summary["failed"].append({"id": release.id, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        todo.update({row["id"]: row for row in found if row["id"] not in stored})
    if todo and edgar is None:
        summary["skipped"] = f"{ENV_SEC_USER_AGENT} not set: no filing text fetched"
        return [], summary
    rows, limits = [], (int(conf.get("max_docs", 3)), int(conf.get("max_chars", 40000)))
    for filing in sorted(todo.values(), key=lambda row: row["id"]):
        try:
            rows += filing_text_rows(edgar, filing, limits, now.isoformat())
            summary["filings"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["failed"].append({"id": filing["id"], "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    summary["documents"], summary["requests"] = len(rows), edgar.requests if edgar else 0
    return rows, summary


def is_nse_archive(url: str | None) -> bool:
    """True for an https URL on NSE's archive host (the only host attachments are read from)."""
    parts = urllib.parse.urlsplit(url or "")
    return parts.scheme == "https" and parts.hostname == NSE_ARCHIVES_HOST


def archive_bytes(nse, url: str) -> bytes:
    """An attachment's bytes from NSE's archive host (replay: the file of the same base name)."""
    if nse.replay:
        return (nse.replay / url.rsplit("/", 1)[-1]).read_bytes()
    headers = {
        "User-Agent": NSE_USER_AGENT,
        "Accept": ACCEPT_ATTACHMENT,
        "Accept-Language": ACCEPT_LANGUAGE_NSE,
        "Referer": NSE_BASE_URL + "/",
    }
    return nse.send(url, headers=headers)


def pdf_text(data: bytes, parser: str) -> str:
    """Text of a PDF's first PDF_MAX_PAGES pages with the configured parser (pypdf; imported only when enabled)."""
    if parser != PDF_PARSER_PYPDF:
        raise ValueError(f"unknown pdf_parser {parser!r}")
    import pypdf  # noqa: PLC0415 - optional: only when config/results.yaml enables it

    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:PDF_MAX_PAGES]).strip()


def attachment_status(url: str | None, conf: dict) -> str | None:
    """Why an attachment is not read (None = it is read)."""
    if not is_nse_archive(url):
        return ATTACH_NOT_ARCHIVE
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(PDF_SUFFIX):
        return None if conf.get("pdf_parser") else ATTACH_PDF_NOT_PARSED
    return None if path.endswith(TEXT_SUFFIXES) else ATTACH_UNSUPPORTED


def attachment_row(announcement: dict, text: str, now: pd.Timestamp, max_chars: int) -> dict:
    """The primary_texts row of one NSE announcement attachment."""
    doc = announcement["url"].rsplit("/", 1)[-1]
    return {
        "id": f"{announcement['id']}:{doc}",
        "primary_id": announcement["id"],
        "ticker": announcement["ticker"],
        "source": SOURCE_NSE,
        "form": announcement["category"],
        "doc": doc,
        "doc_type": DOC_ATTACHMENT,
        "url": announcement["url"],
        "available_at": pd.Timestamp(announcement["published_at"]).tz_convert("UTC").isoformat(),
        "fetched_at": now.isoformat(),
        "text": text[:max_chars],
        "chars": len(text),
        "truncated": len(text) > max_chars,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "method_version": METHOD_VERSION_RESULTS,
    }


def nse_texts(con, nse_factory, announcements: list[dict], conf: dict, now: pd.Timestamp, fetch: bool):
    """primary_texts rows of the announcements' attachments not stored yet (and a summary with each skip)."""
    summary = {"attachments": 0, "not_read": {}, "failed": [], "skipped": None}
    stored = stored_primary_ids(con)
    todo = [row for row in announcements if row["id"] not in stored]
    for row in todo:
        status = attachment_status(row.get("url"), conf)
        if status:
            summary["not_read"][row["id"]] = status
    todo = [row for row in todo if row["id"] not in summary["not_read"]]
    if not fetch:
        summary["skipped"] = "--no-fetch"
        return [], summary
    nse = nse_factory() if todo else None
    rows, max_chars = [], int(conf.get("max_chars", 40000))
    for row in todo:
        try:
            data = archive_bytes(nse, row["url"])
            path = urllib.parse.urlsplit(row["url"]).path.lower()
            if path.endswith(PDF_SUFFIX):
                text = pdf_text(data, conf["pdf_parser"])
            elif path.endswith((".htm", ".html", ".xml")):
                text = html_to_text(data)
            else:
                text = data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - one attachment failing is listed, the run goes on
            summary["failed"].append({"id": row["id"], "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue
        if text.strip():
            rows.append(attachment_row(row, text, now, max_chars))
    summary["attachments"] = len(rows)
    return rows, summary
