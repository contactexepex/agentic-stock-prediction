#!/usr/bin/env python3
"""Golden outputs for the refactor: run the deterministic pipeline on a pinned copy of the data and
compare every output byte for byte with a recorded run (docs/REFACTOR_PLAN.md, "Golden outputs").

  python tests/golden/golden.py record  [--dir work/golden]   record the golden set from this checkout
  python tests/golden/golden.py compare [--dir work/golden]   rerun into DIR/fresh and diff against DIR/run
  python tests/golden/golden.py run --out DIR                 one run into DIR, no comparison

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
- the values of NORMALISED_FIELDS and the NORMALISED_TEXT patterns (wall-clock durations and
  times that do not follow MB_NOW).
Child processes load tests/golden/site/sitecustomize.py: the network guard, and DuckDB on one thread
(queries without a full ORDER BY otherwise return rows in a varying order).
Nothing else is masked. The recorded set (manifest plus full copies, for diffs) lives under --dir,
by default work/golden (git-ignored)."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from overlay import (INPUT_COMMIT, append_valid_calls, fill_report, git_inputs, write_forecaster_file,
                     write_lessons, write_past_calls)

CODE = Path(__file__).resolve().parents[2]
SCRIPTS = CODE / "scripts"
NETGUARD = CODE / "tests" / "netguard"
GOLDEN_SITE = CODE / "tests" / "golden" / "site"
DEFAULT_DIR = CODE / "work" / "golden"
MARKETS = ("india", "us")

PHASE_CLOCKS = {
    "india": {"pre_open": "2026-10-05T02:40:00+00:00", "late": "2026-10-06T02:30:00+00:00"},
    "us": {"pre_open": "2026-10-05T12:15:00+00:00", "late": "2026-10-06T12:15:00+00:00"},
}
MID_SESSION_CHECK = "2026-10-05T15:00:00+00:00"
REVIEW_WEEK = "2026-W39"
REPLAY_WINDOW = ("2026-09-14", "2026-10-01")
BACKTEST_SESSIONS = "40"
AI_REPLAY_DATE = "2026-09-25"

# Values that come from the wall clock, not MB_NOW. JSON keys (replaced by "<normalised>" wherever
# the key appears): replay.py runtime_s, view_data.py generated_at (the HTML report's data),
# ai_replay.py prepare's prepared_at, news_clusters.py seconds. Text: replay.py's HTML footer
# "runtime N s".
NORMALISED_FIELDS = ("runtime_s", "generated_at", "prepared_at", "seconds")
NORMALISED_TEXT = ((rb"runtime \d+ s\.", b"runtime <normalised> s."),)
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
        ("news_clusters", [PY, "news_clusters.py"], None),
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


def environment(root: Path, market: str, clock: str) -> dict[str, str]:
    """The child environment: frozen clock, fixed hash seed, network guard, no credentials or proxies."""
    dropped = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SLACK_BOT_TOKEN", "SLACK_WEBHOOK_URL",
               "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE", "SEC_USER_AGENT"}
    env = {k: v for k, v in os.environ.items() if not k.startswith("MB_") and k.upper() not in dropped}
    env.update({"MB_ROOT": str(root), "MB_CONFIG": str(root / "config"), "MB_MARKET": market, "MB_NOW": clock,
                "PYTHONHASHSEED": "0", "TZ": "UTC", "LC_ALL": "C.UTF-8", "MPLBACKEND": "Agg",
                "PYTHONPATH": os.pathsep.join([str(GOLDEN_SITE), str(NETGUARD)]),
                "MB_NETGUARD": "on", "MB_NETGUARD_LOG": str(root.parent / "netguard.log")})
    return env


def run_all(run_dir: Path) -> dict:
    """One full run into run_dir/root with step logs in run_dir/steps/<market>/; returns the outputs map."""
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
    for market in MARKETS:
        (run_dir / "steps" / market).mkdir(parents=True, exist_ok=True)
        for phase, label, command, stdout_file in steps(market):
            clock = PHASE_CLOCKS[market][phase]
            os.environ["GOLDEN_PHASE"] = phase
            if callable(command):
                command(root, market, clock)
                continue
            argv = [a.format(python=sys.executable, root=root, run=run_dir) for a in command]
            proc = subprocess.run(argv, cwd=SCRIPTS, env=environment(root, market, clock), capture_output=True,
                                  text=True, check=False)
            prefix = run_dir / "steps" / market / f"{phase}.{label}"
            prefix.with_name(prefix.name + ".stdout").write_text(proc.stdout)
            prefix.with_name(prefix.name + ".stderr").write_text(proc.stderr)
            prefix.with_name(prefix.name + ".exit").write_text(f"{proc.returncode}\n")
            if stdout_file:
                (root / stdout_file).write_text(proc.stdout)
    after = snapshot(run_dir)
    outputs = {"changed": {p: h for p, h in after.items() if before.get(p) != h},
               "deleted": sorted(p for p in before if p not in after)}
    (run_dir / "outputs.json").write_text(json.dumps(outputs, indent=1, sort_keys=True))
    return outputs


# ---------- hashing and comparison ----------

def normalise(content: bytes, run_dir: Path) -> bytes:
    """Absolute run paths -> <RUN>, checkout paths -> <CODE>, NORMALISED_FIELDS values -> "<normalised>"."""
    content = content.replace(str(run_dir.resolve()).encode(), b"<RUN>").replace(str(CODE).encode(), b"<CODE>")
    for field in NORMALISED_FIELDS:
        content = re.sub(rb'("' + field.encode() + rb'"\s*:\s*)(-?[0-9][0-9.eE+-]*|"[^"]*")',
                         rb'\1"<normalised>"', content)
    for pattern, replacement in NORMALISED_TEXT:
        content = re.sub(pattern, replacement, content)
    return content


def snapshot(run_dir: Path) -> dict[str, str]:
    """Relative path -> sha256 of the normalised bytes, for every file of the run except bookkeeping."""
    skip = {"netguard.log", "outputs.json"}
    return {p.relative_to(run_dir).as_posix(): hashlib.sha256(normalise(p.read_bytes(), run_dir)).hexdigest()
            for p in sorted(run_dir.rglob("*")) if p.is_file() and p.name not in skip}


def network_clean(run_dir: Path) -> bool:
    log = run_dir / "netguard.log"
    return not log.exists() or not log.read_text().strip()


def git_head() -> str:
    return subprocess.run(["git", "-C", str(CODE), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=False).stdout.strip()


def exit_codes(run_dir: Path) -> dict[str, int]:
    return {p.relative_to(run_dir / "steps").as_posix().removesuffix(".exit"): int(p.read_text())
            for p in sorted((run_dir / "steps").glob("*/*.exit"))}


def record(directory: Path) -> int:
    run_dir = directory / "run"
    outputs = run_all(run_dir)
    manifest = {**outputs, "input_commit": INPUT_COMMIT, "phase_clocks": PHASE_CLOCKS,
                "normalised_fields": list(NORMALISED_FIELDS),
                "normalised_text": [p.decode() for p, _ in NORMALISED_TEXT], "code_commit": git_head(),
                "exit_codes": exit_codes(run_dir)}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    clean = network_clean(run_dir)
    print(json.dumps({"recorded": str(directory), "files": len(outputs["changed"]), "network_clean": clean,
                      "code_commit": manifest["code_commit"],
                      "nonzero_exits": {k: v for k, v in manifest["exit_codes"].items() if v}}, indent=1))
    return 0 if clean else 1


def compare(directory: Path, max_diff_lines: int) -> int:
    golden = json.loads((directory / "manifest.json").read_text())
    fresh_dir = directory / "fresh"
    fresh = run_all(fresh_dir)
    differing = sorted(p for p in set(golden["changed"]) | set(fresh["changed"])
                       if golden["changed"].get(p) != fresh["changed"].get(p))
    deleted_mismatch = sorted(set(golden["deleted"]) ^ set(fresh["deleted"]))
    for path in differing[:20]:
        old, new = directory / "run" / path, fresh_dir / path
        state = ("missing in the fresh run" if not new.exists()
                 else "new in the fresh run" if not old.exists() else "differs")
        print(f"--- {path}: {state}")
        if old.exists() and new.exists() and not path.endswith(".png"):
            a = normalise(old.read_bytes(), directory / "run").decode(errors="replace").splitlines()
            b = normalise(new.read_bytes(), fresh_dir).decode(errors="replace").splitlines()
            for line in list(difflib.unified_diff(a, b, lineterm="", n=1))[:max_diff_lines]:
                print(line[:300])
    clean = network_clean(fresh_dir)
    identical = not differing and not deleted_mismatch and clean
    print(json.dumps({"identical": identical, "compared_files": len(golden["changed"]), "differing": differing,
                      "deleted_mismatch": deleted_mismatch, "network_clean": clean,
                      "golden_code_commit": golden.get("code_commit"), "fresh_code_commit": git_head()}, indent=1))
    return 0 if identical else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--dir", type=Path, default=DEFAULT_DIR)
        p.add_argument("--max-diff-lines", type=int, default=40)
    sub.add_parser("run").add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "run":
        run_all(args.out.resolve())
        return 0
    directory = args.dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return record(directory) if args.cmd == "record" else compare(directory, args.max_diff_lines)


if __name__ == "__main__":
    sys.exit(main())
