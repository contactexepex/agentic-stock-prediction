#!/usr/bin/env python3
"""Golden outputs for the refactor: run the deterministic pipeline on a pinned copy of the data and
compare every output byte for byte with a recorded run (docs/REFACTOR_PLAN.md, "Golden outputs").

  python tests/golden/golden.py record  [--dir work/golden]   record the golden set from this checkout
  python tests/golden/golden.py compare [--dir work/golden]   rerun into DIR/fresh and diff against DIR/run
  python tests/golden/golden.py run --out DIR                 one run into DIR, no comparison

Inputs are fixed: data/, config/ and reports/ come from git commit INPUT_COMMIT (never the working
tree, so daily-run appends do not change them), plus a synthetic overlay built by rules in this file
(stored calls of REVIEW_WEEK, a forecaster file with one call that breaks the rules, lessons, and a
filled report). Every script runs as a subprocess on that scratch root with MB_ROOT, MB_CONFIG,
MB_MARKET and a fixed MB_NOW per phase, PYTHONHASHSEED=0, TZ=UTC and the test network guard on
(tests/netguard), so nothing reaches the network. The code under test (scripts/, sql/, templates/) is
this checkout's.

Two phases per market, each with its own frozen clock (PHASE_CLOCKS):
- pre_open: the morning of 2026-10-05, when the stored bars are current: the normal path (fresh
  bars, 1d and 5d ranges published, report, HTML, Slack dry run);
- late: the morning of 2026-10-06, after every stored input was collected: news visible, bars a
  session behind (validate failures), late ranges, forecaster gate, lessons, review, spot-check,
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
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import date, timedelta
from pathlib import Path

import yaml

CODE = Path(__file__).resolve().parents[2]
SCRIPTS = CODE / "scripts"
NETGUARD = CODE / "tests" / "netguard"
GOLDEN_SITE = CODE / "tests" / "golden" / "site"
INPUT_COMMIT = "24749bdc4835bff242b2683f83e85f2a7e3a2ab0"
INPUT_PATHS = ("data", "config", "reports")
DEFAULT_DIR = CODE / "work" / "golden"
MARKETS = ("india", "us")

PHASE_CLOCKS = {
    "india": {"pre_open": "2026-10-05T02:40:00+00:00", "late": "2026-10-06T02:30:00+00:00"},
    "us": {"pre_open": "2026-10-05T12:15:00+00:00", "late": "2026-10-06T12:15:00+00:00"},
}
MID_SESSION_CHECK = "2026-10-05T15:00:00+00:00"
PAST_CALL_DATES = [date(2026, 9, 21) + timedelta(days=i) for i in range(5)]
PAST_CALL_HOUR_UTC = {"india": "11:00:00", "us": "21:00:00"}
PAST_CALL_TICKERS = 3
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


# ---------- synthetic inputs ----------

def git_inputs(dest: Path) -> None:
    """Extract INPUT_PATHS at INPUT_COMMIT into dest."""
    blob = subprocess.run(["git", "-C", str(CODE), "archive", "--format=tar", INPUT_COMMIT, *INPUT_PATHS],
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(dest, filter="data")


def watchlist_head(root: Path, market: str) -> list[str]:
    """The first PAST_CALL_TICKERS tickers of the market config (file order)."""
    cfg = yaml.safe_load((root / "config" / "markets" / f"{market}.yaml").read_text())
    return list(cfg["tickers"])[:PAST_CALL_TICKERS]


def first_news_ids(root: Path, market: str, tickers: list[str]) -> dict[str, str]:
    """Ticker -> id of the first stored news row tagged with it (file order)."""
    found: dict[str, str] = {}
    for path in sorted((root / "data" / market / "news").glob("**/*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            for ticker in row.get("tickers") or []:
                if ticker in tickers and ticker not in found:
                    found[ticker] = row["id"]
    return found


def latest_bar_date(root: Path, market: str, ticker: str) -> str:
    """The newest stored price date of a ticker (the forecaster's as_of_date)."""
    for path in sorted((root / "data" / market / "prices").glob("**/*.csv"), reverse=True):
        if any(line.split(",")[1] == ticker for line in path.read_text().splitlines()[1:]):
            return path.stem
    raise SystemExit(f"no bars for {ticker}")


def write_past_calls(root: Path, market: str) -> None:
    """Stored calls of REVIEW_WEEK: each watchlist-head ticker, both horizons, every day, after the close."""
    tickers = watchlist_head(root, market)
    for day_index, as_of in enumerate(PAST_CALL_DATES):
        calls = [{"id": f"{as_of}-{ticker}-{horizon}d", "made_at": f"{as_of}T{PAST_CALL_HOUR_UTC[market]}+00:00",
                  "as_of_date": str(as_of), "ticker": ticker, "horizon_days": horizon,
                  "direction": "up" if (day_index + ticker_index + horizon) % 2 else "down",
                  "confidence": [0.55, 0.6, 0.65, 0.7][(day_index + ticker_index) % 4],
                  "rationale": "golden synthetic call", "evidence_ids": ["golden-evidence"],
                  "prompt_version": "golden", "range_widen": 0.0}
                 for ticker_index, ticker in enumerate(tickers) for horizon in (1, 5)]
        path = root / "data" / market / "predictions" / f"{as_of:%Y}" / f"{as_of:%m}" / f"{as_of}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(call) + "\n" for call in calls))


def write_forecaster_file(root: Path, market: str, clock: str) -> None:
    """Today's forecaster output (work/predictions.jsonl): one 5d call per watchlist-head ticker with
    news, plus one call that breaks the rules (confidence 0.95, unknown evidence id)."""
    tickers = watchlist_head(root, market)
    news = first_news_ids(root, market, tickers)

    def call(ticker: str, horizon: int, direction: str, confidence: float, evidence_id: str, widen: float) -> dict:
        as_of = latest_bar_date(root, market, ticker)
        return {"id": f"{as_of}-{ticker}-{horizon}d", "made_at": clock, "as_of_date": as_of, "ticker": ticker,
                "horizon_days": horizon, "direction": direction, "confidence": confidence,
                "rationale": "golden forecaster call", "evidence_ids": [evidence_id], "prompt_version": "golden",
                "range_widen": widen}
    calls = [call(t, 5, "up" if i % 2 else "down", 0.6, news[t], 0.1) for i, t in enumerate(tickers) if t in news]
    calls.append(call(tickers[-1], 1, "up", 0.95, "missing-id", 0.0))
    (root / "work").mkdir(parents=True, exist_ok=True)
    (root / "work" / "predictions.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))


def append_valid_calls(root: Path, market: str, clock: str) -> None:
    """The routine's step 9: drop the calls validate --stage forecast failed, append the rest."""
    summary = json.loads(step_log(root, market, "validate_forecast", "stdout").read_text())
    failed_ids = {m.group(1) for failure in summary.get("failures", [])
                  for m in re.finditer(r"line \d+ \((\S+)\)", failure["detail"])}
    if any(f["code"] == "CALLS_NOT_ALLOWED" for f in summary.get("failures", [])):
        failed_ids = {"*"}
    work_file = root / "work" / "predictions.jsonl"
    calls = [json.loads(line) for line in work_file.read_text().splitlines() if line.strip()]
    kept = [c for c in calls if "*" not in failed_ids and c["id"] not in failed_ids]
    path = root / "data" / market / "predictions" / clock[:4] / clock[5:7] / f"{clock[:10]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.writelines(json.dumps(c) + "\n" for c in kept)
    work_file.unlink()


def write_lessons(root: Path, _market: str, _clock: str) -> None:
    """The reflector's stand-in: one number-free lesson per prepared fact."""
    facts = root / "work" / "lesson_facts.jsonl"
    rows = [json.loads(line) for line in facts.read_text().splitlines() if line.strip()] if facts.exists() else []
    lessons = [{"prediction_id": f["prediction_id"], "lesson": "Golden lesson: weigh the regime before the headline.",
                "prompt_version": "golden"} for f in rows]
    (root / "work" / "lessons.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lessons))


def fill_report(root: Path, market: str, _clock: str) -> None:
    """Replace each AGENT marker of the report and the Slack draft with a fixed number-free sentence."""
    report_step = json.loads(step_log(root, market, "report", "stdout").read_text())
    path = root / report_step["report"]

    def sentence(match: re.Match) -> str:
        name = match.group(1).split(" ")[0]
        if name == "top3":
            return "- Golden point one.\n- Golden point two.\n- Golden point three."
        return f"Golden narrative for {name}."
    path.write_text(re.sub(r"<!-- AGENT:([^>]*?) -->", sentence, path.read_text()))
    slack = root / "work" / f"slack_{market}.md"
    lines = [line for line in slack.read_text().splitlines() if "AGENT:failures" not in line]
    slack.write_text("\n".join(re.sub(r"<!-- AGENT:top3[^>]*-->", "• Golden one.\n• Golden two.\n• Golden three.", line)
                               for line in lines) + "\n")


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


def step_log(root: Path, market: str, label: str, stream: str) -> Path:
    """The log file of a step of the current phase (GOLDEN_PHASE)."""
    return root.parent / "steps" / market / f"{os.environ['GOLDEN_PHASE']}.{label}.{stream}"


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
