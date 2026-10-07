"""The Slack post ledger: one row per posted message part (kind `slack_posts`), so a rerun never double-posts
and later posts find the day's thread. Live runs keep it in data/<market>/slack_posts/ (append-only, committed
by the routine); a dry run keeps its own under work/alerts_dryrun/<market>/."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.core.storage import append_jsonl


class Ledger:
    """Read and append the posted parts of one market."""

    def __init__(self, folder: Path):
        """`folder` is the kind folder (…/slack_posts)."""
        self.folder = folder
        self._rows: list[dict] | None = None

    def rows(self) -> list[dict]:
        """Every stored row, oldest file first."""
        if self._rows is None:
            self._rows = []
            for file in sorted(self.folder.glob(JSONL_GLOB)):
                self._rows += [json.loads(line) for line in file.read_text(encoding=ENCODING_UTF8).splitlines()
                               if line.strip()]
        return self._rows

    def parts_of(self, post_key: str) -> dict[int, dict]:
        """The posted parts of a post: part number -> row."""
        return {int(r["part"]): r for r in self.rows() if r["post_key"] == post_key}

    def thread_ts(self, thread_key: str) -> str | None:
        """The ts of the day's thread: its first message (a row of that thread without a thread_ts)."""
        roots = [r for r in self.rows() if r.get("thread_key") == thread_key and not r.get("thread_ts")]
        return min(roots, key=lambda r: r["posted_at"])["ts"] if roots else None

    def append(self, row: dict) -> None:
        """Append one row to the day file of its posted_at (UTC)."""
        day = datetime.fromisoformat(row["posted_at"].replace("Z", "+00:00")).date()
        path = self.folder / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(path, [row])
        self.rows().append(row)
