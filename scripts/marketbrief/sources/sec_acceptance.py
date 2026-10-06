"""SEC acceptance-time arithmetic: the New York offset, the SGML header time, the shift test and its inverse,
and the collectors' summary of the checks.

Background (docs in sources/sec_filings.py): the submissions JSON's `acceptanceDateTime` is sometimes shifted
later by the New York UTC offset (+4h EDT, +5h EST) for a whole CIK's file; the SGML header's
`<ACCEPTANCE-DATETIME>` (US Eastern) is the authority."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from marketbrief.constants.messages import MSG_SEC_TIME_UNVERIFIED_WARNING
from marketbrief.constants.statuses import STATUS_OK, STATUS_SHIFTED, STATUS_UNVERIFIED, UNVERIFIED_PREFIX
from marketbrief.utils.timefmt import format_utc_z, parse_utc_z

EASTERN = ZoneInfo("America/New_York")  # EDGAR's clock (SGML header and index page times)
SGML_ACCEPTANCE_PATTERN = re.compile(rb"<ACCEPTANCE-DATETIME>\s*(\d{14})")
SGML_ACCEPTANCE_FORMAT = "%Y%m%d%H%M%S"
CANDIDATE_OFFSET_HOURS = (5, 4)  # EST's 5 is tried first when unshifting around a DST change


def et_offset_hours(instant: datetime) -> int:
    """Hours New York is behind UTC at that instant (4 in EDT, 5 in EST)."""
    return int(-instant.astimezone(EASTERN).utcoffset().total_seconds() // 3600)


def sgml_acceptance(header: bytes) -> str | None:
    """<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS (US Eastern) of a filing's SGML header -> UTC (format_utc_z)."""
    match = SGML_ACCEPTANCE_PATTERN.search(header)
    if not match:
        return None
    return format_utc_z(datetime.strptime(match.group(1).decode(), SGML_ACCEPTANCE_FORMAT).replace(tzinfo=EASTERN))


def is_shifted(json_value: str, true_value: str) -> bool:
    """The submissions-JSON error: the JSON time is later than the true one by exactly the ET
    UTC offset at the true instant."""
    true_instant = parse_utc_z(true_value)
    return parse_utc_z(json_value) - true_instant == timedelta(hours=et_offset_hours(true_instant))


def unshift(json_value: str) -> str:
    """Invert the shift: true = JSON - h with h the ET offset at the true instant (h = 4 or 5,
    the one consistent with itself; around a DST change, where both could be, EST's 5 is tried
    first; filings are not accepted at 1-3am on a Sunday, so this never matters in practice)."""
    shifted = parse_utc_z(json_value)
    for hours in CANDIDATE_OFFSET_HOURS:
        if et_offset_hours(shifted - timedelta(hours=hours)) == hours:
            return format_utc_z(shifted - timedelta(hours=hours))
    return format_utc_z(shifted - timedelta(hours=et_offset_hours(shifted)))


def time_summary(edgar) -> dict:
    """Collector summary of the acceptance-time checks: {"ok": n, "shifted": [CIK], "unverified": {CIK: why}}."""
    checks = getattr(edgar, "time_checks", {})
    return {
        STATUS_OK: sum(status == STATUS_OK for status in checks.values()),
        STATUS_SHIFTED: sorted(cik for cik, status in checks.items() if status == STATUS_SHIFTED),
        STATUS_UNVERIFIED: {
            cik: status.split(": ", 1)[-1] for cik, status in checks.items() if status.startswith(STATUS_UNVERIFIED)
        },
    }


def time_warnings(checked) -> list[str]:
    """One warning per CIK whose acceptance times could not be verified (stored as served, maybe
    4-5h late): for the collectors' `warnings` (the routine lists them in data_quality). Takes the
    Edgar client or a time_summary dict."""
    summary = checked if isinstance(checked, dict) else time_summary(checked)
    return [
        MSG_SEC_TIME_UNVERIFIED_WARNING.format(cik=cik, why=why)
        for cik, why in (summary.get(STATUS_UNVERIFIED) or {}).items()
    ]


def unverified(why: str) -> str:
    """A check status that says the time could not be verified, with the reason."""
    return f"{UNVERIFIED_PREFIX}{why}"
