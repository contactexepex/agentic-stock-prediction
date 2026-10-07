"""The dashboard page: one self-contained HTML file. The template, stylesheet and app script live in
assets/; the vendored TradingView Lightweight Charts build (vendor/, Apache-2.0, pinned in NOTICE) is
inlined, and the data is embedded as JSON. Nothing is fetched at view time."""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

from marketbrief.constants.dashboard import (
    APP_BOOT,
    ASSET_CSS,
    ASSET_DIR,
    ASSET_JS,
    ASSET_TEMPLATE,
    SLOT_APP,
    SLOT_CSS,
    SLOT_DATA,
    SLOT_LIB,
    SLOT_TITLE,
    VENDOR_DIR,
    VENDOR_JS,
    VENDOR_NOTICE,
)

HERE = Path(__file__).resolve().parent
NOTICE_SHA = re.compile(r"^SHA-256:\s*([0-9a-f]{64})\s*$", re.M)


def vendor_path() -> Path:
    """The vendored Lightweight Charts standalone build."""
    return HERE / VENDOR_DIR / VENDOR_JS


def pinned_sha256() -> str:
    """The SHA-256 recorded in vendor/NOTICE."""
    match = NOTICE_SHA.search((HERE / VENDOR_DIR / VENDOR_NOTICE).read_text())
    if not match:
        raise ValueError("vendor/NOTICE has no SHA-256 line")
    return match.group(1)


def vendor_script() -> str:
    """The vendored library, refused when its bytes differ from the pinned SHA-256."""
    data = vendor_path().read_bytes()
    if hashlib.sha256(data).hexdigest() != pinned_sha256():
        raise ValueError(f"{VENDOR_JS} does not match the SHA-256 pinned in vendor/NOTICE")
    return data.decode("utf-8")


def script_safe(text: str) -> str:
    """Text placed inside a <script> element: a closing tag can never end it early."""
    return text.replace("</", "<\\/")


def build_page(data: dict) -> str:
    """The HTML page with the stylesheet, the library, the app and the data inlined."""
    assets = HERE / ASSET_DIR
    app = "\n".join([*((assets / name).read_text() for name in ASSET_JS), APP_BOOT])
    payload = script_safe(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    title = f"{data['name']} dashboard"
    values = {
        SLOT_TITLE: html.escape(title),
        SLOT_CSS: (assets / ASSET_CSS).read_text(),
        SLOT_LIB: script_safe(vendor_script()),
        SLOT_APP: script_safe(app),
        SLOT_DATA: payload,
    }
    # one pass over the template, so text inside an inserted value is never taken for a slot
    pattern = re.compile("|".join(re.escape(slot) for slot in values))
    return pattern.sub(lambda m: values[m.group(0)], (assets / ASSET_TEMPLATE).read_text())
