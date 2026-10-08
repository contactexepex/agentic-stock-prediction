#!/usr/bin/env python3
"""Golden outputs for the refactor: run the deterministic pipeline on a pinned copy of the data and
compare every output byte for byte with a recorded run (docs/REFACTOR_PLAN.md, "Golden outputs").

  python tests/golden/golden.py record  [--dir work/golden]   record the golden set from this checkout
  python tests/golden/golden.py compare [--dir work/golden]   rerun into DIR/fresh and diff against DIR/run
  python tests/golden/golden.py run --out DIR                 one run into DIR, no comparison
  each takes --serial (every step in list order in one root, as before; about 5.5 minutes) or
  --jobs N (the default parallel schedule: both markets at once, each on its own copy of the seeded
  root, up to N steps of a market at a time where they do not conflict; about 2 minutes on 4 cores;
  tests/golden/parallel.py). Both give the same bytes, so a record of one compares with the other.

Inputs are fixed: data/, config/ and reports/ come from git commit INPUT_COMMIT (never the working
tree, so daily-run appends do not change them), plus a synthetic overlay built by rules in overlay.py
(stored calls of REVIEW_WEEK, a forecaster file with one call that breaks the rules, lessons, and a
filled report). Every script runs as a subprocess on that scratch root with MB_ROOT, MB_CONFIG,
MB_MARKET and a fixed MB_NOW per phase, PYTHONHASHSEED=0, TZ=UTC and the test network guard on
(tests/netguard), so nothing reaches the network. The code under test (scripts/, sql/, templates/) is
this checkout's.

Two phases per market, each with its own frozen clock (PHASE_CLOCKS):
- pre_open: the morning of 2026-10-05, when the stored bars are current: the normal path (fresh
  bars, scoring, US 1d and 5d ranges published, India's already stored, report, HTML, Slack dry run);
- late: the morning of 2026-10-06, after every stored input was collected: news visible, bars a
  session behind (validate failures), late-path ranges, forecaster gate, lessons, review, spot-check,
  backtest, replays, ai_replay, Neo4j dry run.

Compared: each step's exit code, stdout and stderr, and every file under the scratch root that the
run created or changed (sha256 of the normalised bytes); an input file the run deleted is a
difference too. Normalisation, applied before hashing, is limited to:
- the run directory's absolute path -> <RUN>, this checkout's absolute path -> <CODE>;
- the NORMALISED entries: four wall-clock values (durations and build times that do not follow
  MB_NOW), each masked only in the output paths where it appears.
Child processes load tests/golden/site/sitecustomize.py: the network guard. DuckDB runs with its
default threads, as in production: the queries whose row order or float sums reach an output have a
full ORDER BY or an order-independent aggregate (docs/REFACTOR_PLAN.md, "Known nondeterminism",
fixed). GOLDEN_DUCKDB_THREADS=N sets N threads on every DuckDB connection (a stress check; the
manifest records it). The OpenMP / BLAS thread pools of numpy and scikit-learn get one thread per child
(OMP_NUM_THREADS, OPENBLAS_NUM_THREADS, MKL_NUM_THREADS = 1 unless already set; issue #45): the seed steps run in
parallel, and two concurrent harness or review runs oversubscribed the cores (1316 s instead of 122 s). A set
recorded before this setting may differ in the last float digits of the model outputs: record it again.
Nothing else is masked. The recorded set (manifest plus full copies, for diffs) lives under --dir,
by default work/golden (git-ignored)."""
from __future__ import annotations

import argparse
import difflib
import fnmatch
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from parallel import copy_base, file_hashes, market_dir, merge_market, run_dag
from seed import run_seed

from overlay import (INPUT_COMMIT, append_valid_calls, copy_model_config, fill_report, git_inputs,
                     write_forecaster_file, write_claims, write_lessons, write_past_calls)

CODE = Path(__file__).resolve().parents[2]
SCRIPTS = CODE / "scripts"
NETGUARD = CODE / "tests" / "netguard"
GOLDEN_SITE = CODE / "tests" / "golden" / "site"
DEFAULT_DIR = CODE / "work" / "golden"
MARKETS = ("india", "us")
PHASES = ("pre_open", "late")
DEFAULT_JOBS = 3   # concurrent steps per market in the parallel schedule

