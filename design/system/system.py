"""Inline the cockpit design system into a page (design/README.md: self-contained output, no requests).

    from system import inline_system          # design/system on sys.path
    html = inline_system(template_html, icons=["check", "close"])

Markers in a template: ``<!--@@SYSTEM_CSS@@-->`` becomes a <style> with tokens.css + components.css,
``<!--@@ICONS@@-->`` becomes the Material Symbols sprite (all icons, or the subset given). Both files are
read at build time, so a page never carries a stale copy of the system knowingly.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK_CSS = "<!--@@SYSTEM_CSS@@-->"
MARK_ICONS = "<!--@@ICONS@@-->"


def tokens_css() -> str:
    return (HERE / "tokens.css").read_text()


def components_css() -> str:
    return (HERE / "components.css").read_text()


def icon_names() -> list[str]:
    return re.findall(r'<symbol id="ms-([a-z0-9_]+)"', (HERE / "icons.svg").read_text())


def icons_sprite(names: list[str] | None = None) -> str:
    """The sprite with every icon, or only `names` (unknown names raise, so a typo never ships a blank icon)."""
    sprite = (HERE / "icons.svg").read_text()
    if names is None:
        return sprite
    known = set(icon_names())
    missing = sorted(set(names) - known)
    if missing:
        raise KeyError(f"icons not in icons.svg: {missing}")
    header = re.match(r"<svg[^>]*>\n(?:  <!--.*?-->\n)?", sprite, re.S).group(0)
    symbols = {m.group(1): m.group(0) for m in re.finditer(r'  <symbol id="ms-([a-z0-9_]+)".*?</symbol>', sprite, re.S)}
    return header + "\n".join(symbols[n] for n in names) + "\n</svg>\n"


def inline_system(html: str, icons: list[str] | None = None) -> str:
    css = f"<style>\n{tokens_css()}\n{components_css()}\n</style>"
    out = html.replace(MARK_CSS, css).replace(MARK_ICONS, icons_sprite(icons))
    for mark in (MARK_CSS, MARK_ICONS):
        assert mark not in out
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Inline the design system into a template")
    ap.add_argument("template")
    ap.add_argument("out")
    a = ap.parse_args()
    Path(a.out).write_text(inline_system(Path(a.template).read_text()))
    print(a.out, Path(a.out).stat().st_size, "bytes")
