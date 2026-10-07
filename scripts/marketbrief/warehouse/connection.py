"""Where the warehouse lives and how to connect to it.

Target: `md:<name>` (MotherDuck) when the provider is motherduck and MOTHERDUCK_TOKEN is set, else the local
DuckDB file of config/warehouse.yaml (dev and tests). The token is read from the environment only: the
MotherDuck extension reads MOTHERDUCK_TOKEN itself, so the value is never put into SQL, a connection string or
a config, and every error raised from here has it redacted. The MotherDuck extension is installed with
DuckDB's own `INSTALL motherduck` from the official signed repository; unsigned extensions stay disallowed."""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import yaml

from marketbrief.constants.environment import ENV_MOTHERDUCK_TOKEN
from marketbrief.constants.warehouse import (
    FILE_WAREHOUSE_CONFIG,
    MOTHERDUCK_PREFIX,
    MSG_BAD_NAME,
    MSG_BAD_PROVIDER,
    MSG_TOKEN_MISSING,
    PROVIDER_LOCAL,
    PROVIDER_MOTHERDUCK,
    REDACTED,
)
from marketbrief.core import paths

NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class WarehouseError(RuntimeError):
    """A warehouse failure whose message never carries the token."""

    def __init__(self, message: str):
        """Keep only the redacted message."""
        super().__init__(redact(message))


def token() -> str | None:
    """The MotherDuck token from the environment, None when unset or blank."""
    value = os.environ.get(ENV_MOTHERDUCK_TOKEN, "").strip()
    return value or None


def redact(text) -> str:
    """The text with the token (as is and URL-encoded) replaced by ***."""
    out, secret = str(text), token()
    if secret:
        for form in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
            out = out.replace(form, REDACTED)
    return out


def load_warehouse_config() -> dict:
    """config/warehouse.yaml, checked: a known provider and a plain database name."""
    cfg = yaml.safe_load((paths.CONFIG / FILE_WAREHOUSE_CONFIG).read_text()) or {}
    if cfg.get("provider") not in (PROVIDER_MOTHERDUCK, PROVIDER_LOCAL):
        raise WarehouseError(MSG_BAD_PROVIDER.format(provider=cfg.get("provider")))
    if not NAME_PATTERN.fullmatch(str(cfg.get("name", ""))):
        raise WarehouseError(MSG_BAD_NAME.format(name=cfg.get("name")))
    return cfg


@dataclass(frozen=True)
class Target:
    """The chosen warehouse: kind motherduck (database `name`) or local (DuckDB file `path`)."""

    kind: str
    name: str
    path: Path | None = None

    def label(self) -> str:
        """`md:<name>` or the local file path relative to the repo when inside it."""
        if self.kind == PROVIDER_MOTHERDUCK:
            return MOTHERDUCK_PREFIX + self.name
        try:
            return self.path.resolve().relative_to(paths.ROOT.resolve()).as_posix()
        except ValueError:
            return str(self.path)


def select_target(cfg: dict | None = None, force_local: bool = False, require_token: bool = False) -> Target:
    """MotherDuck when the provider is motherduck and the token is set (and --local was not given), else the
    local file. With `require_token`, a motherduck provider without the token is an error naming the env var."""
    cfg = cfg or load_warehouse_config()
    if cfg["provider"] == PROVIDER_MOTHERDUCK and not force_local:
        if token():
            return Target(PROVIDER_MOTHERDUCK, cfg["name"])
        if require_token:
            raise WarehouseError(MSG_TOKEN_MISSING.format(env=ENV_MOTHERDUCK_TOKEN))
    return Target(PROVIDER_LOCAL, cfg["name"], paths.ROOT / cfg["local_path"])


def connect_motherduck(name: str, read_only: bool) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with the MotherDuck database attached as `name` and in use."""
    if not token():
        raise WarehouseError(MSG_TOKEN_MISSING.format(env=ENV_MOTHERDUCK_TOKEN))
    try:
        con = duckdb.connect()  # the extension reads MOTHERDUCK_TOKEN from the environment itself
        con.execute("INSTALL motherduck")  # DuckDB's official, signed extension repository
        con.execute("LOAD motherduck")
        if read_only:
            con.execute(f"ATTACH '{MOTHERDUCK_PREFIX}{name}' AS {name} (READ_ONLY)")
        else:
            con.execute(f"ATTACH '{MOTHERDUCK_PREFIX}'")
            con.execute(f"CREATE DATABASE IF NOT EXISTS {name}")
        con.execute(f"USE {name}")
        return con
    except duckdb.Error as exc:
        raise WarehouseError(f"{type(exc).__name__}: {exc}") from None


def connect_local(path: Path, read_only: bool) -> duckdb.DuckDBPyConnection:
    """The local DuckDB file (created, with its folder, when writing)."""
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return duckdb.connect(str(path), read_only=read_only)
    except duckdb.Error as exc:
        raise WarehouseError(f"{type(exc).__name__}: {exc}") from None


def connect_warehouse(
    read_only: bool = True, force_local: bool = False, target: Target | None = None
) -> duckdb.DuckDBPyConnection:
    """A connection to the warehouse target (MotherDuck or the local file), read-only unless asked."""
    target = target or select_target(force_local=force_local)
    if target.kind == PROVIDER_MOTHERDUCK:
        return connect_motherduck(target.name, read_only)
    return connect_local(target.path, read_only)
