"""The warehouse connection (scripts/marketbrief/warehouse/connection.py, postgres.py): target selection,
the missing-token error, the Postgres URL's encoding and the redaction of the token everywhere it could
show (repr, str, exception messages). Offline: no MotherDuck connection is made."""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.warehouse import connection, errors, postgres  # noqa: E402
from marketbrief.warehouse.connection import WarehouseError  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SECRET = "tok/en+with=odd@chars:and%signs?&#"  # every character URL encoding must change
CFG = {
    "provider": "motherduck",
    "name": "market_brief",
    "pg_host": "pg.example.invalid",
    "pg_port": 5432,
    "pg_user": "postgres",
    "sslmode": "verify-full",
    "sslrootcert": "system",
    "local_path": "work/warehouse/market_brief.duckdb",
}


def forms(secret: str) -> list[str]:
    return [secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)]


def test_repo_config_has_no_secret_and_loads():
    cfg = connection.load_warehouse_config()
    assert cfg["provider"] == "motherduck" and cfg["name"] == "market_brief"
    assert cfg["pg_host"] == "pg.eu-central-1-aws.motherduck.com" and cfg["pg_port"] == 5432
    assert cfg["sslmode"] == "verify-full" and cfg["sslrootcert"] == "system"
    assert cfg["local_path"].startswith("work/")
    assert not [k for k in cfg if "token" in k or "password" in k]


def test_target_is_motherduck_only_with_the_token(monkeypatch):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", SECRET)
    assert connection.select_target(CFG) == connection.Target("motherduck", "market_brief")
    assert connection.select_target(CFG).label() == "md:market_brief"
    local = connection.select_target(CFG, force_local=True)
    assert local.kind == "local" and local.path == common.ROOT / CFG["local_path"]
    assert connection.select_target({**CFG, "provider": "local"}).kind == "local"
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "   ")  # blank counts as unset
    assert connection.select_target(CFG).kind == "local"
    monkeypatch.delenv("MOTHERDUCK_TOKEN")
    assert connection.select_target(CFG).kind == "local"


def test_missing_token_error_names_the_variable(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    for call in (
        lambda: connection.select_target(CFG, require_token=True),
        lambda: postgres.endpoint(CFG),
        lambda: connection.connect_motherduck("market_brief", read_only=True),
    ):
        with pytest.raises(WarehouseError, match="MOTHERDUCK_TOKEN") as err:
            call()
        assert "--local" in str(err.value)
    # with --local the token is not needed
    assert connection.select_target(CFG, force_local=True, require_token=True).kind == "local"


def test_bad_provider_or_name_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "CONFIG", tmp_path)
    (tmp_path / "warehouse.yaml").write_text("provider: snowflake\nname: market_brief\n")
    with pytest.raises(WarehouseError, match="provider"):
        connection.load_warehouse_config()
    (tmp_path / "warehouse.yaml").write_text("provider: local\nname: 'x; DROP'\n")
    with pytest.raises(WarehouseError, match="name"):
        connection.load_warehouse_config()


def test_postgres_url_encodes_the_token(monkeypatch):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", SECRET)
    pg_endpoint = postgres.endpoint(CFG)
    url = pg_endpoint.url()
    assert url == (
        f"postgresql://postgres:{urllib.parse.quote(SECRET, safe='')}@pg.example.invalid:5432/market_brief"
        "?sslmode=verify-full&sslrootcert=system"
    )
    parsed = urllib.parse.urlsplit(url)
    assert urllib.parse.unquote(parsed.password) == SECRET
    assert parsed.hostname == "pg.example.invalid" and parsed.port == 5432 and parsed.path == "/market_brief"
    assert pg_endpoint.params()["password"] == SECRET and pg_endpoint.params()["dbname"] == "market_brief"


def test_repr_str_and_errors_never_show_the_token(monkeypatch):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", SECRET)
    pg_endpoint = postgres.endpoint(CFG)
    shown = [
        repr(pg_endpoint),
        str(pg_endpoint),
        f"{pg_endpoint}",
        pg_endpoint.redacted_url(),
        repr([pg_endpoint]),
        str({"endpoint": pg_endpoint}),
    ]
    for text in shown:
        assert "***" in text
        for form in forms(SECRET):
            assert form not in text, text
    err = WarehouseError(f"failed with {SECRET} and {urllib.parse.quote(SECRET, safe='')}")
    for text in (str(err), repr(err), str(err.args)):
        for form in forms(SECRET):
            assert form not in text
    assert errors.redact(f"x {SECRET} y") == "x *** y"


def test_driver_errors_are_redacted(monkeypatch, tmp_path):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", SECRET)

    def failing_connect(*_args, **_kwargs):
        raise duckdb.IOException(f"cannot open md:market_brief?motherduck_token={SECRET}")

    monkeypatch.setattr(connection.duckdb, "connect", failing_connect)
    for call in (
        lambda: connection.connect_motherduck("market_brief", read_only=False),
        lambda: connection.connect_local(tmp_path / "w.duckdb", read_only=False),
    ):
        with pytest.raises(WarehouseError) as err:
            call()
        assert SECRET not in str(err.value) and "***" in str(err.value)
        assert err.value.__cause__ is None and err.value.__suppress_context__


def test_extension_rules_in_the_source():
    """The MotherDuck extension is installed by marketbrief/warehouse/extension.py only (HTTPS downloads, a
    local-file INSTALL that DuckDB signature-checks): no `INSTALL motherduck` from DuckDB's plain-HTTP default
    repository, no plain http:// URL, never allow_unsigned_extensions, and the token never goes into SQL or a
    connection string."""
    package = REPO / "scripts" / "marketbrief" / "warehouse"
    text = "\n".join(module.read_text() for module in package.glob("*.py"))
    constants = (REPO / "scripts" / "marketbrief" / "constants" / "warehouse.py").read_text()
    assert "allow_unsigned_extensions" not in text
    assert 'execute("INSTALL motherduck' not in text
    assert "http://" not in text + constants
    assert "load_motherduck(con, load_warehouse_config())" in (package / "connection.py").read_text()
    assert "motherduck_token" not in text  # no config option or SET carrying the value


def test_local_read_only_connection_refuses_writes(tmp_path):
    target = connection.Target("local", "market_brief", tmp_path / "w" / "wh.duckdb")
    con = connection.connect_warehouse(read_only=False, target=target)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.close()
    read_only_con = connection.connect_warehouse(read_only=True, target=target)
    with pytest.raises(duckdb.Error):
        read_only_con.execute("CREATE TABLE u (a INTEGER)")
    read_only_con.close()
