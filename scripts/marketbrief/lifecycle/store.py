"""Storing lifecycle rows (watchlist_events, command_log) append-only via work/, and reading back what is stored."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import yaml

from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.kinds import KIND_COMMAND_LOG
from marketbrief.core import paths
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.lifecycle.constants import (
    COMMAND_ID_PREFIX,
    DIR_WORK_LIFECYCLE,
    FILE_LIFECYCLE_CONFIG,
    KEY_DIGITS,
    STAMP_FORMAT,
)


def load_lifecycle_config() -> dict:
    """config/lifecycle.yaml."""
    return yaml.safe_load((paths.CONFIG / FILE_LIFECYCLE_CONFIG).read_text())


def iso(stamp: datetime) -> str:
    """ISO 8601 UTC without microseconds."""
    return stamp.replace(microsecond=0).isoformat()


def short_hash(text: str) -> str:
    """The first KEY_DIGITS hex digits of sha256(text)."""
    return hashlib.sha256(text.encode()).hexdigest()[:KEY_DIGITS]


def store_rows(rows: list[dict], kind: str, market: str, stamp: datetime) -> str:
    """Append rows to the day file of `stamp` via a temp file in work/ (never overwriting); returns the path."""
    work = paths.ROOT / DIR_WORK_LIFECYCLE
    work.mkdir(parents=True, exist_ok=True)
    temp = work / f"{kind}-{rows[0]['id']}.jsonl"
    temp.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows))
    target = day_file(market, kind, stamp.date())
    with temp.open(encoding=ENCODING_UTF8) as handle:
        append_jsonl(target, [json.loads(line) for line in handle if line.strip()])
    temp.unlink()
    return target.relative_to(paths.ROOT).as_posix()


def stored_rows(market: str, kind: str) -> list[dict]:
    """Every stored row of a kind, in file order."""
    rows = []
    for path in sorted((paths.data_dir(market) / kind).glob(JSONL_GLOB)):
        rows += [json.loads(line) for line in path.read_text(encoding=ENCODING_UTF8).splitlines() if line.strip()]
    return rows


def command_row(market: str, received: datetime, request: dict, result: str, *,  # noqa: PLR0913 (log fields)
                refusal_code: str | None = None, message: str | None = None, record_ids: list[str] | None = None,
                completed: datetime | None = None) -> dict:
    """One command_log row (core/schema_lifecycle.py) for a lifecycle command."""
    key = request.get("idempotency_key")
    basis = key if key else json.dumps(request.get("arguments") or {}, sort_keys=True, default=str)
    return {
        "id": f"{COMMAND_ID_PREFIX}-{received.strftime(STAMP_FORMAT)}-{short_hash(basis)}", "market": market,
        "received_at": iso(received), "channel": request.get("channel"), "actor": request.get("requested_by"),
        "agent": request.get("agent"), "tool": request.get("tool"), "kind": "write",
        "arguments": request.get("arguments") or {}, "idempotency_key": key, "result": result,
        "refusal_code": refusal_code, "message": message, "record_ids": record_ids or [], "budget_left": None,
        "completed_at": iso(completed or received),
    }


def log_command(market: str, row: dict) -> dict:
    """Append one command_log row and return it as stored; an id already stored (the same key twice in one second)
    gets a -2, -3 ... suffix."""
    taken, base, count = {stored["id"] for stored in stored_rows(market, KIND_COMMAND_LOG)}, row["id"], 1
    while row["id"] in taken:
        count += 1
        row = {**row, "id": f"{base}-{count}"}
    store_rows([row], KIND_COMMAND_LOG, market, datetime.fromisoformat(row["received_at"]))
    return row
