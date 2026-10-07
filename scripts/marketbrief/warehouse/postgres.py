"""MotherDuck's Postgres endpoint: the connection parameters and URL the app's route handlers use (wave 2).
The password is the MotherDuck token, URL-encoded in the URL. repr() and str() never show it; only `url()`
and `params()` return it, for handing straight to a client."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from marketbrief.constants.environment import ENV_MOTHERDUCK_TOKEN
from marketbrief.constants.warehouse import MSG_TOKEN_MISSING, REDACTED
from marketbrief.warehouse.connection import WarehouseError, load_warehouse_config, token


@dataclass(frozen=True)
class PostgresEndpoint:
    """Host, port, user, database and TLS settings of the endpoint, plus the token (hidden)."""

    host: str
    port: int
    user: str
    dbname: str
    sslmode: str
    sslrootcert: str
    password: str = field(repr=False)

    def url(self) -> str:
        """postgresql://user:<token, URL-encoded>@host:port/dbname?sslmode=..&sslrootcert=.."""
        query = urllib.parse.urlencode({"sslmode": self.sslmode, "sslrootcert": self.sslrootcert})
        user = urllib.parse.quote(self.user, safe="")
        secret = urllib.parse.quote(self.password, safe="")
        return f"postgresql://{user}:{secret}@{self.host}:{self.port}/{self.dbname}?{query}"

    def params(self) -> dict:
        """The libpq keyword parameters (psql, psycopg), password included."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "dbname": self.dbname,
            "sslmode": self.sslmode,
            "sslrootcert": self.sslrootcert,
            "password": self.password,
        }

    def redacted_url(self) -> str:
        """The URL with the password shown as ***."""
        return self.url().replace(urllib.parse.quote(self.password, safe=""), REDACTED)

    def __repr__(self) -> str:
        """The endpoint without its password."""
        return f"PostgresEndpoint({self.redacted_url()})"

    __str__ = __repr__


def endpoint(cfg: dict | None = None) -> PostgresEndpoint:
    """The endpoint of config/warehouse.yaml with the token from MOTHERDUCK_TOKEN (an error naming the
    variable when it is unset; the value is never echoed)."""
    cfg = cfg or load_warehouse_config()
    secret = token()
    if not secret:
        raise WarehouseError(MSG_TOKEN_MISSING.format(env=ENV_MOTHERDUCK_TOKEN))
    return PostgresEndpoint(
        host=cfg["pg_host"],
        port=int(cfg["pg_port"]),
        user=cfg["pg_user"],
        dbname=cfg["name"],
        sslmode=cfg["sslmode"],
        sslrootcert=cfg["sslrootcert"],
        password=secret,
    )
