"""The replay guard of the NSE collectors: `--replay DIR` reads responses from local files, which can be synthetic,
so replayed rows may only be written to an explicit scratch root. The check runs before anything (even a directory)
is created."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from marketbrief.constants.nse_collection import (
    MSG_NO_SCRATCH_MARKER,
    MSG_ROOT_HAS_PRICES,
    MSG_ROOT_LOOKS_LIKE_REPO,
    MSG_TARGET_HARD_LINKED,
    MSG_TARGET_IN_CHECKOUT_DATA,
    MSG_TARGET_IN_REPO,
    MSG_TARGET_OUTSIDE_ROOT,
    MSG_TARGET_SAME_FILE,
    PRICE_FILES_GLOB,
    REPO_MARKERS,
    SCRATCH_MARKER,
)
from marketbrief.core import paths
from marketbrief.core.paths import data_dir
from marketbrief.core.schemas import SCHEMAS


def write_target(market: str, kind: str, day: date) -> Path:
    """The file day_file() would append to, computed without creating any directory."""
    extension = SCHEMAS[kind][0]
    return data_dir(market) / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{extension}"


def root_problem(root: Path) -> str | None:
    """Why a root is no scratch root (no marker file, a repo checkout, a store with price files), or None."""
    if not (root / SCRATCH_MARKER).is_file():
        return MSG_NO_SCRATCH_MARKER.format(marker=SCRATCH_MARKER, root=root)
    for marker in REPO_MARKERS:
        if (root / marker).exists():
            return MSG_ROOT_LOOKS_LIKE_REPO.format(root=root, marker=marker)
    if any(path.is_file() for path in (root / "data").glob(PRICE_FILES_GLOB)):
        return MSG_ROOT_HAS_PRICES.format(root=root)
    return None


def target_problem(target: Path, base: Path, real_data: Path) -> str | None:
    """Why a write target is refused: outside the root's data/ (a symlink?), inside this checkout's data/ or any repo
    checkout, hard-linked, or the same file as one in this checkout's data/. None when it is safe."""
    resolved = target.resolve()  # follows any symlinked directory on the way
    if not resolved.is_relative_to(base):
        return MSG_TARGET_OUTSIDE_ROOT.format(target=target, resolved=resolved, base=base)
    if resolved.is_relative_to(real_data):
        return MSG_TARGET_IN_CHECKOUT_DATA.format(target=target, real=real_data)
    for parent in resolved.parents:  # never inside any repo checkout's data
        if any((parent / marker).exists() for marker in REPO_MARKERS):
            return MSG_TARGET_IN_REPO.format(target=target, parent=parent)
    if resolved.exists():  # hard links survive resolve(): check the inode itself
        status = resolved.stat()
        if status.st_nlink > 1:
            return MSG_TARGET_HARD_LINKED.format(target=target, links=status.st_nlink)
        real_inodes = {
            (inode_status.st_dev, inode_status.st_ino)
            for path in real_data.rglob("*")
            if path.is_file()
            for inode_status in [path.stat()]
        }
        if (status.st_dev, status.st_ino) in real_inodes:
            return MSG_TARGET_SAME_FILE.format(target=target)
    return None


def replay_problem(root: Path, targets: list[Path]) -> str | None:
    """Replayed rows can be synthetic, so they may only go to an explicit scratch root. Returns
    why `root` is refused, or None. Checked before anything (even a directory) is created."""
    root = Path(root)
    problem = root_problem(root)
    if problem:
        return problem
    base = root.resolve() / "data"  # the root's own data/, not where a data/ symlink points
    real_data = (paths.CODE / "data").resolve()
    for target in targets:
        problem = target_problem(target, base, real_data)
        if problem:
            return problem
    return None
