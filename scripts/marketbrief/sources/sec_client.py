"""The SEC EDGAR client: one throttled urllib client with fixtures for tests, the acceptance-time
cache and the acceptance-time check of a submissions block (background in marketbrief/sources/sec_filings.py)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from marketbrief.constants.environment import ENV_SEC_FIXTURES
from marketbrief.constants.files import FILE_SEC_ACCEPTANCE_CACHE
from marketbrief.constants.messages import (MSG_SEC_FIXTURE_MISSING, MSG_SEC_TIME_HEADER_FAILED,
                                            MSG_SEC_TIME_MISMATCH, MSG_SEC_TIME_MIXED_FILE, MSG_SEC_TIME_NO_ACCEPTANCE,
                                            MSG_SEC_TIME_NO_FIXTURE, MSG_SEC_TIME_NO_HEADER_TIME)
from marketbrief.constants.sources import (ACCEPT_ENCODING_IDENTITY, SEC_ARCHIVE_URL, SEC_ATTEMPTS,
                                           SEC_MIN_INTERVAL_SECONDS, SEC_RETRY_STATUSES, SEC_SUBMISSIONS_URL,
                                           SEC_TICKER_MAP_URL, SEC_TIMEOUT_SECONDS)
from marketbrief.constants.statuses import STATUS_OK, STATUS_SHIFTED, STATUS_UNVERIFIED
from marketbrief.core import paths
from marketbrief.sources.http import HttpClient, HttpPolicy
from marketbrief.sources.sec_acceptance import is_shifted, sgml_acceptance, unshift, unverified
from marketbrief.utils.timefmt import parse_utc_z


def sec_retry_wait(failed_attempt: int) -> float:
    """Seconds to wait after the n-th throttled or failed SEC answer: 2 s, then 5 s."""
    return 2 + 3 * (failed_attempt - 1)


def archive_url(cik: int | str, accession: str, doc: str = "") -> str:
    """The EDGAR archive URL of a filing's document (the folder when `doc` is empty)."""
    return f"{SEC_ARCHIVE_URL}/{int(cik)}/{accession.replace('-', '')}/{doc}"


