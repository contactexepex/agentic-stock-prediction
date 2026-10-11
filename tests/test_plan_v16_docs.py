"""ST-01: the final design v16 is committed unchanged, and its clarification register (errata) lists exactly the
DCs of the approved stories document's Appendix 2, with the same text (docs/PLAN_v16*.md)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
V16_SHA256 = "a19e3405530b691423f68ffb21a272482554fbee5ce0d875a578a50159d3e19b"
DC_ROW = re.compile(r"^\| (DC-\d+) \|.*$", re.M)


def dc_rows(text: str) -> dict[str, str]:
    return {m.group(1): m.group(0) for m in DC_ROW.finditer(text)}


def appendix_2(stories: str) -> str:
    return stories[stories.index("## Appendix 2:"):stories.index("\n## Appendix 3:")]


def test_v16_is_committed_unchanged():
    assert hashlib.sha256((DOCS / "PLAN_v16.md").read_bytes()).hexdigest() == V16_SHA256


def test_errata_lists_every_dc_of_appendix_2_and_nothing_else():
    expected = dc_rows(appendix_2((DOCS / "PLAN_v16_stories.md").read_text()))
    published = dc_rows((DOCS / "PLAN_v16_errata.md").read_text())
    assert expected, "Appendix 2 of the stories document has no DC rows"
    assert list(published) == list(expected)
    assert published == expected


def test_dc_row_parser_catches_a_missing_dc():
    stories = "## Appendix 2: x\n\n| DC-1 | a | b | c |\n| DC-2 | d | e | f |\n\n## Appendix 3: y\n"
    errata = "| DC-1 | a | b | c |\n"
    assert list(dc_rows(errata)) != list(dc_rows(appendix_2(stories)))
