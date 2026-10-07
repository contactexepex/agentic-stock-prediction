"""Installing the MotherDuck extension over HTTPS only, through the environment's proxy.

The `motherduck` extension on extensions.duckdb.org is a loader: on LOAD it downloads its implementation
(`motherduck_impl.<version>.duckdb_extension`) from ext.motherduck.com over plain HTTP with its own client, which
ignores HTTPS_PROXY. DuckDB's own `INSTALL motherduck` first fetches httpfs over plain HTTP too. Both fail where
only an HTTPS proxy may reach the internet, and both break the HTTPS-only rule. So this module downloads the two
signed files itself, over HTTPS with the repo's HttpClient (HTTPS_PROXY and the CA bundle from the environment),
installs the loader with `INSTALL '<local file>'`, puts the implementation where the loader looks for it, and
names the implementation version in MOTHERDUCK_EXT_VERSION, so the loader uses that file and downloads nothing.
DuckDB verifies both files' signatures when they load; unsigned extensions stay disallowed. The versions are
pinned in config/warehouse.yaml. No token is sent with these downloads."""

from __future__ import annotations

import gzip
import os
import tempfile
import urllib.error
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import duckdb

from marketbrief.constants.warehouse import (
    ENV_IMPLEMENTATION_VERSION,
    EXTENSION_ATTEMPTS,
    EXTENSION_HOSTS,
    EXTENSION_TIMEOUT_SECONDS,
    EXTENSION_USER_AGENT,
    IMPLEMENTATION_FILE,
    IMPLEMENTATION_URL,
    LOADER_FILE,
    LOADER_URL,
    MSG_DUCKDB_VERSION_MISMATCH,
    MSG_EXTENSION_DOWNLOAD_FAILED,
    MSG_EXTENSION_URL_REFUSED,
)
from marketbrief.sources.http import HttpClient, HttpPolicy
from marketbrief.warehouse.errors import WarehouseError

DEFAULT_EXTENSION_DIRECTORY = Path.home() / ".duckdb" / "extensions"


@dataclass(frozen=True)
class ExtensionPin:
    """The pinned versions: DuckDB's (e.g. v1.5.6) and MotherDuck's implementation for it."""

    duckdb_version: str
    implementation_version: str

    def urls(self, platform: str) -> tuple[str, str]:
        """The HTTPS URLs of the loader and of the implementation for this platform."""
        names = {"duckdb_version": self.duckdb_version, "platform": platform}
        loader = LOADER_URL.format(**names)
        implementation = IMPLEMENTATION_URL.format(**names, implementation_version=self.implementation_version)
        return loader, implementation


class ExtensionDownloader(HttpClient):
    """Fetches the extension files: HTTPS on the two official hosts only, a generic User-Agent."""

    def __init__(self):
        """One retry on a network error; no retry on an HTTP error."""
        super().__init__(
            HttpPolicy(
                timeout=EXTENSION_TIMEOUT_SECONDS,
                attempts=EXTENSION_ATTEMPTS,
                network_errors=(urllib.error.URLError, TimeoutError),
            )
        )

    def download(self, url: str) -> bytes:
        """The response body of an allowed URL; any other URL is refused before a request is made."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in EXTENSION_HOSTS:
            raise WarehouseError(MSG_EXTENSION_URL_REFUSED.format(url=url))
        return self.send(url, headers={"User-Agent": EXTENSION_USER_AGENT})

    def on_http_error(self, url: str, exc: urllib.error.HTTPError):
        """An HTTP error status ends the install with the URL and the status."""
        raise WarehouseError(MSG_EXTENSION_DOWNLOAD_FAILED.format(url=url, reason=f"HTTP {exc.code}"))

    def on_network_error(self, url: str, exc: BaseException, _attempt: int, is_last: bool) -> None:
        """A network error is retried once, then ends the install."""
        if is_last:
            raise WarehouseError(MSG_EXTENSION_DOWNLOAD_FAILED.format(url=url, reason=exc))


def extension_pin(warehouse_cfg: dict) -> ExtensionPin:
    """The pinned versions of config/warehouse.yaml; an error when the installed DuckDB is another version."""
    pinned = warehouse_cfg["extension"]
    pin = ExtensionPin(pinned["duckdb_version"], pinned["implementation_version"])
    installed = "v" + duckdb.__version__
    if installed != pin.duckdb_version:
        raise WarehouseError(MSG_DUCKDB_VERSION_MISMATCH.format(installed=installed, pinned=pin.duckdb_version))
    return pin


def extension_platform(con: duckdb.DuckDBPyConnection) -> str:
    """The extension platform of this DuckDB, e.g. linux_amd64."""
    return con.execute("SELECT platform FROM pragma_platform()").fetchone()[0]


def extension_folder(con: duckdb.DuckDBPyConnection, pin: ExtensionPin, platform: str) -> Path:
    """Where DuckDB keeps this version's extensions: <extension_directory>/<duckdb version>/<platform>."""
    setting = con.execute("SELECT current_setting('extension_directory')").fetchone()[0]
    base = Path(setting).expanduser() if setting else DEFAULT_EXTENSION_DIRECTORY
    return base / pin.duckdb_version / platform


def write_gunzipped(compressed: bytes, target: Path) -> None:
    """Decompress into `target` atomically: a temporary file in the same folder, then a rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.part-")
    with os.fdopen(handle, "wb") as extension_file:
        extension_file.write(gzip.decompress(compressed))
    os.replace(temporary, target)


def install_loader(con: duckdb.DuckDBPyConnection, url: str, downloader: ExtensionDownloader) -> None:
    """Download the signed loader into a fresh folder and INSTALL it from there (DuckDB checks the signature)."""
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / LOADER_FILE
        write_gunzipped(downloader.download(url), local)
        con.execute(f"INSTALL '{local.as_posix()}'")


def load_motherduck(
    con: duckdb.DuckDBPyConnection, warehouse_cfg: dict, downloader: ExtensionDownloader | None = None
) -> None:
    """Install what is missing (loader, implementation) over HTTPS, pin the implementation version, LOAD."""
    pin = extension_pin(warehouse_cfg)
    downloader = downloader or ExtensionDownloader()
    platform = extension_platform(con)
    loader_url, implementation_url = pin.urls(platform)
    folder = extension_folder(con, pin, platform)
    if not (folder / LOADER_FILE).is_file():
        install_loader(con, loader_url, downloader)
    implementation = folder / IMPLEMENTATION_FILE.format(implementation_version=pin.implementation_version)
    if not implementation.is_file():
        write_gunzipped(downloader.download(implementation_url), implementation)
    os.environ[ENV_IMPLEMENTATION_VERSION] = pin.implementation_version
    con.execute("LOAD motherduck")