PHASE_CLOCKS = {
    "india": {"pre_open": "2026-10-05T02:40:00+00:00", "late": "2026-10-06T02:30:00+00:00"},
    "us": {"pre_open": "2026-10-05T12:15:00+00:00", "late": "2026-10-06T12:15:00+00:00"},
}
MID_SESSION_CHECK = "2026-10-05T15:00:00+00:00"
REVIEW_WEEK = "2026-W39"
REPLAY_WINDOW = ("2026-09-14", "2026-10-01")
BACKTEST_SESSIONS = "40"
AI_REPLAY_DATE = "2026-09-25"

# Values that come from the wall clock, not MB_NOW, each masked only in the outputs (paths relative
# to the run directory, fnmatch patterns) where it was seen: (paths, regex, replacement).
NORMALISED = (
    (("root/data/*/replays/*/*/*.jsonl", "root/reports/*/replay-*.json", "steps/*/late.replay*.stdout"),
     rb'("runtime_s"\s*:\s*)(-?[0-9][0-9.eE+-]*)', rb'\1"<normalised>"'),               # replay.py
    (("root/reports/*/replay-*.html",), rb"runtime \d+ s\.", b"runtime <normalised> s."),       # replay.py
    (("root/reports/*/????-??-??.html", "root/work/slack_*_plan/????-??-??.html"),
     rb'("generated_at"\s*:\s*)("[^"]*")', rb'\1"<normalised>"'),                         # view_data.py
    (("ai_replay_*/ai_replay.json", "steps/*/late.ai_replay_prepare.stdout"),
     rb'("prepared_at"\s*:\s*)("[^"]*")', rb'\1"<normalised>"'),                          # ai_replay.py
    (("steps/*/late.news_clusters.stdout",),
     rb'("seconds"\s*:\s*)(-?[0-9][0-9.eE+-]*)', rb'\1"<normalised>"'),                   # news_clusters.py
)
PY = "{python}"


# ---------- the steps ----------

