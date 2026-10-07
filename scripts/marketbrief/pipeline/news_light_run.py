"""The news-only light run (routine/NEWS_PROMPT.md; docs/DESIGN.md section 3, "News timing"): every 4 hours,
every day including weekends and holidays, collect news so busy outlet feeds and a closed day lose nothing.

Runs, one after the other, each as its own script with this market (MB_MARKET), saving each JSON summary to
work/steps/<name>.json (summaries left in work/steps/ by an earlier run are deleted first: the gate reads them):
  collect_news.py                         headlines (catch-up window since the last successful run)
  collect_nse_india.py --only announcements   India only: NSE exchange filings, one market-wide call
  collect_articles.py                     article pages of material watchlist headlines (allowlisted outlets)
  news_clusters.py                        same-event clusters
  validate.py --stage news_collect        the gate of the news kinds (no price or calendar check)
Nothing else: no prices, no agents (no news analyst, claim checker, forecaster), no report, no Slack. A failed
collector does not stop the run (the gate lists it). Every script appends to data/ only (append-only files).
Prints a JSON summary: each step's exit code, `validate_ok`, `new_items`, the news `window`, and
`commit_paths` (the data folders of the news kinds that exist, for `git add`). Exit 1 when the gate failed
(commit nothing then), else 0."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from marketbrief.constants.environment import ENV_MARKET
from marketbrief.constants.news_light_run import (
    ARTICLES_STEP,
    CLUSTERS_STEP,
    INDIA,
    NEWS_STEP,
    NSE_STEP,
    STEP_NEWS_LIGHT_RUN,
    VALIDATE_STEP,
)
from marketbrief.constants.validation import NEWS_COLLECT_KINDS
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market

SCRIPTS_DIR = Path(__file__).resolve().parents[2]


def steps(market: str) -> list[tuple[str, list[str]]]:
    """(summary name, script and arguments) of each step, in order."""
    plan = [NEWS_STEP]
    if market == INDIA:
        plan.append(NSE_STEP)
    plan += [ARTICLES_STEP, CLUSTERS_STEP, VALIDATE_STEP]
    return [(name, list(command)) for name, command in plan]


def run_step(command: list[str], market: str, summary_path: Path) -> int:
    """Run one script of scripts/ with this market; its stdout is saved as the step's summary."""
    env = {**os.environ, ENV_MARKET: market}
    done = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / command[0]), *command[1:]],
        cwd=SCRIPTS_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    summary_path.write_text(done.stdout, encoding="utf-8")
    if done.stderr:
        sys.stderr.write(done.stderr)
    return done.returncode


def read_summary(path: Path) -> dict:
    """A saved step summary as a dict (empty when it is not JSON)."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def commit_paths(market: str) -> list[str]:
    """The data folders of the news kinds that exist (relative to the repo root), for `git add`."""
    base = paths.data_dir(market)
    return [
        (base / kind).relative_to(paths.ROOT).as_posix()
        for kind in NEWS_COLLECT_KINDS
        if (base / kind).is_dir() and any(path.is_file() for path in (base / kind).rglob("*"))
    ]


def light_run(market: str, runner=run_step) -> dict:
    """Run every step (see the module docstring) and return the summary."""
    steps_dir = paths.ROOT / "work" / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    for stale in steps_dir.glob("*.json"):  # the gate reads every collect_*.json: never an earlier run's
        stale.unlink()
    results = []
    for name, command in steps(market):
        summary_path = steps_dir / f"{name}.json"
        results.append({"step": name, "exit_code": runner(command, market, summary_path)})
    news = read_summary(steps_dir / f"{NEWS_STEP[0]}.json")
    gate = read_summary(steps_dir / f"{VALIDATE_STEP[0]}.json")
    return {
        "step": STEP_NEWS_LIGHT_RUN,
        "market": market,
        "steps": results,
        "new_items": news.get("new_items"),
        "window": news.get("window"),
        "validate_ok": bool(gate.get("ok")),
        "failures": gate.get("failures") or [],
        "warnings": gate.get("warnings") or [],
        "commit_paths": commit_paths(market),
    }


def main() -> int:
    """Entry point of scripts/collect_news_only.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    summary = light_run(cfg["market"])
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["validate_ok"] else 1
