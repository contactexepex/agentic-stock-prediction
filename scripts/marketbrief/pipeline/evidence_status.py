"""The verification status of cited evidence ids as of a time, per ticker:
- a news id has the status of the newest status row listing it for that ticker (news_status_ids_asof);
- an SEC filing or NSE announcement id is confirmed_primary only when it confirms one of that ticker's
  events: it is among the primary_ids of a cluster status row of that ticker whose status is
  confirmed_primary (news_verified_asof). Any other filing or announcement (another ticker's, or one
  that confirms no event, e.g. a Form 4 or a share allotment) is unverified;
- an id no row lists, or any id before the feature existed, is unverified."""

from __future__ import annotations

import pandas as pd

from marketbrief.constants.verification import STATUS_CONFIRMED_PRIMARY, STATUS_UNVERIFIED
from marketbrief.core.clock import clock
from marketbrief.utils.timefmt import as_utc_timestamp

ACTIVE_SQL = "SELECT count(*) FROM news_verified WHERE as_of <= ?::TIMESTAMPTZ"
IDS_SQL = "SELECT news_id, ticker, status FROM news_status_ids_asof(?::TIMESTAMPTZ) ORDER BY news_id, ticker"
CONFIRMING_SQL = """
SELECT DISTINCT unnest(primary_ids) AS primary_id, ticker FROM news_verified_asof(?::TIMESTAMPTZ)
WHERE level = 'cluster' AND status = 'confirmed_primary' ORDER BY 1, 2"""


def instant(when) -> str:
    """A time as ISO UTC text; a missing time is now (the run's clock)."""
    return (as_utc_timestamp(when) or pd.Timestamp(clock())).isoformat()


class EvidenceStatuses:
    """Status lookups on one DuckDB connection, cached per time."""

    def __init__(self, con):
        """Keep the connection and an empty per-time cache."""
        self.con = con
        self._by_time: dict[str, tuple[dict[str, dict[str, str]], set[tuple[str, str]]]] = {}

    def _tables(self, when) -> tuple[dict[str, dict[str, str]], set[tuple[str, str]]]:
        """The status table and the confirming (id, ticker) pairs as of a time, cached."""
        key = instant(when)
        if key not in self._by_time:
            table: dict[str, dict[str, str]] = {}
            for news_id, ticker, status in self.con.execute(IDS_SQL, [key]).fetchall():
                table.setdefault(news_id, {})[ticker] = status
            confirming = {(p, ticker_name) for p, ticker_name in self.con.execute(CONFIRMING_SQL, [key]).fetchall()}
            self._by_time[key] = (table, confirming)
        return self._by_time[key]

    def active(self, when) -> bool:
        """True when a status row existed by then (the feature was running)."""
        return self.con.execute(ACTIVE_SQL, [instant(when)]).fetchone()[0] > 0

    def of(self, evidence_id: str, ticker: str, when) -> str:
        """The id's status for this ticker as of `when`."""
        table, confirming = self._tables(when)
        if (evidence_id, ticker) in confirming:
            return STATUS_CONFIRMED_PRIMARY
        return table.get(evidence_id, {}).get(ticker, STATUS_UNVERIFIED)
