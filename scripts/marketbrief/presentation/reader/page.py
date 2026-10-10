"""The reader's daily report page (C2): one self-contained HTML file (inline CSS, JS, data and icons; no network)
built from assets/ and the cockpit design system's tokens and icons (design/system, B7), read at build time so the
page never carries a stale copy. html_report.py passes the view, the narrative and the reader block."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
SYSTEM = HERE.parents[3] / "design" / "system"   # scripts/marketbrief/presentation/reader -> repo root
JS_FILES = ("base.js", "cards.js")
ICONS = ("warning", "trending_up", "trending_down")
SYMBOL_RE = re.compile(r'<symbol id="ms-([a-z0-9_]+)".*?</symbol>', re.S)


def tokens_css() -> str:
    """The design system's tokens (custom properties and type-role classes), light scheme."""
    return (SYSTEM / "tokens.css").read_text()


def icons_sprite(names: tuple[str, ...] = ICONS) -> str:
    """A hidden SVG sprite with only the named Material Symbols of design/system/icons.svg."""
    symbols = {m.group(1): m.group(0) for m in SYMBOL_RE.finditer((SYSTEM / "icons.svg").read_text())}
    missing = [name for name in names if name not in symbols]
    if missing:
        raise ValueError(f"icons not in design/system/icons.svg: {missing}")
    return ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">'
            + "".join(symbols[name] for name in names) + "</svg>")


def css() -> str:
    """The page's stylesheet (tokens first, then the page's own rules); the report index uses it too."""
    return tokens_css() + "\n" + (ASSETS / "reader.css").read_text()


def script() -> str:
    """The page's script: the asset files in order inside one strict-mode function."""
    body = "\n".join((ASSETS / name).read_text() for name in JS_FILES)
    return "(function(){\n'use strict';\n" + body + "\n})();"


def payload(data: dict) -> str:
    """The embedded JSON, safe inside a <script> element."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render(title: str, meta: str, data: dict) -> str:
    """The whole page."""
    values = {"__TITLE__": html.escape(title), "__META__": meta, "__TOKENS__": tokens_css(),
              "__CSS__": (ASSETS / "reader.css").read_text(), "__ICONS__": icons_sprite(),
              "__DATA__": payload(data), "__JS__": script()}
    pattern = re.compile("|".join(re.escape(key) for key in values))
    return pattern.sub(lambda m: values[m.group(0)], (ASSETS / "page.html").read_text())
