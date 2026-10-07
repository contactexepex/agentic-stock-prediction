"""Append-only storage of the intraday kinds: data/<market>/<kind>/YYYY/MM/<UTC date>.jsonl, or the same tree
under an --out folder (live checks that must not touch data/)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from marketbrief.core.storage import append_jsonl, day_file


def kind_file(market: str, kind: str, day: date, out_root: Path | None) -> Path:
    """The day file of a kind, under data/<market>/ or under out_root."""
    if out_root is None:
        return day_file(market, kind, day)
    path = out_root / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_rows(market: str, kind: str, day: date, rows: list[dict], out_root: Path | None) -> int:
    """Append the rows (never rewrites a line)."""
    return append_jsonl(kind_file(market, kind, day, out_root), rows)


def stored_ids(con, kind: str, out_root: Path | None) -> set[str]:
    """Ids of a kind already stored in data/ (through the connection) and, with out_root, under it."""
    ids = {row[0] for row in con.execute(f"SELECT id FROM {kind}").fetchall()}
    if out_root is not None:
        for path in sorted((out_root / kind).glob("**/*.jsonl")):
            ids |= {json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    return ids
