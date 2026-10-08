"""Offline checks of the app API contract (api/openapi.yaml with api/paths/*.yaml and api/schemas/*.yaml, bundled by
marketbrief/warehouse/openapi_spec.py; docs/ARCHITECTURE.md, docs/ws/b4.md): paths under /api/v1, every $ref
resolves, every operation has an operationId and a 200 response schema, planned operations carry x-status, read
operations name a read-model table that a registered builder writes, writes take an Idempotency-Key, and the code an
`x-source` names exists."""
from __future__ import annotations

import re
from pathlib import Path

import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import openapi_spec, rm_registry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "scripts" / "marketbrief"
PREFIX = "/api/v1/"
METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")
WRITE_METHODS = ("put", "post", "delete", "patch")
PLANNED = "planned"
SOURCE_CALL = re.compile(r"\b([a-z_]+(?:/[a-z_]+)*)\.([a-z_]+)\b")


@pytest.fixture(scope="module")
def spec() -> dict:
    return openapi_spec.bundle()


def operations(spec: dict):
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method in item:
                yield path, method, item[method]


def walk(node, trail=()):
    """Every (trail, dict) in the document."""
    if isinstance(node, dict):
        yield trail, node
        for key, value in node.items():
            yield from walk(value, (*trail, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, (*trail, index))


def resolve(spec: dict, ref: str):
    assert ref.startswith("#/"), f"only local refs are allowed: {ref}"
    node = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        assert isinstance(node, dict) and part in node, f"unresolved $ref {ref}"
        node = node[part]
    return node


def deref(spec: dict, node: dict) -> dict:
    while "$ref" in node:
        node = resolve(spec, node["$ref"])
    return node


def test_is_openapi_3_1(spec):
    assert str(spec["openapi"]).startswith("3.1.")
    assert re.fullmatch(r"\d+\.\d+\.\d+", spec["info"]["version"])


def test_every_path_is_under_api_v1(spec):
    assert spec["paths"], "no paths"
    bad = [p for p in spec["paths"] if not p.startswith(PREFIX)]
    assert not bad, bad


def test_every_ref_resolves(spec):
    refs = [(trail, node["$ref"]) for trail, node in walk(spec) if isinstance(node.get("$ref"), str)]
    assert refs
    for _trail, ref in refs:
        resolve(spec, ref)


def test_every_operation_has_an_operation_id_and_a_200_schema(spec):
    ids = []
    for path, method, op in operations(spec):
        assert op.get("operationId"), f"{method} {path}: no operationId"
        ids.append(op["operationId"])
        ok = deref(spec, op.get("responses", {}).get("200") or {})
        content = ok.get("content") or {}
        assert content, f"{method} {path}: no 200 response content"
        for media in content.values():
            assert media.get("schema"), f"{method} {path}: 200 without a schema"
            deref(spec, media["schema"])
    assert len(ids) == len(set(ids)), "duplicate operationId"


def test_planned_operations_carry_x_status(spec):
    for path, method, op in operations(spec):
        responses = op.get("responses", {})
        if "x-status" in op:
            assert op["x-status"] == PLANNED, f"{method} {path}: unknown x-status {op['x-status']}"
        if "501" in responses:
            assert op.get("x-status") == PLANNED, f"{method} {path}: answers 501 but is not marked planned"
        if op.get("x-status") == PLANNED:
            assert "501" in responses, f"{method} {path}: planned but no 501 response"


def test_operations_returning_planned_schemas_are_planned(spec):
    for path, method, op in operations(spec):
        ok = op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {})
        if deref(spec, ok.get("schema") or {}).get("x-status") == PLANNED:
            assert op.get("x-status") == PLANNED, f"{method} {path}: returns a planned schema but is not planned"


def test_writes_take_an_idempotency_key(spec):
    for path, method, op in operations(spec):
        if method not in WRITE_METHODS or "/internal/" in path:
            continue
        names = [deref(spec, p).get("name") for p in op.get("parameters", [])]
        assert "Idempotency-Key" in names, f"{method} {path}: no Idempotency-Key header"


