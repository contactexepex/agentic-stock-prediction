"""The app API contract as one document (docs/ws/b4.md "Contract layout"). The contract is split so that each page
session edits only its own files:

  api/openapi.yaml         info, servers, security, tags, the shared parameters, headers, responses and schemas, and
                           the platform paths (markets, status, internal revalidate) and the 1.0 paths
  api/paths/<page>.yaml    a map of path -> path item: the page's operations
  api/schemas/<page>.yaml  a map of schema name -> schema: the page's payload and response schemas

`bundle()` merges them into one OpenAPI 3.1 document: every path of api/paths/*.yaml joins `paths` and every schema
of api/schemas/*.yaml joins `components.schemas`; a path or a schema name defined twice is an error. Every `$ref`
in every file is written against the bundled document (`#/components/schemas/Market`), so the bundle has local
refs only. Tools that need one file (code generators, B7) take `python -m marketbrief.warehouse.openapi_spec`."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import yaml

CODE_ROOT = Path(__file__).resolve().parents[3]  # the repository this code lives in (not core.paths.ROOT: data)
API_DIR = "api"
ROOT_FILE = "openapi.yaml"
PATHS_DIR = "paths"
SCHEMAS_DIR = "schemas"
MSG_DUPLICATE = "api contract: {kind} {name!r} is defined twice ({where})"
MSG_NOT_A_MAP = "api contract: {file} must be a mapping of {kind}"


class SpecError(ValueError):
    """The contract files do not merge into one document."""


def api_dir() -> Path:
    """The api/ folder of the repository the code lives in (the contract is code, so a test's data root never
    moves it; bundle(folder) takes another folder)."""
    return CODE_ROOT / API_DIR


def load_yaml(path: Path) -> dict:
    """One contract file as a mapping."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SpecError(MSG_NOT_A_MAP.format(file=path.name, kind="names"))
    return data


def merge(target: dict, extra: dict, kind: str, where: str) -> None:
    """Add `extra`'s entries to `target`; a name already present is an error."""
    for name, value in extra.items():
        if name in target:
            raise SpecError(MSG_DUPLICATE.format(kind=kind, name=name, where=where))
        target[name] = value


def bundle(folder: Path | None = None) -> dict:
    """The whole contract as one document with local refs only."""
    folder = folder or api_dir()
    document = load_yaml(folder / ROOT_FILE)
    document.setdefault("paths", {})
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    for path in sorted((folder / PATHS_DIR).glob("*.yaml")):
        merge(document["paths"], load_yaml(path), "path", f"{PATHS_DIR}/{path.name}")
    for path in sorted((folder / SCHEMAS_DIR).glob("*.yaml")):
        merge(schemas, load_yaml(path), "schema", f"{SCHEMAS_DIR}/{path.name}")
    return document


@lru_cache(maxsize=4)
def _cached(folder: str) -> str:
    return json.dumps(bundle(Path(folder)))


def spec() -> dict:
    """The bundled contract of the current root (cached per folder; a fresh copy each call)."""
    return json.loads(_cached(str(api_dir())))


def version(document: dict | None = None) -> str:
    """info.version of the contract: the schema_version of every read-model row."""
    return str((document or spec())["info"]["version"])


def resolve(document: dict, ref: str):
    """The node a local `#/...` ref points to (KeyError when it does not resolve)."""
    if not ref.startswith("#/"):
        raise SpecError(f"api contract: only local refs are allowed: {ref}")
    node = document
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def component(name: str, document: dict | None = None) -> dict:
    """components.schemas.<name>."""
    return (document or spec())["components"]["schemas"][name]


def response_schema(path: str, method: str = "get", document: dict | None = None) -> dict:
    """The application/json schema of an operation's 200 response."""
    document = document or spec()
    operation = document["paths"][path][method]
    return operation["responses"]["200"]["content"]["application/json"]["schema"]


def main() -> int:
    """Print the bundled contract as JSON (for code generators)."""
    json.dump(bundle(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
