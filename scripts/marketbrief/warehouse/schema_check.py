"""Check a JSON value against a schema of the API contract (docs/ARCHITECTURE.md 4.1: the sync validates every
payload before writing it; the contract tests validate every served response). It implements the part of JSON
Schema 2020-12 the contract uses, with no new dependency: $ref (local), type (one or a list), enum, const,
properties, required, additionalProperties (false or a schema), items, prefixItems, minItems, maxItems, minimum,
maximum, exclusiveMinimum, minLength, maxLength, pattern, allOf, anyOf and oneOf. `format`, `description` and the
`x-` keys are annotations only. Returns the list of problems, each prefixed with its JSON path ($.a.b[0])."""

from __future__ import annotations

import re

from marketbrief.warehouse.openapi_spec import resolve

MAX_ERRORS = 20
TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: (
        isinstance(value, int) and not isinstance(value, bool) or isinstance(value, float) and value.is_integer()
    ),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def type_errors(value, schema: dict, where: str) -> list[str]:
    """`type`, `enum` and `const`."""
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(TYPE_CHECKS[name](value) for name in names):
            return [f"{where}: expected {'|'.join(names)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: {value!r} not in {schema['enum']}"]
    if "const" in schema and value != schema["const"]:
        return [f"{where}: {value!r} is not {schema['const']!r}"]
    return []


def bound_errors(value, schema: dict, where: str) -> list[str]:
    """Number and string bounds and the string pattern."""
    out = []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: {value} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append(f"{where}: {value} <= exclusiveMinimum {schema['exclusiveMinimum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where}: {value!r} does not match {schema['pattern']}")
    return out


def object_errors(value: dict, schema: dict, document: dict, where: str) -> list[str]:
    """`required`, `properties` and `additionalProperties`."""
    out = [f"{where}: missing {key!r}" for key in schema.get("required", []) if key not in value]
    properties = schema.get("properties") or {}
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in properties:
            out += errors(item, properties[key], document, f"{where}.{key}")
        elif extra is False:
            out.append(f"{where}: unexpected {key!r}")
        elif isinstance(extra, dict):
            out += errors(item, extra, document, f"{where}.{key}")
    return out


def array_errors(value: list, schema: dict, document: dict, where: str) -> list[str]:
    """`minItems`, `maxItems`, `prefixItems` and `items`."""
    out = []
    if "minItems" in schema and len(value) < schema["minItems"]:
        out.append(f"{where}: fewer than {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        out.append(f"{where}: more than {schema['maxItems']} items")
    prefix = schema.get("prefixItems") or []
    for index, item in enumerate(value):
        if index < len(prefix):
            out += errors(item, prefix[index], document, f"{where}[{index}]")
        elif isinstance(schema.get("items"), dict):
            out += errors(item, schema["items"], document, f"{where}[{index}]")
    return out


def combinator_errors(value, schema: dict, document: dict, where: str) -> list[str]:
    """`allOf` (every part), `anyOf` (at least one) and `oneOf` (exactly one)."""
    out = []
    for part in schema.get("allOf") or []:
        out += errors(value, part, document, where)
    if "anyOf" in schema and all(errors(value, part, document, where) for part in schema["anyOf"]):
        out.append(f"{where}: matches none of anyOf")
    if "oneOf" in schema:
        matches = sum(not errors(value, part, document, where) for part in schema["oneOf"])
        if matches != 1:
            out.append(f"{where}: matches {matches} of oneOf, not exactly 1")
    return out


def errors(value, schema: dict, document: dict, where: str = "$") -> list[str]:
    """Every problem of `value` against `schema` (refs resolved in the bundled `document`)."""
    while "$ref" in schema:
        schema = resolve(document, schema["$ref"])
    out = type_errors(value, schema, where)
    if out:
        return out
    out += bound_errors(value, schema, where)
    if isinstance(value, dict):
        out += object_errors(value, schema, document, where)
    if isinstance(value, list):
        out += array_errors(value, schema, document, where)
    out += combinator_errors(value, schema, document, where)
    return out[:MAX_ERRORS]
