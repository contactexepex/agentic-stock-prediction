"""The verification status of cited evidence ids as of a time: an SEC filing or NSE announcement id is a
primary source (confirmed_primary); a news id has the status of the newest status row listing it for
that ticker (news_status_ids_asof); a news id no row lists, or any id before the feature existed, is
unverified."""
from __future__ import annotations

import pandas as pd

from marketbrief.constants.verification import STATUS_CONFIRMED_PRIMARY, STATUS_UNVERIFIED
from marketbrief.core.clock import clock
from marketbrief.utils.timefmt import as_utc_timestamp

PRIMARY_IDS_SQL = "SELECT id FROM filings UNION SELECT id FROM announcements"
ACTIVE_SQL = "SELECT count(*) FROM news_verified WHERE as_of <= ?::TIMESTAMPTZ"
IDS_SQL = "SELECT news_id, ticker, status FROM news_status_ids_asof(?::TIMESTAMPTZ) ORDER BY news_id, ticker"


def instant(when) -> str:
    """A time as ISO UTC text; a missing time is now (the run's clock)."""
    return (as_utc_timestamp(when) or pd.Timestamp(clock())).isoformat()


class EvidenceStatuses:
    """Status lookups on one DuckDB connection, cached per time."""

    def __init__(self, con):
        self.con = con
        self.primary = {r[0] for r in con.execute(PRIMARY_IDS_SQL).fetchall()}
        self._by_time: dict[str, dict[str, dict[str, str]]] = {}

    def _table(self, when) -> dict[str, dict[str, str]]:
        key = instant(when)
        if key not in self._by_time:
            table: dict[str, dict[str, str]] = {}
            for news_id, ticker, status in self.con.execute(IDS_SQL, [key]).fetchall():
                table.setdefault(news_id, {})[ticker] = status
            self._by_time[key] = table
        return self._by_time[key]

    def active(self, when) -> bool:
        """True when a status row existed by then (the feature was running)."""
        return self.con.execute(ACTIVE_SQL, [instant(when)]).fetchone()[0] > 0

    def of(self, evidence_id: str, ticker: str, when) -> str:
        """The id's status for this ticker as of `when`."""
        if evidence_id in self.primary:
            return STATUS_CONFIRMED_PRIMARY
        return self._table(when).get(evidence_id, {}).get(ticker, STATUS_UNVERIFIED)
