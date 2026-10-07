"""The explainer's input (prepare) and storage (add) around the gate in explain_gate.py."""

from __future__ import annotations

import json
from pathlib import Path

from marketbrief.core.clock import utc_now, utc_today
from marketbrief.intraday.constants import KIND_INTRADAY_EXPLANATIONS, MSG_PATH_DOES_NOT_EXIST
from marketbrief.intraday.explain_gate import parse_lines, validate_records
from marketbrief.intraday.inputs import records
from marketbrief.intraday.settings import explanation_id
from marketbrief.intraday.store import write_rows

JSON_COLUMNS = ("calls", "candidates")


def flagged_rows(con, check: str | None = None) -> dict[str, dict]:
    """{row id: row} of the stored flagged check rows (one check's when `check` is given), JSON parsed."""
    where, params = ("AND check_id = ?", [check]) if check else ("", [])
    frame = con.execute(
        f"SELECT DISTINCT ON (id) * FROM intraday_checks WHERE flagged {where} ORDER BY id, computed_at", params
    ).df()
    out = {}
    for row in records(frame):
        for key in JSON_COLUMNS:
            row[key] = json.loads(row[key]) if isinstance(row[key], str) else (row[key] or [])
        for key in ("flags", "candidate_ids", "notes"):
            row[key] = list(row[key]) if row[key] is not None else []
        for key in ("check_at", "last_time", "computed_at"):
            row[key] = row[key].isoformat() if row.get(key) is not None else None
        row["session_date"] = str(row["session_date"])[:10]
        out[row["id"]] = row
    return out


def explained_ids(con) -> set[str]:
    """Check row ids that already have a stored note."""
    return {row[0] for row in con.execute("SELECT check_row_id FROM intraday_explanations").fetchall()}


def latest_check_id(con) -> str | None:
    """The newest check that wrote rows."""
    found = con.execute("SELECT id FROM intraday_runs WHERE written > 0 ORDER BY check_at DESC, id LIMIT 1").fetchall()
    return found[0][0] if found else None


def prepare(con, out: Path, check: str | None) -> dict:
    """Write the flagged rows without a note (of `check`, default the newest check) to `out`."""
    check = check or latest_check_id(con)
    done = explained_ids(con)
    todo = [row for ident, row in sorted(flagged_rows(con, check).items()) if ident not in done] if check else []
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row, default=str) + "\n" for row in todo), encoding="utf-8")
    return {"check_id": check, "flags": str(out), "n": len(todo), "already_explained": len(done)}


def check_file(con, path: Path, settings: dict) -> tuple[list[dict], list[dict], int, dict]:
    """(valid records, errors, record count, rows) of an explainer file."""
    if not path.exists():
        raise SystemExit(MSG_PATH_DOES_NOT_EXIST.format(path=path))
    recs = parse_lines(path.read_text(encoding="utf-8"))
    rows = flagged_rows(con)
    good, bad = validate_records(recs, rows, explained_ids(con), settings)
    return good, bad, len(recs), rows


def add(market: str, good: list[dict], rows: dict) -> tuple[int, str]:
    """Append the valid notes; the row facts come from the stored check row, never the agent's copy."""
    now = utc_now()
    out = []
    for rec in good:
        row = rows[rec["check_row_id"]]
        out.append({
            "id": explanation_id(row["id"]), "check_row_id": row["id"], "check_id": row["check_id"],
            "check_at": row["check_at"], "session_date": row["session_date"], "ticker": row["ticker"],
            "flags": row["flags"], "attribution": rec["attribution"], "text": rec["text"],
            "cited_ids": rec["cited_ids"], "prompt_version": rec["prompt_version"], "created_at": now,
        })
    day = utc_today()
    write_rows(market, KIND_INTRADAY_EXPLANATIONS, day, out, None)
    return len(out), f"data/{market}/{KIND_INTRADAY_EXPLANATIONS}/{day:%Y/%m/%Y-%m-%d}.jsonl"
