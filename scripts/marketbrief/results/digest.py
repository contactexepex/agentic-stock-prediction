"""Assembling results digests: each detected release with its stored texts, deterministic numbers, consensus and
reaction (a `Prepared`), whether it is due (no stored digest with the same state key), the results-analyst's input
records and the rows `add` appends to results_digests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd
import yaml

from marketbrief.analytics.claim_numbers import plain_number_tokens
from marketbrief.constants.config_keys import CFG_FILINGS, FILINGS_SOURCE_SEC
from marketbrief.core import paths
from marketbrief.results.constants import (
    FILE_RESULTS_CONFIG,
    KIND_CONCALL,
    KIND_RESULTS,
    METHOD_VERSION_RESULTS,
    NUMBERS_OK,
    NUMBERS_UNAVAILABLE,
    STATUS_OK,
)
from marketbrief.results.detection import Release, detect
from marketbrief.results.gate import ReleaseView, number_values
from marketbrief.results.numbers import india_numbers, us_numbers
from marketbrief.results.sources import TextSource, iso, release_sources, state_key
from marketbrief.results.surprise import consensus, reaction

STORED_SQL = """
SELECT DISTINCT ON (id) id, state_key, status, numbers_status, CAST(bullets AS VARCHAR) AS bullets FROM results_digests
WHERE created_at <= ?::TIMESTAMPTZ ORDER BY id, created_at DESC"""
KEYS_SQL = "SELECT DISTINCT id, state_key FROM results_digests WHERE created_at <= ?::TIMESTAMPTZ"


def load_settings() -> dict:
    """config/results.yaml as parsed."""
    return yaml.safe_load((paths.CONFIG / FILE_RESULTS_CONFIG).read_text()) or {}


@dataclass
class Prepared:
    """One release with everything its digest holds except the agent's bullets."""

    release: Release
    sources: list[TextSource]
    status: str
    numbers_status: str
    numbers_as_of: pd.Timestamp | None
    numbers: dict
    consensus: dict = field(default_factory=dict)
    reaction: dict = field(default_factory=dict)
    state_key: str = ""

    def view(self) -> ReleaseView:
        """What the gate checks this release's bullets against."""
        labels = " ".join(
            str(value or "")
            for value in (
                self.numbers.get("fiscal_label"),
                self.numbers.get("period_end"),
                self.numbers.get("period_start"),
                self.release.release_date,
            )
        )
        tokens = plain_number_tokens(re.sub(r"[^0-9.]", " ", labels))
        return ReleaseView(
            self.release.kind,
            {source.id: source for source in self.sources},
            number_values(self.numbers, self.consensus, self.reaction),
            tokens | {token.lstrip("0") for token in tokens if token.lstrip("0")},
        )


def stored_digests(con, now: pd.Timestamp) -> tuple[dict[str, dict], set[tuple[str, str]]]:
    """(newest stored digest per release id, every (id, state key) stored) as of now."""
    newest = {row["id"]: row for row in con.execute(STORED_SQL, [now.isoformat()]).df().to_dict("records")}
    keys = {(row[0], row[1]) for row in con.execute(KEYS_SQL, [now.isoformat()]).fetchall()}
    return newest, keys


def prepare_release(con, cfg: dict, release: Release, now: pd.Timestamp, settings: dict, extra: list[dict]) -> Prepared:
    """A release with its sources (US: release time from the 2.02 acceptance), numbers, consensus and reaction."""
    sources, status = release_sources(con, cfg, release, now, settings.get("texts") or {}, extra)
    conf = settings.get("numbers") or {}
    if release.kind != KIND_RESULTS:  # a call digest quotes its numbers; the release's are in its results digest
        numbers_status, as_of, numbers = NUMBERS_UNAVAILABLE, None, {}
    elif cfg.get(CFG_FILINGS) == FILINGS_SOURCE_SEC:
        numbers_status, as_of, numbers = us_numbers(con, release, now, conf)
    else:
        numbers_status, as_of, numbers = india_numbers(con, release, now, conf)
    if numbers.get("period_end") and release.period_end is None:
        release.period_end = pd.Timestamp(numbers["period_end"]).date()
    found = Prepared(release, sources, status, numbers_status, as_of, numbers)
    if release.kind == KIND_RESULTS:
        found.consensus = consensus(con, release, now, numbers.get("eps_diluted"), settings.get("consensus") or {})
        found.reaction = reaction(con, cfg, release, now)
    found.state_key = state_key(release, sources, status, numbers_status)
    return found


