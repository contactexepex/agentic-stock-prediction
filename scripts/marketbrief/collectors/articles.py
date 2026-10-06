"""Read the article behind this run's material watchlist headlines (news verification phase A,
docs/DESIGN.md section 3a; settings and the outlet allowlist in config/news_sources.yaml).

Selection: see marketbrief/collectors/article_candidates.py.

Per item (paced, `pause_seconds` between requests, one polite User-Agent, TLS verification on):
1. the outlet (Google News <source url> domain, its label, or the link host) must be on the
   allowlist: otherwise access=skipped_unlisted and nothing is requested; an allowlisted outlet with
   `fetch: false` (refuses cloud traffic) is access=blocked without a request;
2. a Google News link is resolved to the publisher URL (googlenewsdecoder: one GET per link and
   one POST per batch to news.google.com; a request hook refuses any request, redirects included,
   that is not HTTPS to google.com); on failure access=undecoded;
3. the publisher URL must be HTTPS on an allowlisted domain (each redirect hop too), else
   skipped_unlisted; a refused request (HTTP status, TLS or network error) is access=blocked;
4. extraction: JSON-LD articleBody -> trafilatura -> newspaper4k; JSON-LD isAccessibleForFree=false
   -> access=paywalled and only the description/OpenGraph text is read; access=full when the body has
   at least `full_chars` characters, else partial.
Stored per row (schema `news_articles` in marketbrief/core/schemas.py): metadata (final URL, domain, tier, status,
dates, byline, JSON-LD provider), the origin agency and its evidence, sources_say, promotional,
at most 3 key sentences of at most 40 words, normalised numbers, a content hash and a MinHash
signature of the 6-word shingles (copy detection in marketbrief/analytics/news_clusters.py). Never the article text.
Article text is untrusted data: it is only measured, never followed as instructions.
At most `max_per_run` items are requested per run (skipped ones do not count); the rest wait for
the next run. Prints a JSON summary (counts by access and domain, requests, seconds, and
`unvetted_domains`: outlets not on the allowlist, with counts, to review and vet later).
Exit 1 only when the run could not start (no config)."""

from __future__ import annotations

import json
import time
from collections import Counter

import pandas as pd

from marketbrief.analytics.article_pages import canonical_url, fetch_page, host_of, url_check
from marketbrief.analytics.news_sources import label_domains, load_sources, outlet_key, outlet_of
from marketbrief.analytics.news_tags import norm
from marketbrief.collectors.article_candidates import candidates, lookback_start
from marketbrief.collectors.article_rows import article_row, base_row
from marketbrief.constants.article_collection import (
    COLLECTOR_ARTICLES,
    DECODER_ERROR_LIMIT,
    DECODER_NAME,
    DEFAULT_DECODE_BATCH,
    DEFAULT_MAX_PER_RUN,
    DEFAULT_MAX_SECONDS,
    DEFAULT_PAUSE_SECONDS,
    EXTRACTION_ERROR_LIMIT,
    MSG_EXTRACTION_FAILED,
    MSG_LINK_NOT_RESOLVED,
    MSG_LINKS_NOT_DECODED,
    MSG_NOT_DECODED,
    MSG_NOT_REQUESTED,
    MSG_OUTLET_NOT_LISTED,
    MSG_SAME_ARTICLE_TITLE,
    MSG_SAME_ARTICLE_URL,
    MSG_STOPPED_AFTER,
    NOTE_DECODE_REQUESTS,
    NOTE_LIMIT,
    UNDECODED_WARNING_SHARE,
    UNVETTED_LIMIT,
)
from marketbrief.constants.articles import (
    ACCESS_BLOCKED,
    ACCESS_PARTIAL,
    ACCESS_SKIPPED_UNLISTED,
    ACCESS_UNDECODED,
    GOOGLE_HOST,
    HTTPS,
    TIER_UNLISTED,
)
from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.config_keys import CFG_MARKET, CFG_TICKERS, META_NAME
from marketbrief.constants.verification import KIND_NEWS_ARTICLES
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET, SUMMARY_WARNINGS
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.article_fetch import Pacer, make_session
from marketbrief.sources.google_news_decoder import decode_google

DECODER = decode_google  # tests replace this
SESSION_FACTORY = make_session  # tests replace this
LEARNED_LABELS_SQL = "SELECT source, source_domain FROM news WHERE first_seen_at >= ? AND first_seen_at <= ?"


