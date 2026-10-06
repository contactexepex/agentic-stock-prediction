"""Append-only JSONL storage: day files, appending rows and reading back recent ids."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from marketbrief.constants.columns import COL_ID
from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.core import paths
from marketbrief.core.schemas import SCHEMAS


def day_file(market: str, kind: str, day: date, ext: str | None = None) -> Path:
    """data/<market>/<kind>/YYYY/MM/YYYY-MM-DD.<ext>, its folder created."""
    ext = ext or SCHEMAS[kind][0]
    path = paths.data_dir(market) / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, rows) -> int:
    """Append rows; never rewrites existing lines."""
    rows = list(rows)
    if rows:
        with path.open("a", encoding=ENCODING_UTF8) as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def recent_ids(market: str, kind: str, days: int, key: str = COL_ID) -> set[str]:
    """Ids seen in the last `days` daily files of a kind (for de-duplication)."""
    ids: set[str] = set()
    files = sorted((paths.data_dir(market) / kind).glob(JSONL_GLOB))[-days:]
    for file in files:
        for line in file.read_text(encoding=ENCODING_UTF8).splitlines():
            if line.strip():
                ids.add(json.loads(line)[key])
    return ids
