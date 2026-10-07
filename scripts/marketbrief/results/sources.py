"""The stored texts a release's digest may quote, as of a time: primary_texts rows fetched and available by then
(plus, in a dry run, the rows just fetched into work/) and, in India, the announcement subjects. Also the release's
status (is there a text to quote?) and its state key (a digest is due again only when these inputs changed)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from marketbrief.collectors.event_timing import timing
from marketbrief.constants.config_keys import CFG_FILINGS, FILINGS_SOURCE_SEC
from marketbrief.results.constants import (
    CONCALL_HEAD_CHARS,
    KIND_CONCALL,
    SOURCE_KIND_ANNOUNCEMENT,
    SOURCE_KIND_ATTACHMENT,
    SOURCE_KIND_FILING,
    SOURCE_NSE,
    SOURCE_SEC,
    STATUS_OK,
    STATUS_TEXT_UNAVAILABLE,
    STATUS_TRANSCRIPT_UNAVAILABLE,
    TIME_ACCEPTED,
)
from marketbrief.results.detection import Release

TEXTS_SQL = """
SELECT DISTINCT ON (id) id, primary_id, ticker, source, form, doc, doc_type, url, text, available_at, fetched_at
FROM primary_texts WHERE ticker = ? AND fetched_at <= ?::TIMESTAMPTZ AND available_at <= ?::TIMESTAMPTZ
ORDER BY id, fetched_at"""
SUBJECTS_SQL = """
SELECT id, category, subject, url, coalesce(published_at, first_seen_at) AS available_at FROM announcements_latest
WHERE list_contains(?, id) AND first_seen_at <= ?::TIMESTAMPTZ ORDER BY id"""


@dataclass
class TextSource:
    """One citable text: its id (document id, or announcement id for a subject), kind, document, url, when it was
    available to us and the stored text."""

    id: str
    kind: str
    doc: str
    url: str | None
    available_at: str
    text: str

    def meta(self) -> dict:
        """The stored description of the source (no text)."""
        return {"id": self.id, "kind": self.kind, "doc": self.doc, "url": self.url, "available_at": self.available_at}


def iso(value) -> str:
    """A timestamp as ISO 8601 UTC, seconds."""
    return pd.Timestamp(value).tz_convert("UTC").floor("s").isoformat()


def text_rows(con, ticker: str, now: pd.Timestamp, extra: list[dict]) -> list[dict]:
    """A ticker's primary_texts rows usable at now: stored ones and, in a dry run, the rows fetched into work/."""
    rows = con.execute(TEXTS_SQL, [ticker, now.isoformat(), now.isoformat()]).df().to_dict("records")
    ids = {row["id"] for row in rows}
    rows += [row for row in extra if row["ticker"] == ticker and row["id"] not in ids]
    return sorted(rows, key=lambda row: row["id"])


def text_source(row: dict, kind: str) -> TextSource:
    """A primary_texts row as a citable source; available once both public and fetched."""
    available = max(iso(row["available_at"]), iso(row["fetched_at"]))
    return TextSource(row["id"], kind, row["doc"], row["url"], available, row["text"] or "")


def is_concall_doc(row: dict, terms: list[str]) -> bool:
    """An SEC EX-99 document whose name or head matches an earnings-call term (prepared remarks, transcript)."""
    if row.get("doc_type") == "primary":
        return False
    head = f"{row['doc']}\n{(row['text'] or '')[:CONCALL_HEAD_CHARS]}".lower()
    return any(term.lower() in head for term in terms)


def is_results_filing(docs: list[dict], marker: str) -> bool:
    """The filing's main document states the results item (e.g. "Item 2.02")."""
    pattern = re.compile(r"\s+".join(map(re.escape, marker.split())), re.I)
    return any(doc.get("doc_type") == "primary" and pattern.search(doc["text"] or "") for doc in docs)


def us_sources(
    cfg: dict, release: Release, rows: list[dict], conf: dict
) -> tuple[list[TextSource], pd.Timestamp | None]:
    """(sources, acceptance time of the 2.02 filing) of a US release: results = the documents of the filings on the
    release date whose main document states the results item; concall = EX-99 documents of the filings from the
    release date to `concall_days` after it that are prepared remarks or a transcript."""
    span = timedelta(days=int(conf.get("concall_days", 3)))
    by_filing: dict[str, list[dict]] = {}
    for row in rows:
        if row["source"] == SOURCE_SEC:
            by_filing.setdefault(row["primary_id"], []).append(row)
    results, accepted = [], []
    concall = []
    for docs in by_filing.values():
        stamp = pd.Timestamp(docs[0]["available_at"]).tz_convert("UTC")
        day = timing(cfg, stamp)[0]
        if not release.release_date <= day <= release.release_date + span:
            continue
        if day == release.release_date and is_results_filing(docs, conf.get("results_item_marker", "Item 2.02")):
            results += docs
            accepted.append(stamp)
        concall += [doc for doc in docs if is_concall_doc(doc, conf.get("concall_terms", []))]
    chosen = concall if release.kind == KIND_CONCALL else results
    return [text_source(row, SOURCE_KIND_FILING) for row in chosen], (min(accepted) if accepted else None)


def india_sources(con, release: Release, rows: list[dict], now: pd.Timestamp) -> list[TextSource]:
    """Sources of an India release: each announcement's subject and its stored attachment text."""
    out = []
    for ann_id, category, subject, url, available in con.execute(
        SUBJECTS_SQL, [release.announcement_ids, now.isoformat()]
    ).fetchall():
        out.append(TextSource(ann_id, SOURCE_KIND_ANNOUNCEMENT, category, url, iso(available), subject or ""))
        out += [
            text_source(row, SOURCE_KIND_ATTACHMENT)
            for row in rows
            if row["source"] == SOURCE_NSE and row["primary_id"] == ann_id
        ]
    return out


def release_sources(con, cfg: dict, release: Release, now: pd.Timestamp, conf: dict, extra: list[dict]):
    """(sources, status) of a release; a US results release gets its 2.02 acceptance time as release_at."""
    rows = text_rows(con, release.ticker, now, extra)
    if release.announcement_ids or cfg.get(CFG_FILINGS) != FILINGS_SOURCE_SEC:
        sources = india_sources(con, release, rows, now)
    else:
        sources, accepted = us_sources(cfg, release, rows, conf)
        if accepted is not None:
            release.release_at, release.time_basis = accepted, TIME_ACCEPTED
            release.release_date, release.timing = timing(cfg, accepted)
    readable = any(source.kind != SOURCE_KIND_ANNOUNCEMENT for source in sources)
    if readable:
        return sources, STATUS_OK
    missing = (
        STATUS_TRANSCRIPT_UNAVAILABLE
        if release.kind == KIND_CONCALL and cfg.get(CFG_FILINGS) == FILINGS_SOURCE_SEC
        else (STATUS_TEXT_UNAVAILABLE)
    )
    return sources, missing


def state_key(release: Release, sources: list[TextSource], status: str, numbers_status: str) -> str:
    """Hash of the inputs that decide a digest: the release, its quotable sources, their status and numbers status."""
    payload = {
        "id": release.id,
        "sources": sorted(source.id for source in sources),
        "status": status,
        "numbers": numbers_status,
        "period_end": str(release.period_end),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