def steps(market: str) -> list[tuple[str, str, object, str | None]]:
    """(phase, label, argv or callable(root, market, clock), file under root that receives stdout)."""
    replay_window = ["--start", REPLAY_WINDOW[0], "--end", REPLAY_WINDOW[1]]
    ai_root = "{run}/ai_replay_" + market
    pre_open = [
        ("market_status", [PY, "market_status.py", "--now", PHASE_CLOCKS[market]["pre_open"]], None),
        ("market_status_mid_session", [PY, "market_status.py", "--now", MID_SESSION_CHECK], None),
        ("validate_collect", [PY, "validate.py", "--stage", "collect"], None),
        ("score_predictions", [PY, "score_predictions.py"], None),
        ("features", [PY, "features.py"], None),
        ("calibrate", [PY, "calibrate.py"], None),
        ("validate_features", [PY, "validate.py", "--stage", "features"], None),
        ("model_config", copy_model_config, None),
        ("model_scores", [PY, "model_scores.py"], None),
        ("context", [PY, "context.py"], "work/context.md"),
        ("validate_context", [PY, "validate.py", "--stage", "context"], None),
        ("validate_forecast_absent", [PY, "validate.py", "--stage", "forecast"], None),
        ("ranges", [PY, "ranges.py"], None),
        ("context_after_ranges", [PY, "context.py"], "work/context.md"),
        ("charts", [PY, "charts.py"], None),
        ("report", [PY, "report.py"], None),
        ("fill_report", fill_report, None),
        ("validate_report", [PY, "validate.py", "--stage", "report"], None),
        ("html_report", [PY, "html_report.py"], None),
        ("notify_slack_dry_run", [PY, "notify_slack.py", "--dry-run"], None),
    ]
    late = [
        ("market_status", [PY, "market_status.py", "--now", PHASE_CLOCKS[market]["late"]], None),
        ("validate_collect", [PY, "validate.py", "--stage", "collect"], None),
        ("score_predictions", [PY, "score_predictions.py"], None),
        ("lessons_prepare", [PY, "lessons.py", "prepare"], None),
        ("lessons_write", write_lessons, None),
        ("lessons_validate", [PY, "lessons.py", "validate", "{root}/work/lessons.jsonl"], None),
        ("lessons_add", [PY, "lessons.py", "add", "{root}/work/lessons.jsonl"], None),
        ("features", [PY, "features.py"], None),
        ("calibrate", [PY, "calibrate.py"], None),
        ("validate_features", [PY, "validate.py", "--stage", "features"], None),
        ("model_scores", [PY, "model_scores.py"], None),
        ("news_clusters", [PY, "news_clusters.py"], None),
        ("claims_prepare", [PY, "claims.py", "prepare"], None),
        ("claims_write", write_claims, None),
        ("claims_validate", [PY, "claims.py", "validate", "{root}/work/claims.jsonl"], None),
        ("claims_add", [PY, "claims.py", "add", "{root}/work/claims.jsonl"], None),
        ("news_status", [PY, "news_status.py"], None),
        ("context", [PY, "context.py"], "work/context.md"),
        ("validate_context", [PY, "validate.py", "--stage", "context"], None),
        ("forecaster_file", write_forecaster_file, None),
        ("validate_forecast", [PY, "validate.py", "--stage", "forecast"], None),
        ("append_valid_calls", append_valid_calls, None),
        ("ranges", [PY, "ranges.py"], None),
        ("context_after_ranges", [PY, "context.py"], "work/context.md"),
        ("review", [PY, "review.py", "--week", REVIEW_WEEK], None),
        ("review_if_due", [PY, "review.py", "--if-due", "--week", REVIEW_WEEK], None),
        ("charts", [PY, "charts.py"], None),
        ("report", [PY, "report.py", "--force"], None),
        ("fill_report", fill_report, None),
        ("validate_report", [PY, "validate.py", "--stage", "report"], None),
        ("html_report", [PY, "html_report.py"], None),
        ("spotcheck", [PY, "spotcheck.py", "--week", REVIEW_WEEK], None),
        ("graph_status", [PY, "graph.py", "status"], None),
        ("backtest", [PY, "backtest.py", "--eval-sessions", BACKTEST_SESSIONS], None),
        ("replay", [PY, "replay.py", *replay_window], None),
        ("replay_aci", [PY, "replay.py", *replay_window, "--aci"], None),
        ("ai_replay_dates", [PY, "ai_replay.py", "dates"], None),
        ("ai_replay_prepare", [PY, "ai_replay.py", "prepare", "--date", AI_REPLAY_DATE, "--root", ai_root,
                               "--source", "{root}"], None),
        ("ai_replay_record", [PY, "ai_replay.py", "record", "--date", AI_REPLAY_DATE, "--root", ai_root,
                              "--calls", "{run}/no_calls.jsonl", "--results", "{run}/ai_replay_results"], None),
        ("ai_replay_score", [PY, "ai_replay.py", "score", "--results", "{run}/ai_replay_results",
                             "--out", "{run}/ai_replay_results/score_" + market + ".html"], None),
        ("neo4j_dry_run", [PY, "neo4j_sync.py", "--dry-run", "--full"], None),
        ("validate_all", [PY, "validate.py", "--stage", "all"], None),
    ]
    return [("pre_open", *s) for s in pre_open] + [("late", *s) for s in late]


THREAD_POOL_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def environment(root: Path, market: str, clock: str) -> dict[str, str]:
    """The child environment: frozen clock, fixed hash seed, network guard, one OpenMP/BLAS thread, no credentials
    or proxies."""
    dropped = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SLACK_BOT_TOKEN", "SLACK_WEBHOOK_URL",
               "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE", "SEC_USER_AGENT"}
    env = {k: v for k, v in os.environ.items() if not k.startswith("MB_") and k.upper() not in dropped}
    env.update({"MB_ROOT": str(root), "MB_CONFIG": str(root / "config"), "MB_MARKET": market, "MB_NOW": clock,
                "PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C.UTF-8", "MPLBACKEND": "Agg",
                "PYTHONPATH": os.pathsep.join([str(GOLDEN_SITE), str(NETGUARD)]),
                "MB_NETGUARD": "on", "MB_NETGUARD_LOG": str(root.parent / "netguard.log")})
    for name in THREAD_POOL_VARIABLES:
        env.setdefault(name, "1")
    return env


