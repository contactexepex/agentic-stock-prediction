"""The contract checks of the read models (docs/ws/b4.md "Contract tests"): a served response validates against its
operation's 200 schema in api/openapi.yaml, and its payload matches the approved mockup's data.json in shape.

serve(row, mode, now) is what the route returns for a stored rm row (web/lib/data/serve.ts does the same; the shared
fixture web/lib/data/tests/serve.fixture.json keeps the two equal):
  verbatim  the payload as stored (1.0 pages)
  page      plus `cutoff` and `built_at` at the top and `freshness` in the `status` block (2.0 page payloads)
  status    plus `freshness` at the top (the status page)
freshness = {state, built_at, age_minutes}: age = whole minutes from built_at to the request time (never below 0);
state fresh up to FRESH_MINUTES, stale after, unknown without built_at. Times are ISO UTC with a Z, to the second.

Shape: every key of the mockup's object must be in the payload and every payload key in the mockup (an object at a
`map_paths` path is a map with data keys: its values are compared); list items are compared with the merged shape
of the mockup's items (a key every mockup item has is required, one some have is optional); null matches any type,
integer and float are both numbers, and an empty mockup list says nothing about its items."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from marketbrief.constants.warehouse import (
    FRESH_MINUTES,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    SERVE_PAGE,
    SERVE_STATUS,
)
from marketbrief.warehouse import schema_check

META_FIELDS = ("market", "page_key", "as_of", "cutoff", "built_at", "schema_version", "source_commit", "payload_sha256")
STATUS_KEY = "status"
SECONDS_PER_MINUTE = 60


def iso_second(value) -> str | None:
    """A time as ISO UTC to the second with a Z, or None."""
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value) -> str | None:
    """A date as YYYY-MM-DD, or None."""
    return None if value is None else str(value)[:10]


def freshness(built_at, now: datetime) -> dict:
    """How old a page is at `now`."""
    if built_at is None:
        return {"state": FRESHNESS_UNKNOWN, "built_at": None, "age_minutes": None}
    age = max(int((pd.Timestamp(now) - pd.Timestamp(built_at)).total_seconds() // SECONDS_PER_MINUTE), 0)
    return {
        "state": FRESHNESS_FRESH if age <= FRESH_MINUTES else FRESHNESS_STALE,
        "built_at": iso_second(built_at),
        "age_minutes": age,
    }


def served_payload(row: dict, mode: str, now: datetime) -> dict:
    """The payload the route returns for a stored row."""
    payload = row["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    fresh = freshness(row.get("built_at"), now)
    if mode == SERVE_STATUS:
        return {**payload, "freshness": fresh}
    if mode != SERVE_PAGE:
        return payload
    out = {**payload, "cutoff": iso_second(row.get("cutoff")), "built_at": iso_second(row.get("built_at"))}
    if isinstance(out.get(STATUS_KEY), dict):
        out[STATUS_KEY] = {**out[STATUS_KEY], "freshness": fresh}
    return out


def serve(row: dict, mode: str, now: datetime) -> dict:
    """The whole response body: the envelope (times to the second) and the served payload."""
    meta = {key: row.get(key) for key in META_FIELDS}
    meta.update(as_of=iso_date(meta["as_of"]), cutoff=iso_second(meta["cutoff"]), built_at=iso_second(meta["built_at"]))
    return {**meta, "payload": served_payload(row, mode, now)}


# ---------- shape ----------
@dataclass
class Shape:
    """The merged shape of one or more mockup values: kind null|boolean|number|string|array|object|map|any."""

    kind: str
    item: Shape | None = None  # array items, map values
    keys: dict[str, tuple[Shape, bool]] = field(default_factory=dict)  # object key -> (shape, required)


KINDS = ((bool, "boolean"), ((int, float), "number"), (str, "string"), (list, "array"), (dict, "object"))


def kind_of(value) -> str:
    """The JSON kind of a value (a bool is a boolean, not a number)."""
    if value is None:
        return "null"
    return next(name for types, name in KINDS if isinstance(value, types))


def merge(first: Shape | None, second: Shape | None) -> Shape | None:
    """The shape both values fit (null fits anything; two different kinds give `any`)."""
    if first is None or first.kind == "null":
        return second if second is not None else first
    if second is None or second.kind == "null":
        return first
    if first.kind != second.kind:
        return Shape("any")
    if first.kind in ("array", "map"):
        return Shape(first.kind, item=merge(first.item, second.item))
    if first.kind == "object":
        keys = {}
        for name in first.keys.keys() | second.keys.keys():
            one, two = first.keys.get(name), second.keys.get(name)
            shape = merge(one[0] if one else None, two[0] if two else None)
            keys[name] = (shape, bool(one and two and one[1] and two[1]))
        return Shape("object", keys=dict(sorted(keys.items())))
    return first


def describe(value, where: str, maps: tuple[str, ...]) -> Shape:
    """The shape of one mockup value at path `where`."""
    kind = kind_of(value)
    if kind == "array":
        item = None
        for element in value:
            item = merge(item, describe(element, f"{where}[]", maps))
        return Shape("array", item=item)
    if kind == "object" and where in maps:
        item = None
        for element in value.values():
            item = merge(item, describe(element, f"{where}{{}}", maps))
        return Shape("map", item=item)
    if kind == "object":
        return Shape("object", keys={k: (describe(v, f"{where}.{k}", maps), True) for k, v in value.items()})
    return Shape(kind)


def object_problems(value: dict, shape: Shape, where: str, extra_keys: tuple[str, ...]) -> list[str]:
    """Missing and unknown keys of an object, then each key's own problems."""
    out = [
        f"{where}: missing {name!r}" for name, (_s, required) in shape.keys.items() if required and name not in value
    ]
    out += [
        f"{where}: {name!r} is not in the mockup" for name in value if name not in shape.keys.keys() | set(extra_keys)
    ]
    for name, item in value.items():
        if name in shape.keys:
            out += problems(item, shape.keys[name][0], f"{where}.{name}")
    return out


