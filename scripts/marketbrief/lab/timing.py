"""F1.1 timing and F1.8 locking: D is the first session whose open is after made_at; N+k exits at the close of the
k-th session after D (decision 37; weekends and holidays skipped, special sessions count)."""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from marketbrief.contracts.horizons import HORIZON_LABEL_N_PLUS_K
from marketbrief.core.calendar import next_session, session_open_utc
from marketbrief.utils.timefmt import as_utc_timestamp

LEGACY_5D_SESSIONS_AFTER_D = 4   # legacy_5d_d4: exit at the close of D+4, 4 sessions after D


def entry_session(cfg: dict, made_at: datetime) -> date:
    """D: the first session of the market calendar whose open is after `made_at`."""
    when = as_utc_timestamp(made_at).to_pydatetime()
    day = next_session(cfg, when.date() - timedelta(days=1), include=True)   # a day early: zones east of UTC
    while session_open_utc(cfg, day) <= when:
        day = next_session(cfg, day, include=False)
    return day


def exit_session(cfg: dict, entry_date: date, horizon_days: int) -> date:
    """The k-th session after D (a Friday entry with k = 1 exits on Monday's close)."""
    day = entry_date
    for _ in range(int(horizon_days)):
        day = next_session(cfg, day, include=False)
    return day


def sessions_after_d(horizon_days: int, horizon_label: str | None) -> int:
    """How many sessions after D a stored horizon exits: N+k exits k after D; the legacy open-to-close 5d
    (legacy_5d_d4, rows without a label) exits at D+4; the legacy 1d (= N+1) one after D."""
    if horizon_label == HORIZON_LABEL_N_PLUS_K or int(horizon_days) not in (1, 5):
        return int(horizon_days)
    return 1 if int(horizon_days) == 1 else LEGACY_5D_SESSIONS_AFTER_D


def first_commit_times(repo: Path, file: Path) -> dict[str, datetime]:
    """{line text: committer time of the first commit that added it} for one data file, from `git log -p`
    (empty when git or the history is not available)."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "log", "--reverse", "--format=@@commit %cI", "-p", "--",
                              str(file)], capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    found: dict[str, datetime] = {}
    when = None
    for line in out.stdout.splitlines():
        if line.startswith("@@commit "):
            when = datetime.fromisoformat(line.split(" ", 1)[1])
        elif when is not None and line.startswith("+") and not line.startswith("+++"):
            found.setdefault(line[1:], when)
    return found


def is_locked(prediction: dict, cfg: dict, first_committed_at: datetime | None) -> bool:
    """F1.8: made_at before D's open and, when git can tell, the row first committed before it too."""
    entry = prediction["session_date"]
    entry = entry if isinstance(entry, date) else date.fromisoformat(str(entry)[:10])
    opening = session_open_utc(cfg, entry)
    if as_utc_timestamp(prediction["made_at"]).to_pydatetime() >= opening:
        return False
    return first_committed_at is None or as_utc_timestamp(first_committed_at).to_pydatetime() < opening