def run_all(run_dir: Path, serial: bool = False, jobs: int = DEFAULT_JOBS) -> dict:
    """One full run into run_dir/root with step logs in run_dir/steps/<market>/; returns the outputs map.
    serial: every step in list order in one root; else the parallel schedule of parallel.py (same bytes)."""
    if run_dir.exists():
        shutil.rmtree(run_dir)
    root = run_dir / "root"
    root.mkdir(parents=True)
    git_inputs(root)
    (root / ".scratch-ok").write_text("golden scratch root\n")
    (root / "work").mkdir()
    (run_dir / "no_calls.jsonl").write_text("")
    for market in MARKETS:
        write_past_calls(root, market)
    before = snapshot(run_dir)
    run_seed(run_dir, root, environment, SCRIPTS, parallel=not serial)
    overlaps = []
    if serial:
        for market in MARKETS:
            run_market(run_dir, market, None)
    else:
        overlaps = run_markets_parallel(run_dir, jobs)
    after = snapshot(run_dir)
    outputs = {"changed": {p: h for p, h in after.items() if before.get(p) != h},
               "deleted": sorted(p for p in before if p not in after)}
    if not serial:
        outputs["market_overlaps"] = overlaps
    (run_dir / "outputs.json").write_text(json.dumps(outputs, indent=1, sort_keys=True))
    return outputs


def run_market(run_dir: Path, market: str, jobs: int | None) -> None:
    """Both phases of one market on run_dir/root; jobs None = one step at a time in list order."""
    (run_dir / "steps" / market).mkdir(parents=True, exist_ok=True)
    for phase in PHASES:
        os.environ["GOLDEN_PHASE"] = phase
        items = [s for s in steps(market) if s[0] == phase]
        if jobs is None:
            for item in items:
                run_step(run_dir, market, item)
        else:
            run_dag([s[1] for s in items], lambda i, items=items: run_step(run_dir, market, items[i]), jobs)


def run_step(run_dir: Path, market: str, item: tuple) -> None:
    phase, label, command, stdout_file = item
    root, clock = run_dir / "root", PHASE_CLOCKS[market][phase]
    if callable(command):
        command(root, market, clock)
        return
    argv = [a.format(python=sys.executable, root=root, run=run_dir) for a in command]
    proc = subprocess.run(argv, cwd=SCRIPTS, env=environment(root, market, clock), capture_output=True,
                          text=True, check=False)
    prefix = run_dir / "steps" / market / f"{phase}.{label}"
    prefix.with_name(prefix.name + ".stdout").write_text(proc.stdout)
    prefix.with_name(prefix.name + ".stderr").write_text(proc.stderr)
    prefix.with_name(prefix.name + ".exit").write_text(f"{proc.returncode}\n")
    if stdout_file:
        (root / stdout_file).write_text(proc.stdout)


