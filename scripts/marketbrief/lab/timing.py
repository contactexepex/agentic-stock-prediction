"""F1.1 timing and F1.8 locking: D is the first session whose open is after made_at; N+k exits at the close of the
k-th session after D (decision 37; weekends and holidays skipped, special sessions count)."""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from marketbrief.core.calendar import next_session, session_open_utc
from marketbrief.utils.timefmt import as_utc_timestamp



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


def git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    """A git command in `repo`, or None when git cannot run."""
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def in_git_repo(repo: Path) -> bool:
    """True when `repo` is (inside) a git work tree."""
    out = git(repo, "rev-parse", "--is-inside-work-tree")
    return out is not None and out.returncode == 0 and out.stdout.strip() == "true"


def shallow_boundaries(repo: Path) -> set[str]:
    """The commit hashes at a shallow clone's history cut (.git/shallow), empty for a full clone."""
    out = git(repo, "rev-parse", "--git-path", "shallow")
    if out is None or out.returncode != 0:
        return set()
    path = Path(out.stdout.strip())
    path = path if path.is_absolute() else repo / path
    return set(path.read_text().split()) if path.exists() else set()


def first_commit_times(repo: Path, file: Path) -> dict[str, datetime | None]:
    """{line text: committer time of the first commit that added it} for one data file, from `git log -p`; None
    for a line first seen in a shallow clone's boundary commit (its real first commit is cut off). Empty when git
    or the history is not available."""
    out = git(repo, "log", "--reverse", "--format=@@commit %H %cI", "-p", "--", str(file))
    if out is None or out.returncode != 0:
        return {}
    boundaries = shallow_boundaries(repo)
    found: dict[str, datetime | None] = {}
    when, seen = None, False
    for line in out.stdout.splitlines():
        if line.startswith("@@commit "):
            _, sha, stamp = line.split(" ", 2)
            when, seen = (None if sha in boundaries else datetime.fromisoformat(stamp)), True
        elif seen and line.startswith("+") and not line.startswith("+++"):
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