def test_reads_name_their_read_model_and_return_the_envelope(spec):
    meta = "#/components/schemas/ReadModelMeta"
    built = set(rm_registry.tables())
    for path, method, op in operations(spec):
        if method != "get" or path.startswith(PREFIX + "inbox/"):
            continue
        table = op.get("x-read-model", "")
        assert re.fullmatch(r"rm\.[a-z_]+", table), f"{method} {path}: x-read-model {table!r}"
        if op.get("x-status") != PLANNED:
            assert table.removeprefix("rm.") in built, f"{method} {path}: no registered builder writes {table}"
        schema = deref(spec, op["responses"]["200"]["content"]["application/json"]["schema"])
        parts = schema.get("allOf") or []
        assert any(p.get("$ref") == meta for p in parts), f"{method} {path}: 200 is not ReadModelMeta + payload"
        assert any("payload" in (p.get("properties") or {}) for p in parts), f"{method} {path}: no payload"
    pattern = spec["components"]["schemas"]["RevalidateRequest"]["properties"]["keys"]["items"]["properties"]
    assert all(re.fullmatch(pattern["table"]["pattern"], table) for table in built)


def test_every_builder_schema_is_in_the_contract(spec):
    schemas = spec["components"]["schemas"]
    for builder in rm_registry.builders():
        assert builder.schema in schemas, f"rm.{builder.table}: schema {builder.schema} not in the contract"


def test_every_contract_case_names_an_operation_of_its_table(spec):
    cases = rm_registry.contract_cases()
    assert cases
    for case in cases:
        op = spec["paths"][case.path]["get"]
        assert op["x-read-model"] == f"rm.{case.table}", case.path
        assert (REPO / case.mockup).is_file(), case.mockup


def write(folder: Path, name: str, data: dict) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def test_bundle_merges_page_files_and_refuses_a_name_defined_twice(tmp_path):
    write(tmp_path, "openapi.yaml", {"openapi": "3.1.0", "info": {"version": "1.1.0"}, "paths": {"/api/v1/a": {}},
                                     "components": {"schemas": {"Market": {"type": "string"}}}})
    write(tmp_path, "paths/page.yaml", {"/api/v1/b": {"get": {}}})
    write(tmp_path, "schemas/page.yaml", {"PagePayload": {"$ref": "#/components/schemas/Market"}})
    bundled = openapi_spec.bundle(tmp_path)
    assert set(bundled["paths"]) == {"/api/v1/a", "/api/v1/b"}
    assert set(bundled["components"]["schemas"]) == {"Market", "PagePayload"}
    write(tmp_path, "schemas/other.yaml", {"Market": {"type": "integer"}})
    with pytest.raises(openapi_spec.SpecError, match="schema 'Market' is defined twice"):
        openapi_spec.bundle(tmp_path)
    (tmp_path / "schemas/other.yaml").unlink()
    write(tmp_path, "paths/other.yaml", {"/api/v1/b": {"post": {}}})
    with pytest.raises(openapi_spec.SpecError, match="path '/api/v1/b' is defined twice"):
        openapi_spec.bundle(tmp_path)


def test_x_source_functions_exist(spec):
    """An x-source like `presentation/dashboard/track.call_block` names a module and a function that exist."""
    checked = 0
    for _trail, node in walk(spec):
        source = node.get("x-source")
        if not isinstance(source, str):
            continue
        for module, name in SOURCE_CALL.findall(source):
            path = PACKAGE / f"{module}.py"
            if "/" not in module:  # a table or view name such as rm.status, not a module path
                continue
            assert path.is_file(), f"x-source module {module} not found"
            text = path.read_text(encoding="utf-8")
            assert re.search(rf"^(def|class) {name}\b|^{name}\s*(:[^=\n]*)?=", text, re.M), f"{module}.{name} not found"
            checked += 1
    assert checked >= 20, f"only {checked} x-source references checked"