def run_markets_parallel(run_dir: Path, jobs: int) -> list[str]:
    """Each market on its own copy of the seeded run directory, both at once (parallel.py); then merge
    the copies back in MARKETS order. Returns the paths both markets wrote (the later market's kept)."""
    def raw(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
    skip = {"netguard.log"}
    base = {p: h for p, h in file_hashes(run_dir, raw).items() if p not in skip}
    dirs = {market: market_dir(run_dir, market) for market in MARKETS}
    for target in dirs.values():
        copy_base(run_dir, target)
        (target / "netguard.log").unlink(missing_ok=True)
    with ProcessPoolExecutor(max_workers=len(MARKETS), mp_context=multiprocessing.get_context("fork")) as pool:
        for future in [pool.submit(run_market, dirs[m], m, jobs) for m in MARKETS]:
            future.result()
    seen, overlaps = set(), []
    for market in MARKETS:
        written, _ = merge_market(dirs[market], run_dir, base, raw, skip)
        overlaps += sorted(seen & set(written))
        seen |= set(written)
        log = dirs[market] / "netguard.log"
        if log.exists():
            with (run_dir / "netguard.log").open("a") as handle:
                handle.write(log.read_text())
        shutil.rmtree(dirs[market])
    return overlaps


# ---------- hashing and comparison ----------

def normalise(content: bytes, run_dir: Path, relative_path: str) -> bytes:
    """Absolute run paths -> <RUN>, checkout paths -> <CODE>, then the NORMALISED entries for this path."""
    content = content.replace(str(run_dir.resolve()).encode(), b"<RUN>").replace(str(CODE).encode(), b"<CODE>")
    for paths, pattern, replacement in NORMALISED:
        if any(fnmatch.fnmatch(relative_path, p) for p in paths):
            content = re.sub(pattern, replacement, content)
    return content


def snapshot(run_dir: Path) -> dict[str, str]:
    """Relative path -> sha256 of the normalised bytes, for every file of the run except bookkeeping."""
    skip = {"netguard.log", "outputs.json"}
    files = [p for p in sorted(run_dir.rglob("*")) if p.is_file() and p.name not in skip]
    return {p.relative_to(run_dir).as_posix():
            hashlib.sha256(normalise(p.read_bytes(), run_dir, p.relative_to(run_dir).as_posix())).hexdigest()
            for p in files}


def network_clean(run_dir: Path) -> bool:
    log = run_dir / "netguard.log"
    return not log.exists() or not log.read_text().strip()


def git_head() -> str:
    return subprocess.run(["git", "-C", str(CODE), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=False).stdout.strip()


def exit_codes(run_dir: Path) -> dict[str, int]:
    return {p.relative_to(run_dir / "steps").as_posix().removesuffix(".exit"): int(p.read_text())
            for p in sorted((run_dir / "steps").glob("*/*.exit"))}


def record(directory: Path, serial: bool, jobs: int) -> int:
    run_dir = directory / "run"
    started = time.monotonic()
    outputs = run_all(run_dir, serial, jobs)
    wall = round(time.monotonic() - started, 1)
    manifest = {**outputs, "input_commit": INPUT_COMMIT, "phase_clocks": PHASE_CLOCKS,
                "normalised": [{"paths": list(p), "pattern": r.decode()} for p, r, _ in NORMALISED],
                "duckdb_threads": os.environ.get("GOLDEN_DUCKDB_THREADS") or "default", "code_commit": git_head(),
                "schedule": "serial" if serial else f"parallel, {jobs} steps per market",
                "exit_codes": exit_codes(run_dir)}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    clean = network_clean(run_dir)
    print(json.dumps({"recorded": str(directory), "files": len(outputs["changed"]), "network_clean": clean,
                      "schedule": manifest["schedule"], "wall_s": wall,
                      "code_commit": manifest["code_commit"],
                      "nonzero_exits": {k: v for k, v in manifest["exit_codes"].items() if v}}, indent=1))
    return 0 if clean else 1


def compare(directory: Path, max_diff_lines: int, serial: bool, jobs: int) -> int:
    golden = json.loads((directory / "manifest.json").read_text())
    fresh_dir = directory / "fresh"
    started = time.monotonic()
    fresh = run_all(fresh_dir, serial, jobs)
    wall = round(time.monotonic() - started, 1)
    differing = sorted(p for p in set(golden["changed"]) | set(fresh["changed"])
                       if golden["changed"].get(p) != fresh["changed"].get(p))
    deleted_mismatch = sorted(set(golden["deleted"]) ^ set(fresh["deleted"]))
    for path in differing[:20]:
        old, new = directory / "run" / path, fresh_dir / path
        state = ("missing in the fresh run" if not new.exists()
                 else "new in the fresh run" if not old.exists() else "differs")
        print(f"--- {path}: {state}")
        if old.exists() and new.exists() and not path.endswith(".png"):
            a = normalise(old.read_bytes(), directory / "run", path).decode(errors="replace").splitlines()
            b = normalise(new.read_bytes(), fresh_dir, path).decode(errors="replace").splitlines()
            for line in list(difflib.unified_diff(a, b, lineterm="", n=1))[:max_diff_lines]:
                print(line[:300])
    clean = network_clean(fresh_dir)
    identical = not differing and not deleted_mismatch and clean
    print(json.dumps({"identical": identical, "compared_files": len(golden["changed"]), "differing": differing,
                      "deleted_mismatch": deleted_mismatch, "network_clean": clean,
                      "golden_code_commit": golden.get("code_commit"), "fresh_code_commit": git_head(),
                      "golden_schedule": golden.get("schedule", "serial"),
                      "fresh_schedule": "serial" if serial else f"parallel, {jobs} steps per market", "wall_s": wall},
                     indent=1))
    return 0 if identical else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "compare", "run"):
        p = sub.add_parser(name)
        if name == "run":
            p.add_argument("--out", type=Path, required=True)
        else:
            p.add_argument("--dir", type=Path, default=DEFAULT_DIR)
            p.add_argument("--max-diff-lines", type=int, default=40)
        p.add_argument("--serial", action="store_true", help="every step in list order in one root (slower)")
        p.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="concurrent steps per market (parallel run)")
    args = ap.parse_args()
    if args.cmd == "run":
        run_all(args.out.resolve(), args.serial, args.jobs)
        return 0
    directory = args.dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.cmd == "record":
        return record(directory, args.serial, args.jobs)
    return compare(directory, args.max_diff_lines, args.serial, args.jobs)


if __name__ == "__main__":
    sys.exit(main())
