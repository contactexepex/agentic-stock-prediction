"""Where the warehouse lives and how to connect to it.

Target: `md:<name>` (MotherDuck) when the provider is motherduck and MOTHERDUCK_TOKEN is set, else the local
DuckDB file of config/warehouse.yaml (dev and tests). The token is read from the environment only (or passed in
by a caller with another account, e.g. the inbox import) and handed to DuckDB as a bound `SET motherduck_token = ?`
parameter, so the value is never put into SQL text, a connection string or a config, and every error raised from
here has it redacted. The MotherDuck extension is installed over HTTPS only, with DuckDB checking its signatures
(marketbrief/warehouse/extension.py); unsigned extensions stay disallowed."""

from __future__ import annotations

import re
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
)
from marketbrief.core import paths
from marketbrief.warehouse.errors import WarehouseError, token
from marketbrief.warehouse.extension import load_motherduck

NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def connect_motherduck(name: str, read_only: bool, token_value: str | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with the MotherDuck database `name` attached and in use, signed in with `token_value`
    (another account's token, e.g. the inbox's) or else MOTHERDUCK_TOKEN. The extension is installed over HTTPS
    (extension.py); the token is set as a bound parameter, so it never enters SQL text, and it takes precedence over
    any MOTHERDUCK_TOKEN in the environment."""
    secret = token_value or token()
    if not secret:
        raise WarehouseError(MSG_TOKEN_MISSING.format(env=ENV_MOTHERDUCK_TOKEN))
    try:
        con = duckdb.connect()
        load_motherduck(con, load_warehouse_config())
        con.execute("SET motherduck_token = ?", [secret])
        if read_only:
            con.execute(f"ATTACH '{MOTHERDUCK_PREFIX}{name}' AS {name} (READ_ONLY)")
        else:
            con.execute(f"ATTACH '{MOTHERDUCK_PREFIX}'")
            con.execute(f"CREATE DATABASE IF NOT EXISTS {name}")
        con.execute(f"USE {name}")
        return con
    except duckdb.Error as exc:
        raise WarehouseError(f"{type(exc).__name__}: {exc}", other_secrets=(secret,)) from None


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
