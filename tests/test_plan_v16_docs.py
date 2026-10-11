"""ST-01: the final design v16 is committed unchanged, and its clarification register (errata) lists exactly the
DCs of the approved stories document's Appendix 2, with the same text (docs/PLAN_v16*.md)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
V16_SHA256 = "a19e3405530b691423f68ffb21a272482554fbee5ce0d875a578a50159d3e19b"
DC_ROW = re.compile(r"^\| (DC-\d+) \|.*$", re.M)


def dc_rows(text: str) -> list[tuple[str, str]]:
    """Every DC row in file order as (identifier, full row); duplicates are kept so that they can be detected."""
    return [(m.group(1), m.group(0)) for m in DC_ROW.finditer(text)]


def appendix_2(stories: str) -> str:
    return stories[stories.index("## Appendix 2:"):stories.index("\n## Appendix 3:")]


def register_matches(errata: str, stories: str) -> bool:
    expected = dc_rows(appendix_2(stories))
    ids = [dc for dc, _ in expected]
    return bool(expected) and len(ids) == len(set(ids)) and dc_rows(errata) == expected


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_v16_is_committed_unchanged():
    assert hashlib.sha256((DOCS / "PLAN_v16.md").read_bytes()).hexdigest() == V16_SHA256


def test_errata_lists_every_dc_of_appendix_2_and_nothing_else():
    assert register_matches(read("PLAN_v16_errata.md"), read("PLAN_v16_stories.md"))


def test_register_check_rejects_missing_changed_extra_and_duplicate_rows():
    stories = "## Appendix 2: x\n\n| DC-1 | a | b | c |\n| DC-2 | d | e | f |\n\n## Appendix 3: y\n"
    good = "| DC-1 | a | b | c |\n| DC-2 | d | e | f |\n"
    assert register_matches(good, stories)
    assert not register_matches("| DC-1 | a | b | c |\n", stories)                       # missing DC-2
    assert not register_matches(good.replace("| d |", "| D |"), stories)                # changed text
    assert not register_matches(good + "| DC-3 | g | h | i |\n", stories)               # extra DC
    assert not register_matches("| DC-1 | old | b | c |\n" + good, stories)             # stale duplicate first
    assert not register_matches(good + "| DC-1 | a | b | c |\n", stories)              # exact duplicate later
