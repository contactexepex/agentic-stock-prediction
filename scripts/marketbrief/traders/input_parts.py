"""A trader's input in parts it can read whole (issue from the first live runs, 2026-10-08/09: a trader's single Read
of a 400-line input stopped part-way, so it decided on part of its input).

`prepare` writes the input as parts of at most PART_BYTES each: work/traders/<strategy_id>.md (part 1, which lists
every part) and <strategy_id>.part<k>.md. Lines longer than LINE_CHARS are wrapped at a space, since the Read tool
cuts longer lines. Each part ends with a check fragment (4 hex characters of the part's SHA-256), and
work/traders/<strategy_id>.check holds the fragments joined by "-". Every line the trader writes carries
`input_check` = that value: the gate refuses a line without it (INPUT_UNREAD), so a decision on part of the input
never reaches the store. Without a .check file (no prepare run, tests) the check is off."""
from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

PART_BYTES = 24 * 1024     # well inside one Read call (a live trader's single Read stopped after 343 of 432 lines)
LINE_CHARS = 1500          # the Read tool cuts lines longer than 2000 characters
CHECK_FIELD = "input_check"


def wrapped(text: str) -> list[str]:
    """The text's lines, each longer than LINE_CHARS wrapped at spaces (a table row or a long sentence)."""
    out = []
    for line in text.splitlines():
        out += textwrap.wrap(line, LINE_CHARS, break_long_words=True, break_on_hyphens=False) \
            if len(line) > LINE_CHARS else [line]
    return out


def chunks(text: str, part_bytes: int = PART_BYTES) -> list[str]:
    """The text cut at line ends into chunks of at most part_bytes (one wrapped line never exceeds it)."""
    parts, current, size = [], [], 0
    for line in wrapped(text):
        width = len(line.encode("utf-8")) + 1
        if current and size + width > part_bytes:
            parts.append("\n".join(current) + "\n")
            current, size = [], 0
        current.append(line)
        size += width
    if current or not parts:
        parts.append("\n".join(current) + "\n")
    return parts


def fragment(body: str) -> str:
    """The check fragment of one part's body."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:4]


def part_name(strategy_id: str, number: int) -> str:
    """The file name of part `number` (1-based)."""
    return f"{strategy_id}.md" if number == 1 else f"{strategy_id}.part{number}.md"


def write_parts(folder: Path, strategy_id: str, text: str) -> tuple[list[Path], str]:
    """Write the parts and the .check file; (the part paths, the check value). Stale parts of an earlier run go."""
    for old in folder.glob(f"{strategy_id}.part*.md"):
        old.unlink()
    bodies = chunks(text)
    total, names = len(bodies), [part_name(strategy_id, k) for k in range(1, len(bodies) + 1)]
    fragments, out = [], []
    for number, body in enumerate(bodies, 1):
        tag = fragment(body)
        fragments.append(tag)
        head = (f"<!-- part {number} of {total}. Read every part in full, in order: "
                + ", ".join(f"work/traders/{name}" for name in names) + " -->\n\n") if number == 1 else \
            f"<!-- part {number} of {total} -->\n\n"
        path = folder / names[number - 1]
        path.write_text(head + body + f"\n<!-- end of part {number} of {total}; check fragment {tag} -->\n",
                        encoding="utf-8")
        out.append(path)
    check = "-".join(fragments)
    (folder / f"{strategy_id}.check").write_text(check + "\n", encoding="utf-8")
    return out, check


def expected(folder: Path, strategy_id: str) -> str | None:
    """The check value prepare wrote for this trader, or None (no prepare run: the check is off)."""
    path = folder / f"{strategy_id}.check"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None
