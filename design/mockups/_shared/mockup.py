"""Shared builder of the design-track mockups (design/mockups/<NN-page>/build.py imports it).

    from mockup import catalogue, pick, build_page, run

`catalogue(name)` reads design/catalogue/<name>.json; `pick(record, fields)` copies the named fields; `run(compose,
here)` composes the page's data with `compose(files, cutoff)`, writes data.json and page.html next to the page's
template.html (or into --out) and prints a summary. The page's HTML gets the design system (design/system/) and the
shared shell (shell.css, shell.js of this folder) inlined: markers `<!--@@SYSTEM_CSS@@-->`, `<!--@@SHARED_CSS@@-->`
and `<!--@@ICONS@@-->`, `<!--@@SHARED_JS@@-->`, and `/*__DATA__*/null` for the payload. Deterministic: `cutoff` is the
catalogue files' shared `as_of` clock; nothing reads the wall clock.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
CATALOGUE = os.path.join(REPO, "design", "catalogue")
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from system import inline_system  # noqa: E402

NOTE = ("EXAMPLE DATA for page design only: every value is copied from W1's example files in design/catalogue/ "
        "(docs/DATA_CATALOGUE.md). Predictions, trades, reasons and scores are invented there and consistent "
        "with each other. Not a forecast, not advice. Paper only.")
MARKETS = ("india", "us")
HORIZONS = (1, 2, 3, 4, 5)       # config/strategies.yaml horizons (decision 37); N+1 opens (decision 39)
MARK_SHARED_CSS = "<!--@@SHARED_CSS@@-->"
MARK_SHARED_JS = "<!--@@SHARED_JS@@-->"


def catalogue(name: str) -> dict:
    with open(os.path.join(CATALOGUE, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


def load(names: tuple) -> tuple[dict, str]:
    files = {name: catalogue(name) for name in names}
    cutoffs = {files[name]["as_of"] for name in names}
    assert len(cutoffs) == 1, cutoffs
    return files, cutoffs.pop()


def pick(record: dict, fields: tuple) -> dict:
    return {field: record[field] for field in fields}


def envelope(page: str, spec: str, endpoint: str, read_model: str, names: tuple, cutoff: str, markets: dict) -> dict:
    return {
        "_example": True, "_note": NOTE, "page": page, "spec": spec, "endpoint": endpoint, "read_model": read_model,
        "sources": [f"design/catalogue/{name}.json" for name in names],
        "as_of": min(p["as_of"] for p in markets.values()), "cutoff": cutoff,
        "built_at": max(p["built_at"] for p in markets.values()), "markets": markets,
    }


def render(template: str, data: dict) -> str:
    with open(os.path.join(HERE, "shell.css"), encoding="utf-8") as handle:
        css = f"<style>\n{handle.read()}\n</style>"
    with open(os.path.join(HERE, "shell.js"), encoding="utf-8") as handle:
        js = f"<script>\n{handle.read()}\n</script>"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace(MARK_SHARED_CSS, css).replace(MARK_SHARED_JS, js).replace("/*__DATA__*/null", payload)
    for mark in (MARK_SHARED_CSS, MARK_SHARED_JS):
        assert mark not in html, mark
    return inline_system(html)


def run(compose, here: str, summary=None) -> dict:
    parser = argparse.ArgumentParser(description="Build this mockup from design/catalogue/ into page.html")
    parser.add_argument("--out", default=here)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    data = compose()
    with open(os.path.join(args.out, "data.json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    with open(os.path.join(here, "template.html"), encoding="utf-8") as handle:
        html = render(handle.read(), data)
    out = os.path.join(args.out, "page.html")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(html)
    if summary:
        for market, payload in data["markets"].items():
            print(f"{market}: {summary(payload)}")
    print(out, len(html), "bytes")
    return data