class ArticleRun:
    """One run: classify the candidates (skip, copy, read), then read the pages in batches."""

    def __init__(self, cfg: dict, src, now: pd.Timestamp):
        """The article collector's config, source and clock."""
        self.cfg, self.src, self.now = cfg, src, now
        self.market, self.selection = cfg[CFG_MARKET], src.sel
        self.started = time.monotonic()
        self.connection = connect(self.market)
        self.candidates = candidates(self.connection, cfg, src, now)
        self.learned = label_domains(
            self.connection.execute(
                LEARNED_LABELS_SQL, [lookback_start(src, now).to_pydatetime(), now.to_pydatetime()]
            ).fetchall(),
            src,
        )
        self.names = {ticker: [meta[META_NAME], *meta.get("aliases", [])] for ticker, meta in cfg[CFG_TICKERS].items()}
        self.out_path = day_file(self.market, KIND_NEWS_ARTICLES, utc_today())
        self.pacer = Pacer(float(self.selection.get("pause_seconds", DEFAULT_PAUSE_SECONDS)))
        self.cap = int(self.selection.get("max_per_run", DEFAULT_MAX_PER_RUN))
        self.max_seconds = float(self.selection.get("max_seconds", DEFAULT_MAX_SECONDS))
        self.requests_made = {"decode": 0, "fetch": 0}
        self.written: list[dict] = []
        self.failed: list[dict] = []
        self.warnings: list[str] = []
        self.deferred = 0
        self.copies: list[str] = []
        self.unvetted: list[dict] = []
        self.todo: list[dict] = []
        self.same: dict[str, list[dict]] = {}
        self.first_key: dict[tuple, str] = {}
        self.decoder_broken: str | None = None
        self.by_url: dict[str, dict] = {}

    def emit(self, row: dict, candidate: dict | None = None) -> None:
        """Store one row. The same article stored under other news ids (another source label, or the outlet's own
        feed and Google News) is one request and one row per id, copied."""
        append_jsonl(self.out_path, [row])
        self.written.append(row)
        for other in self.same.pop(candidate[COL_ID], []) if candidate else []:
            copy = {
                **row,
                COL_ID: other[COL_ID],
                COL_TICKER: other[COL_TICKER],
                "source_url": other["url"],
                "note": MSG_SAME_ARTICLE_TITLE.format(first_id=candidate[COL_ID]),
            }
            append_jsonl(self.out_path, [copy])
            self.written.append(copy)
            self.copies.append(other[COL_ID])

    def triage(self) -> None:
        """Sort the candidates: unlisted and not-fetched outlets get a row without a request, copies of an
        article already queued wait for it, the first `max_per_run` others are read, the rest are deferred."""
        for candidate in self.candidates:
            if candidate["tier"] == TIER_UNLISTED:
                outlet = candidate["outlet"] or outlet_of(candidate["source"], self.src, self.learned)
                self.unvetted.append({"key": outlet_key(outlet, candidate["source"])})
                self.emit(
                    {
                        **base_row(candidate, utc_now()),
                        "access": ACCESS_SKIPPED_UNLISTED,
                        "note": MSG_OUTLET_NOT_LISTED.format(outlet=candidate["outlet"] or candidate["source"]),
                    }
                )
                continue
            domain, meta = self.src.lookup(candidate["outlet"])
            if meta.get("fetch") is False:
                self.emit(
                    {
                        **base_row(candidate, utc_now()),
                        "access": ACCESS_BLOCKED,
                        "note": MSG_NOT_REQUESTED.format(why=meta.get("note") or "fetch: false"),
                    }
                )
                continue
            key = (norm(candidate["title"]), domain)
            if key in self.first_key:
                self.same.setdefault(self.first_key[key], []).append(candidate)
            elif len(self.todo) < self.cap:
                self.first_key[key] = candidate[COL_ID]
                self.todo.append(candidate)
            else:
                self.deferred += 1

    def decode_batch(self, chunk: list[dict]) -> dict[str, dict]:
        """The decoder's results for the Google News links of a batch ({link: result})."""
        links = [candidate["url"] for candidate in chunk if host_of(candidate["url"]) == GOOGLE_HOST]
        if not links or self.decoder_broken is not None:
            return {}
        try:
            self.pacer.wait()
            results = DECODER(links, self.src)
            self.requests_made["decode"] += len(links) + 1
            return dict(zip(links, results))
        except Exception as exc:  # the decoder relies on an undocumented Google endpoint
            self.decoder_broken = f"{type(exc).__name__}: {str(exc)[:DECODER_ERROR_LIMIT]}"
            self.failed.append({"source": DECODER_NAME, "error": self.decoder_broken})
            return {}

    def resolve_url(self, candidate: dict, decoded: dict[str, dict]) -> str | None:
        """The page URL of a candidate: its own, or the decoded publisher URL of a Google News link; None (the
        row is stored as undecoded) when the link was not resolved."""
        url = candidate["url"]
        if host_of(url) != GOOGLE_HOST:
            return url
        result = decoded.get(url) or {"success": False, "message": self.decoder_broken or MSG_NOT_DECODED}
        if not result.get("success") or not result.get("decoded_url"):
            note = MSG_LINK_NOT_RESOLVED.format(message=str(result.get("message"))[:NOTE_LIMIT])
            self.emit({**base_row(candidate, utc_now()), "access": ACCESS_UNDECODED, "note": note}, candidate)
            return None
        return result["decoded_url"]

    def emit_not_requested(self, candidate: dict, url: str, why: str, domain: str | None) -> None:
        """Store the row of a URL that may not be requested (not HTTPS, not allowlisted, `fetch: false`)."""
        self.emit(
            {
                **base_row(candidate, utc_now()),
                "final_url": url if url.startswith(HTTPS + "://") else None,
                "domain": domain or host_of(url) or candidate["outlet"],
                "tier": self.src.tier(host_of(url)),
                "access": ACCESS_BLOCKED if domain else ACCESS_SKIPPED_UNLISTED,
                "note": MSG_NOT_REQUESTED.format(why=why),
            },
            candidate,
        )

    def emit_unread(self, candidate: dict, page) -> None:
        """Store the row of a page that could not be read (refused request, HTTP error, not HTML)."""
        final_host = host_of(page.final_url)
        listed = self.src.lookup(final_host)[0]
        final_url = page.final_url if (page.final_url or "").startswith(HTTPS + "://") else None
        self.emit(
            {
                **base_row(candidate, utc_now()),
                "final_url": final_url,
                "domain": listed or final_host or candidate["outlet"],
                "tier": self.src.tier(final_host),
                "http_status": page.status,
                "access": ACCESS_SKIPPED_UNLISTED if page.skipped and not listed else ACCESS_BLOCKED,
                "note": page.error,
            },
            candidate,
        )

    def read_candidate(self, session, candidate: dict, decoded: dict[str, dict]) -> None:
        """Resolve, check, fetch and store one candidate."""
        url = self.resolve_url(candidate, decoded)
        if url is None:
            return
        canonical = canonical_url(url)
        if canonical in self.by_url:  # decoded to an article already read in this run
            previous = self.by_url[canonical]
            self.emit(
                {
                    **previous,
                    COL_ID: candidate[COL_ID],
                    COL_TICKER: candidate[COL_TICKER],
                    "source_url": candidate["url"],
                    "note": MSG_SAME_ARTICLE_URL.format(first_id=previous[COL_ID]),
                },
                candidate,
            )
            return
        allowed, why, domain = url_check(url, self.src)
        if not allowed:
            self.emit_not_requested(candidate, url, why, domain)
            return
        self.pacer.wait()
        page = fetch_page(session, url, self.src)
        self.requests_made["fetch"] += page.requests
        if page.html is None:
            self.emit_unread(candidate, page)
            return
        try:
            row = article_row(candidate, page, self.src, self.names.get(candidate[COL_TICKER], []))
        except Exception as exc:  # one bad page never stops the run
            note = MSG_EXTRACTION_FAILED.format(error_type=type(exc).__name__, detail=str(exc)[:EXTRACTION_ERROR_LIMIT])
            row = {
                **base_row(candidate, utc_now()),
                "final_url": page.final_url,
                "http_status": page.status,
                "access": ACCESS_PARTIAL,
                "note": note,
            }
        self.by_url[canonical] = row
        self.emit(row, candidate)

    def read_pages(self) -> None:
        """Read the queued candidates in batches (one decoder call per batch) until done or out of time."""
        session = SESSION_FACTORY()
        batch = int(self.selection.get("decode_batch", DEFAULT_DECODE_BATCH))
        for start in range(0, len(self.todo), batch):
            if time.monotonic() - self.started > self.max_seconds:
                left = self.todo[start:]
                self.deferred += len(left) + sum(
                    len(self.same.get(left_candidate[COL_ID], [])) for left_candidate in left
                )
                self.warnings.append(MSG_STOPPED_AFTER.format(seconds=self.max_seconds, left=len(left)))
                break
            chunk = self.todo[start : start + batch]
            decoded = self.decode_batch(chunk)
            for candidate in chunk:
                self.read_candidate(session, candidate, decoded)
        try:
            session.close()
        except Exception:
            pass

    def summary(self) -> dict:
        """The run's JSON summary."""
        undecoded = sum(1 for row in self.written if row["access"] == ACCESS_UNDECODED)
        tried = sum(1 for candidate in self.todo if host_of(candidate["url"]) == GOOGLE_HOST)
        if tried and undecoded / tried > UNDECODED_WARNING_SHARE:
            self.warnings.append(MSG_LINKS_NOT_DECODED.format(count=undecoded, tried=tried))
        return {
            SUMMARY_COLLECTOR: COLLECTOR_ARTICLES,
            SUMMARY_MARKET: self.market,
            "candidates": len(self.candidates),
            "written": len(self.written),
            "deferred": self.deferred,
            "copied_same_article": len(self.copies),
            # outlets not on the allowlist (never requested), for review: vet and add, or ignore
            "unvetted_domains": dict(
                Counter(stored_row["key"] for stored_row in self.unvetted).most_common(UNVETTED_LIMIT)
            ),
            "by_access": dict(Counter(stored_row["access"] for stored_row in self.written).most_common()),
            "by_domain": dict(
                Counter(f"{stored_row['domain']}:{stored_row['access']}" for stored_row in self.written).most_common()
            ),
            "requests": {**self.requests_made, "total": sum(self.requests_made.values()), "note": NOTE_DECODE_REQUESTS},
            "seconds": round(time.monotonic() - self.started, 1),
            SUMMARY_FAILED: self.failed,
            SUMMARY_WARNINGS: self.warnings,
        }


def main() -> int:
    """Entry point of scripts/collect_articles.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    run = ArticleRun(cfg, load_sources(), pd.Timestamp(clock()))
    run.triage()
    run.read_pages()
    print(json.dumps(run.summary(), indent=2))
    return 0
