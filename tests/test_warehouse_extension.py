"""The MotherDuck extension installer (scripts/marketbrief/warehouse/extension.py), offline: only HTTPS URLs on
the two official hosts are requested, the pinned versions agree with requirements.txt and the installed DuckDB,
a missing loader is downloaded and INSTALLed from a local file, a missing implementation is written where the
loader looks for it, files already present are not downloaded again, the implementation version is pinned
in the environment before LOAD, and download failures are clear errors. A fake connection and a fake
downloader stand in for DuckDB's extension loading and the network; the live check is in docs/ws/ws1.md."""

from __future__ import annotations

import gzip
import re
import sys
import urllib.error
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import extension  # noqa: E402
from marketbrief.warehouse.connection import load_warehouse_config  # noqa: E402
from marketbrief.warehouse.errors import WarehouseError  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PLATFORM = "linux_amd64"
PIN = extension.ExtensionPin("v" + duckdb.__version__, "v" + duckdb.__version__ + "-2026-10-3")
WAREHOUSE_CFG = {
    "extension": {"duckdb_version": PIN.duckdb_version, "implementation_version": PIN.implementation_version}
}


class FakeConnection:
    """Answers the platform and extension_directory queries; records every other statement."""

    def __init__(self, extension_directory: Path):
        self.extension_directory, self.statements, self.result = extension_directory, [], None

    def execute(self, sql: str, *_args):
        if "pragma_platform" in sql:
            self.result = (PLATFORM,)
        elif "extension_directory" in sql:
            self.result = (str(self.extension_directory),)
        else:
            self.statements.append(sql)
            if sql.startswith("INSTALL '"):
                installed = Path(re.match(r"INSTALL '(.+)'", sql).group(1))
                self.installed_bytes = installed.read_bytes()
        return self

    def fetchone(self):
        return self.result


class FakeDownloader:
    """Returns gzip-compressed bytes named after the URL; records the URLs asked for."""

    def __init__(self):
        self.urls = []

    def download(self, url: str) -> bytes:
        self.urls.append(url)
        return gzip.compress(f"signed file from {url}".encode())


def folder(base: Path) -> Path:
    return base / PIN.duckdb_version / PLATFORM


def test_pinned_versions_match_requirements_and_duckdb():
    pinned = load_warehouse_config()["extension"]
    requirement = re.search(r"^duckdb==([0-9.]+)", (REPO / "requirements.txt").read_text(), re.M)
    assert requirement, "requirements.txt pins duckdb exactly"
    assert pinned["duckdb_version"] == "v" + requirement.group(1) == "v" + duckdb.__version__
    assert pinned["implementation_version"].startswith(pinned["duckdb_version"] + "-")
    assert extension.extension_pin(load_warehouse_config()) == extension.ExtensionPin(**pinned)


def test_a_duckdb_other_than_the_pin_is_a_clear_error():
    other = {"extension": {"duckdb_version": "v0.0.1", "implementation_version": "v0.0.1-2020-01-1"}}
    with pytest.raises(WarehouseError, match="DuckDB is v.* pins the MotherDuck extension for v0.0.1"):
        extension.extension_pin(other)


def test_urls_are_https_on_the_official_hosts():
    loader, implementation = PIN.urls(PLATFORM)
    assert loader == f"https://extensions.duckdb.org/{PIN.duckdb_version}/{PLATFORM}/motherduck.duckdb_extension.gz"
    assert implementation == (
        f"https://ext.motherduck.com/{PIN.duckdb_version}/{PLATFORM}/"
        f"motherduck_impl.{PIN.implementation_version}.duckdb_extension.gz"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://extensions.duckdb.org/v1.5.6/linux_amd64/motherduck.duckdb_extension.gz",
        "https://example.com/motherduck.duckdb_extension.gz",
        "https://extensions.duckdb.org.example.com/motherduck.duckdb_extension.gz",
        "ftp://ext.motherduck.com/x.gz",
    ],
)
def test_other_urls_are_refused_before_any_request(url, monkeypatch):
    downloader = extension.ExtensionDownloader()
    monkeypatch.setattr(downloader, "send", lambda *_a, **_k: pytest.fail("a request was made"))
    with pytest.raises(WarehouseError, match="refused extension URL"):
        downloader.download(url)


def test_download_failures_are_clear_errors(monkeypatch):
    downloader = extension.ExtensionDownloader()
    url = PIN.urls(PLATFORM)[0]
    not_found = urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    with pytest.raises(WarehouseError, match=r"downloading https://extensions.duckdb.org/.* failed: HTTP 404"):
        downloader.on_http_error(url, not_found)
    downloader.on_network_error(url, urllib.error.URLError("reset"), 1, False)  # retried, no error yet
    with pytest.raises(WarehouseError, match="failed: <urlopen error reset>"):
        downloader.on_network_error(url, urllib.error.URLError("reset"), 2, True)
    sent = {}
    monkeypatch.setattr(downloader, "send", lambda target, headers: sent.update(url=target, headers=headers) or b"")
    downloader.download(url)
    assert sent["url"] == url and sent["headers"]["User-Agent"].startswith("market-brief/")


def test_missing_files_are_downloaded_installed_and_pinned(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_EXT_VERSION", raising=False)
    con, downloader = FakeConnection(tmp_path), FakeDownloader()
    extension.load_motherduck(con, WAREHOUSE_CFG, downloader)
    loader_url, implementation_url = PIN.urls(PLATFORM)
    assert downloader.urls == [loader_url, implementation_url]
    assert con.statements[0].startswith("INSTALL '") and con.statements[-1] == "LOAD motherduck"
    assert con.installed_bytes == f"signed file from {loader_url}".encode()  # the decompressed download
    implementation = folder(tmp_path) / f"motherduck_impl.{PIN.implementation_version}.duckdb_extension"
    assert implementation.read_bytes() == f"signed file from {implementation_url}".encode()
    assert not list(folder(tmp_path).glob("*.part-*"))  # written atomically, no partial file left
    assert extension.os.environ["MOTHERDUCK_EXT_VERSION"] == PIN.implementation_version


def test_files_already_present_are_not_downloaded_again(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_EXT_VERSION", raising=False)
    folder(tmp_path).mkdir(parents=True)
    (folder(tmp_path) / "motherduck.duckdb_extension").write_bytes(b"loader")
    (folder(tmp_path) / f"motherduck_impl.{PIN.implementation_version}.duckdb_extension").write_bytes(b"impl")
    con, downloader = FakeConnection(tmp_path), FakeDownloader()
    extension.load_motherduck(con, WAREHOUSE_CFG, downloader)
    assert downloader.urls == [] and con.statements == ["LOAD motherduck"]
    assert extension.os.environ["MOTHERDUCK_EXT_VERSION"] == PIN.implementation_version


def test_default_extension_directory_when_the_setting_is_empty():
    con = FakeConnection(Path(""))
    con.extension_directory = ""
    assert extension.extension_folder(con, PIN, PLATFORM) == (
        Path.home() / ".duckdb" / "extensions" / PIN.duckdb_version / PLATFORM
    )