def problems(value, shape: Shape | None, where: str, extra_keys: tuple[str, ...] = ()) -> list[str]:
    """How `value` differs from `shape` (empty = it matches)."""
    if shape is None or value is None or shape.kind in ("null", "any"):
        return []
    kind = kind_of(value)
    expected = "object" if shape.kind == "map" else shape.kind
    if kind != expected:
        return [f"{where}: expected {'a map' if shape.kind == 'map' else expected}, got {kind}"]
    if shape.kind == "map":
        return [p for key, item in value.items() for p in problems(item, shape.item, f"{where}{{{key}}}")]
    if kind == "array":
        return [p for index, item in enumerate(value) for p in problems(item, shape.item, f"{where}[{index}]")]
    return object_problems(value, shape, where, extra_keys) if kind == "object" else []


def shape_problems(
    payload: dict, mockup: dict, map_paths: tuple[str, ...] = (), extra_keys: tuple[str, ...] = ()
) -> list[str]:
    """How a served payload differs in shape from its mockup payload."""
    return problems(payload, describe(mockup, "$", map_paths), "$", extra_keys)


def response_problems(response: dict, schema: dict, document: dict) -> list[str]:
    """The served response's problems against its operation's 200 schema."""
    return schema_check.errors(response, schema, document)


# ---------- cases ----------
def load_mockup(path: str) -> dict:
    """An approved mockup's data.json (path from the root of the repository the code lives in)."""
    from marketbrief.warehouse.openapi_spec import CODE_ROOT

    return json.loads((CODE_ROOT / path).read_text(encoding="utf-8"))


def case_problems(case, builder, rows: dict[str, dict], document: dict, now: datetime) -> list[str]:
    """Every problem of one contract case over the stored rows of one market (page_key -> row): each served response
    against the operation's 200 schema, each served payload against its mockup page's shape."""
    from marketbrief.warehouse.openapi_spec import response_schema

    schema = response_schema(case.path, "get", document)
    mockup = load_mockup(case.mockup)
    out = []
    keys = [key for key in sorted(rows) if case.page_keys is None or case.page_keys(key)]
    if not keys:
        return [f"{case.path}: no stored page of rm.{case.table}"]
    for page_key in keys:
        row = rows[page_key]
        response = serve(row, builder.serve, now)
        label = f"{case.path} [{row['market']}/{page_key}]"
        out += [f"{label} schema {p}" for p in response_problems(response, schema, document)]
        expected = case.mockup_payload(mockup, row["market"], page_key)
        out += [
            f"{label} shape {p}" for p in shape_problems(response["payload"], expected, case.map_paths, case.extra_keys)
        ]
    return out


def stored_rows(warehouse, table: str, market: str) -> dict[str, dict]:
    """page_key -> the stored row (column -> value) of one rm table and market."""
    cursor = warehouse.execute(f"SELECT * FROM rm.{table} WHERE market = ? ORDER BY page_key", [market])
    names = [column[0] for column in cursor.description]
    return {row[names.index("page_key")]: dict(zip(names, row)) for row in cursor.fetchall()}


def check_market(warehouse, market: str, now: datetime) -> dict:
    """Every registered contract case over a market's stored rows: {checked, problems}."""
    from marketbrief.warehouse import openapi_spec, rm_registry

    document = openapi_spec.spec()
    builders = {builder.table: builder for builder in rm_registry.builders()}
    checked, found = [], []
    for case in rm_registry.contract_cases():
        rows = stored_rows(warehouse, case.table, market)
        found += case_problems(case, builders[case.table], rows, document, now)
        checked.append(case.path)
    return {"market": market, "checked": checked, "problems": found}