@dataclass
class Scope:
    """One run's window: its clock, the detection start, an optional ticker filter and, in a dry run, the texts
    fetched into work/ instead of data/."""

    now: pd.Timestamp
    since: pd.Timestamp
    tickers: list[str] | None = None
    extra: list[dict] = field(default_factory=list)


def due_releases(con, cfg: dict, scope: Scope, settings: dict) -> tuple[list[Prepared], dict]:
    """The releases since `scope.since` whose digest is due (no stored row with the same state key), newest first, at
    most `max_releases_per_run`; and a summary."""
    now, since, tickers, extra = scope.now, scope.since, scope.tickers, scope.extra
    releases = detect(con, cfg, now, since, settings.get("texts") or {})
    if tickers:
        releases = [release for release in releases if release.ticker in set(tickers)]
    _, keys = stored_digests(con, now)
    prepared = [prepare_release(con, cfg, release, now, settings, extra or []) for release in releases]
    due = [found for found in prepared if (found.release.id, found.state_key) not in keys]
    limit = int((settings.get("detection") or {}).get("max_releases_per_run", 12))
    info = {
        "detected": len(releases),
        "already_stored": len(prepared) - len(due),
        "due": len(due),
        "deferred": max(0, len(due) - limit),
    }
    return due[:limit], info


def input_record(found: Prepared, cfg: dict, stored: dict | None, max_chars: int) -> dict:
    """The results-analyst's input line of one release."""
    release = found.release
    previous = json.loads(stored["bullets"]) if stored and stored.get("bullets") else []
    return {
        "release_id": release.id,
        "kind": release.kind,
        "ticker": release.ticker,
        "company": cfg["tickers"].get(release.ticker, {}).get("name", release.ticker),
        "release_at": iso(release.release_at),
        "release_date": str(release.release_date),
        "period_end": None if release.period_end is None else str(release.period_end),
        "status": found.status,
        "numbers_status": found.numbers_status,
        "numbers": found.numbers,
        "consensus": found.consensus,
        "reaction": found.reaction,
        "sources": [{**source.meta(), "text": source.text[:max_chars]} for source in found.sources],
        "stored_bullets": previous,
    }


def digest_row(found: Prepared, status: str, bullets: list[dict], prompt_version: str | None, now: str) -> dict:
    """The results_digests row of one release (schema in core/schema_results.py)."""
    release = found.release
    times = [iso(release.release_at), *(source.available_at for source in found.sources)]
    if found.numbers_as_of is not None:
        times.append(iso(found.numbers_as_of))
    if found.consensus.get("consensus_collected_at"):
        times.append(found.consensus["consensus_collected_at"])
    return {
        "id": release.id,
        "release_kind": release.kind,
        "ticker": release.ticker,
        "release_at": iso(release.release_at),
        "release_date": str(release.release_date),
        "release_timing": release.timing,
        "release_time_basis": release.time_basis,
        "period_end": None if release.period_end is None else str(release.period_end),
        "fiscal_label": found.numbers.get("fiscal_label"),
        "basis": found.numbers.get("basis"),
        "currency": found.numbers.get("currency"),
        "status": status,
        "numbers_status": found.numbers_status,
        "numbers_as_of": None if found.numbers_as_of is None else iso(found.numbers_as_of),
        "numbers": found.numbers,
        "consensus": found.consensus,
        "reaction": found.reaction,
        "bullets": bullets,
        "source_ids": [source.id for source in found.sources],
        "sources": [source.meta() for source in found.sources],
        "state_key": found.state_key,
        "inputs_until": max(times),
        "created_at": now,
        "prompt_version": prompt_version,
        "method_version": METHOD_VERSION_RESULTS,
    }


def summary_of(found: Prepared) -> dict:
    """A short line per release for the JSON summaries."""
    release = found.release
    return {
        "release_id": release.id,
        "status": found.status,
        "numbers_status": found.numbers_status,
        "release_at": iso(release.release_at),
        "sources": len(found.sources),
        "needs_agent": found.status == STATUS_OK,
        "concall": release.kind == KIND_CONCALL,
        "numbers": found.numbers_status == NUMBERS_OK,
    }