class Edgar(HttpClient):
    """SEC EDGAR access: every request goes through one throttle and backs off on 429/5xx; with
    MB_SEC_FIXTURES=<dir> the URLs in <dir>/urls.json are served from files instead of the network."""

    def __init__(self, ua: str):
        policy = HttpPolicy(timeout=SEC_TIMEOUT_SECONDS, attempts=SEC_ATTEMPTS, min_interval=SEC_MIN_INTERVAL_SECONDS,
                            retry_wait=sec_retry_wait, retry_statuses=SEC_RETRY_STATUSES, count_attempts=False)
        super().__init__(policy)
        self.ua = ua
        fixtures_dir = os.environ.get(ENV_SEC_FIXTURES)
        self.fixtures = Path(fixtures_dir) if fixtures_dir else None
        self.urls = json.loads((self.fixtures / "urls.json").read_text()) if fixtures_dir else {}
        self.time_checks: dict[str, str] = {}   # CIK -> ok | shifted | unverified: <why>
        self._accepted: dict[str, str] | None = None   # accession -> true acceptance (format_utc_z)

    def _fixture(self, url: str) -> Path:
        """The fixture file that stands in for a URL."""
        if url not in self.urls:
            raise FileNotFoundError(MSG_SEC_FIXTURE_MISSING.format(url=url))
        return self.fixtures / self.urls[url]

    def open(self, url: str):
        """Streaming response (file-like). Throttled; retries twice on 429/5xx."""
        self.requests += 1
        if self.fixtures:
            return self._fixture(url).open("rb")
        return self.send(url, headers={"User-Agent": self.ua, "Accept-Encoding": ACCEPT_ENCODING_IDENTITY},
                         stream=True)

    def get(self, url: str) -> bytes:
        """The body of a URL."""
        with self.open(url) as response:
            return response.read()

    def json(self, url: str):
        """A URL's body parsed as JSON."""
        return json.loads(self.get(url))

    def cik_map(self) -> dict[str, int]:
        """SEC's ticker -> CIK map."""
        data = self.json(SEC_TICKER_MAP_URL)
        return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}

    def _cache(self) -> dict[str, str]:
        """The accession -> acceptance-time cache, loaded once (not used with fixtures)."""
        if self._accepted is None:
            self._accepted = {}
            if not self.fixtures:
                try:
                    self._accepted = json.loads((paths.ROOT / FILE_SEC_ACCEPTANCE_CACHE).read_text())
                except (OSError, ValueError):
                    pass
        return self._accepted

    def acceptance(self, cik: int | str, accession: str) -> str | None:
        """True acceptance time (UTC, format_utc_z) of a filing from its SGML header (cached)."""
        cache = self._cache()
        if accession not in cache:
            acceptance = sgml_acceptance(self.get(archive_url(cik, accession, f"{accession}.hdr.sgml")))
            if acceptance is None:
                return None
            cache[accession] = acceptance
            if not self.fixtures:
                self._save_cache(cache)
        return cache[accession]

    @staticmethod
    def _save_cache(cache: dict[str, str]) -> None:
        """Write the cache file atomically; a failed write is ignored (the cache only saves requests)."""
        try:
            path = paths.ROOT / FILE_SEC_ACCEPTANCE_CACHE
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(cache))
            temporary.replace(path)
        except OSError:
            pass

    def _verdict(self, cik: int | str, accession: str, json_value: str) -> str:
        """One filing: "ok" (JSON = header), "shifted" (JSON = header + ET offset) or
        "unverified: <why>"."""
        header_url = archive_url(cik, accession, f"{accession}.hdr.sgml")
        if self.fixtures and accession not in self._cache() and header_url not in self.urls:
            return unverified(MSG_SEC_TIME_NO_FIXTURE)      # tests without header fixtures: no request
        try:
            true_value = self.acceptance(cik, accession)
        except Exception as exc:
            return unverified(MSG_SEC_TIME_HEADER_FAILED.format(accession=accession, error=str(exc)[:100]))
        if true_value is None:
            return unverified(MSG_SEC_TIME_NO_HEADER_TIME.format(accession=accession))
        if parse_utc_z(json_value) == parse_utc_z(true_value):
            return STATUS_OK
        if is_shifted(json_value, true_value):
            return STATUS_SHIFTED
        return unverified(MSG_SEC_TIME_MISMATCH.format(accession=accession, json_value=json_value, header=true_value))

    def check_times(self, cik: int | str, block: dict) -> str:
        """Check a submissions block's acceptanceDateTime against the SGML headers of its newest
        and its oldest listed filing (one cached request each; one when they are the same filing)
        and correct the whole column in place only when both are shifted. Both right: "ok".
        Anything else, including a mixed file (one right, one shifted), is "unverified: ..." and
        the column is kept as served: correcting a right value would make it 4-5h too early
        (look-ahead), keeping a shifted one only makes it late."""
        accessions = block.get("accessionNumber") or []
        times = block.get("acceptanceDateTime") or []
        listed = [k for k, v in enumerate(times) if v and k < len(accessions) and accessions[k]]
        if not listed:
            status = unverified(MSG_SEC_TIME_NO_ACCEPTANCE)
        else:
            probes = list(dict.fromkeys([listed[0], listed[-1]]))         # newest, oldest
            verdicts = [self._verdict(cik, accessions[k], times[k]) for k in probes]
            bad = [v for v in verdicts if v.startswith(STATUS_UNVERIFIED)]
            if bad:
                status = bad[0]
            elif len(set(verdicts)) > 1:
                status = unverified(MSG_SEC_TIME_MIXED_FILE.format(
                    newest=accessions[probes[0]], newest_verdict=verdicts[0],
                    oldest=accessions[probes[1]], oldest_verdict=verdicts[1]))
            elif verdicts[0] == STATUS_SHIFTED:
                block["acceptanceDateTimeJson"] = list(times)
                block["acceptanceDateTime"] = [unshift(v) if v else v for v in times]
                status = STATUS_SHIFTED
            else:
                status = STATUS_OK
        self.time_checks[str(int(cik))] = status
        return status

    def recent(self, cik: int) -> dict:
        """The `filings.recent` block of a company's submissions (latest ~1000 filings), with
        `acceptanceDateTime` checked and, if shifted, corrected (check_times)."""
        data = self.json(SEC_SUBMISSIONS_URL.format(cik=int(cik)))
        block = {"name": data.get("name"), **data["filings"]["recent"]}
        self.check_times(cik, block)
        return block
