"""Scratch roots: pointing readers at another root, running scripts on it, guarding its location."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from marketbrief.core import paths
from marketbrief.constants.ai_replay import MARKER
from marketbrief.constants.ai_replay import (
    MSG_FAILED_IN_EXIT,
    MSG_ROOT_ALREADY_HOLDS_A_PREPARED_REPLAY,
    MSG_ROOT_EXISTS_IS_NOT_EMPTY_AND,
    MSG_ROOT_MUST_NOT_BE_THE_SOURCE,
    MSG_ROOT_MUST_NOT_CONTAIN_THE_SOURCE,
)


@contextmanager
def data_root(root: Path):
    """Point connect() at another root inside this process."""
    old = paths.ROOT
    paths.ROOT = Path(root)
    try:
        yield
    finally:
        paths.ROOT = old


def run_script(
    script: str, root: Path, market: str, *args: str, now: str | None = None, timeout: int | None = None
) -> subprocess.CompletedProcess:
    """Run scripts/<script> on another root (MB_ROOT=root, MB_CONFIG=root/config), as of `now` if given."""
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(root / "config"), "MB_MARKET": market}
    env.pop("MB_NOW", None)
    if now:
        env["MB_NOW"] = now
    return subprocess.run(
        [sys.executable, str(paths.CODE / "scripts" / script), "--market", market, *args],
        cwd=paths.CODE / "scripts",
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def run_step(script: str, root: Path, market: str, now: str, *args: str, stdout: Path | None = None) -> str:
    process = run_script(script, root, market, *args, now=now)
    if process.returncode != 0:
        raise SystemExit(
            MSG_FAILED_IN_EXIT.format(
                script=script, root=root, returncode=process.returncode, value=process.stderr[-3000:]
            )
        )
    if stdout is not None:
        stdout.parent.mkdir(parents=True, exist_ok=True)
        stdout.write_text(process.stdout, encoding="utf-8")
    return process.stdout


def json_or_text(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip()[-2000:]


def check_root(root: Path, src: Path, force: bool) -> None:
    root, src = root.resolve(), src.resolve()
    if root == src or src in root.parents and (src / "data") in [root, *root.parents]:
        raise SystemExit(MSG_ROOT_MUST_NOT_BE_THE_SOURCE.format(root=root))
    if root in src.parents or root == src:
        raise SystemExit(MSG_ROOT_MUST_NOT_CONTAIN_THE_SOURCE.format(root=root))
    if root.exists() and any(root.iterdir()):
        if not (root / MARKER).exists():
            raise SystemExit(MSG_ROOT_EXISTS_IS_NOT_EMPTY_AND.format(root=root))
        if not force:
            raise SystemExit(MSG_ROOT_ALREADY_HOLDS_A_PREPARED_REPLAY.format(root=root))
        shutil.rmtree(root)
