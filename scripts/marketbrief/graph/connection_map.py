"""The connection map: edges between watchlist companies and the people and companies around them."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from marketbrief.constants.connection_map import (
    MSG_ALIASES_MUST_BE_A_LIST_OF,
    MSG_AS_OF_IS_IN_THE_FUTURE,
    MSG_AS_OF_MUST_BE_YYYY_MM,
    MSG_NOT_JSON,
    MSG_RELATION_NOT_ONE_OF,
    MSG_SOURCE_URL_MUST_BE_THE_HTTP,
    MSG_STATUS_NOT_ONE_OF,
    MSG_TARGET_KIND_NOT_ONE_OF,
    MSG_TARGET_NAME_MISSING,
    MSG_TARGET_TICKER_MUST_BE_A_STRING,
    MSG_TICKER_NOT_IN_THE_WATCHLIST,
    MSG_WEIGHT_MUST_BE_A_NUMBER_OR,
)
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.utils.text import slugify

RELATIONS = ("board", "group", "subsidiary", "supplier", "customer", "competitor", "promoter", "major_holder")

TARGET_KINDS = ("person", "company")

STATUSES = ("active", "removed")

COMPARE = (
    "ticker",
    "relation",
    "target",
    "target_kind",
    "target_ticker",
    "aliases",
    "detail",
    "weight",
    "status",
    "as_of",
    "source_url",
)

MIN_NAME = 3  # shorter names/aliases are never matched against headlines


def edge_id(ticker: str, relation: str, target: str) -> str:
    """The stable id of an edge from ticker, relation and target."""
    return f"{ticker}|{relation}|{slugify(target)}"


def load_edges(con, ticker: str | None = None) -> list[dict]:
    """The latest version of every stored edge, optionally of one ticker."""
    sql = "SELECT * FROM graph_edges" + (" WHERE ticker = ?" if ticker else "") + " ORDER BY ticker, relation, target"
    cur = con.execute(sql, [ticker] if ticker else [])
    cols = [column[0] for column in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def normalise_as_of_and_aliases(record: dict, today: date) -> list[str]:
    """Check and normalise the `as_of` date and the alias list of one edge (in place); return the problems."""
    errs = []
    try:
        as_of = date.fromisoformat(str(record["as_of"]))
        if as_of > today:
            errs.append(MSG_AS_OF_IS_IN_THE_FUTURE)
        record["as_of"] = str(as_of)
    except ValueError:
        errs.append(MSG_AS_OF_MUST_BE_YYYY_MM)
    aliases = record["aliases"] or []
    if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
        errs.append(MSG_ALIASES_MUST_BE_A_LIST_OF)
    else:
        record["aliases"] = sorted({alias.strip() for alias in aliases if alias.strip()})
    return errs


def validate(row: dict, tickers: set[str], today: date) -> tuple[dict | None, list[str]]:
    """Normalise one edge from the agent; return (edge, errors)."""
    errs = []
    record = {key: row.get(key) for key in COMPARE + ("prompt_version",)}
    if record["ticker"] not in tickers:
        errs.append(MSG_TICKER_NOT_IN_THE_WATCHLIST.format(ticker=record["ticker"]))
    if record["relation"] not in RELATIONS:
        errs.append(MSG_RELATION_NOT_ONE_OF.format(relation=record["relation"], relations=RELATIONS))
    if not isinstance(record["target"], str) or len(record["target"].strip()) < 2:
        errs.append(MSG_TARGET_NAME_MISSING)
    if record["target_kind"] not in TARGET_KINDS:
        errs.append(MSG_TARGET_KIND_NOT_ONE_OF.format(target_kind=record["target_kind"], target_kinds=TARGET_KINDS))
    if not str(record["source_url"] or "").startswith(("https://", "http://")):
        errs.append(MSG_SOURCE_URL_MUST_BE_THE_HTTP)
    record["status"] = record["status"] or "active"
    if record["status"] not in STATUSES:
        errs.append(MSG_STATUS_NOT_ONE_OF.format(status=record["status"], statuses=STATUSES))
    errs += normalise_as_of_and_aliases(record, today)
    if record["weight"] is not None and not isinstance(record["weight"], (int, float)):
        errs.append(MSG_WEIGHT_MUST_BE_A_NUMBER_OR)
    if record["target_ticker"] is not None and not isinstance(record["target_ticker"], str):
        errs.append(MSG_TARGET_TICKER_MUST_BE_A_STRING)
    if errs:
        return None, errs
    record["target"] = record["target"].strip()
    record["id"] = edge_id(record["ticker"], record["relation"], record["target"])
    record["prompt_version"] = record["prompt_version"] or "graph-v4"
    return record, []


def add(cfg: dict, con, path: Path, dry_run: bool = False) -> dict:
    """Validate the edges in path and append the new or changed ones. dry_run (`check`) only
    validates and counts what would be written: the graph-builder runs it, the caller runs `add`
    after the judge passes the file."""
    today, now = utc_today(), utc_now()
    current = {stored_edge["id"]: stored_edge for stored_edge in load_all_latest(con)}
    tickers = set(cfg["tickers"])
    new, rejected, unchanged = {}, [], 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            rejected.append({"line": line_number, "errors": [MSG_NOT_JSON.format(error=exc)]})
            continue
        edge, errs = validate(row, tickers, today)
        if errs:
            rejected.append({"line": line_number, "target": row.get("target"), "errors": errs})
            continue
        old = current.get(edge["id"])
        if old and all(same_value(old.get(key), edge.get(key)) for key in COMPARE):
            unchanged += 1
            continue
        if edge["status"] == "removed" and not old:
            rejected.append(
                {"line": line_number, "target": edge["target"], "errors": ["removing an edge that does not exist"]}
            )
            continue
        new[edge["id"]] = {
            "id": edge["id"],
            **{key: edge[key] for key in COMPARE},
            "added_at": now,
            "prompt_version": edge["prompt_version"],
        }
    if dry_run:
        return {
            "step": "graph_check",
            "market": cfg["market"],
            "would_write": len(new),
            "unchanged": unchanged,
            "rejected": rejected,
        }
    written = append_jsonl(day_file(cfg["market"], "graph", today), new.values())
    return {
        "step": "graph_add",
        "market": cfg["market"],
        "written": written,
        "unchanged": unchanged,
        "rejected": rejected,
    }


def load_all_latest(con) -> list[dict]:
    """Latest version of every edge id, including removed ones (to compare before appending)."""
    cur = con.execute("SELECT DISTINCT ON (id) * FROM graph ORDER BY id, added_at DESC")
    cols = [column[0] for column in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def comparable(value):
    """A stored or new field value in a form that compares equal across lists, tuples and text."""
    if isinstance(value, (list, tuple)):
        return sorted(value)
    return str(value) if value is not None else None


def same_value(first, second) -> bool:
    """True when two edge field values are equal after normalisation."""
    return comparable(first) == comparable(second)


def status(cfg: dict, con) -> dict:
    """Edge counts and ticker coverage of the connection map."""
    edges = load_edges(con)
    last = con.execute("SELECT max(added_at) FROM graph").fetchone()[0]
    last_run = con.execute("SELECT max(run_at) FROM graph_runs").fetchone()[0]
    month = f"{utc_today():%Y-%m}"
    by_rel: dict[str, int] = {}
    for edge in edges:
        by_rel[edge["relation"]] = by_rel.get(edge["relation"], 0) + 1
    covered = {edge["ticker"] for edge in edges}
    # Due until a refresh attempt is recorded for the current UTC month (edges or not).
    attempted = con.execute("SELECT count(*) FROM graph_runs WHERE month = ?", [month]).fetchone()[0] > 0
    return {
        "market": cfg["market"],
        "edges": len(edges),
        "by_relation": by_rel,
        "tickers_without_edges": [ticker for ticker in cfg["tickers"] if ticker not in covered],
        "last_added_at": last.isoformat() if last else None,
        "last_attempt_at": last_run.isoformat() if last_run else None,
        "refresh_due": not attempted,
    }


def attempt(cfg: dict, con, note: str | None = None) -> dict:
    """Append one refresh-attempt record (current edge count) to data/<market>/graph_runs/."""
    status_and_time, now = status(cfg, con), utc_now()
    row = {
        "id": f"{cfg['market']}-graph-run-{now}",
        "run_at": now,
        "month": f"{utc_today():%Y-%m}",
        "edges": status_and_time["edges"],
        "tickers_without_edges": len(status_and_time["tickers_without_edges"]),
        "note": note,
    }
    append_jsonl(day_file(cfg["market"], "graph_runs", utc_today()), [row])
    return {"step": "graph_attempt", **row}
