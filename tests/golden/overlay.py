"""Synthetic inputs of the golden run (tests/golden/golden.py): the pinned data, stored calls of the
review week, the forecaster's file and its gate, the reflector's lessons and the filled report.
Every value follows a fixed rule, so two runs build the same bytes."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tarfile
from datetime import date, timedelta
from pathlib import Path

import yaml

CODE = Path(__file__).resolve().parents[2]
INPUT_COMMIT = "24749bdc4835bff242b2683f83e85f2a7e3a2ab0"
INPUT_PATHS = ("data", "config", "reports")
PAST_CALL_DATES = [date(2026, 9, 21) + timedelta(days=i) for i in range(5)]
PAST_CALL_HOUR_UTC = {"india": "11:00:00", "us": "21:00:00"}
PAST_CALL_TICKERS = 3


def step_log(root: Path, market: str, label: str, stream: str) -> Path:
    """The log file of a step of the current phase (GOLDEN_PHASE)."""
    return root.parent / "steps" / market / f"{os.environ['GOLDEN_PHASE']}.{label}.{stream}"


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


def first_primary_ids(root: Path, market: str, tickers: list[str], clock: str) -> dict[str, str]:
    """Ticker -> id of the first stored SEC filing or NSE announcement of it (file order) public by
    clock: a primary source, which news verification counts as confirmed_primary evidence."""
    found: dict[str, str] = {}
    for kind, column in (("filings", "accepted_at"), ("announcements", "published_at")):
        for path in sorted((root / "data" / market / kind).glob("**/*.jsonl")):
            for line in path.read_text().splitlines():
                row = json.loads(line)
                public = row.get(column) or row.get("first_seen_at") or ""
                if row.get("ticker") in tickers and row["ticker"] not in found and public[:19] <= clock[:19]:
                    found[row["ticker"]] = row["id"]
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
    news, citing the ticker's first stored primary source (filing or announcement) first when it has one
    (news verification: the main evidence must be confirmed_primary or corroborated), plus one call that
    breaks the rules (confidence 0.95, unknown evidence id)."""
    tickers = watchlist_head(root, market)
    news, primary = first_news_ids(root, market, tickers), first_primary_ids(root, market, tickers, clock)

    def call(ticker: str, horizon: int, direction: str, confidence: float, evidence: list[str], widen: float) -> dict:
        as_of = latest_bar_date(root, market, ticker)
        return {"id": f"{as_of}-{ticker}-{horizon}d", "made_at": clock, "as_of_date": as_of, "ticker": ticker,
                "horizon_days": horizon, "direction": direction, "confidence": confidence,
                "rationale": "golden forecaster call", "evidence_ids": evidence, "prompt_version": "golden",
                "range_widen": widen}
    calls = [call(t, 5, "up" if i % 2 else "down", 0.6, [*([primary[t]] if t in primary else []), news[t]], 0.1)
             for i, t in enumerate(tickers) if t in news]
    calls.append(call(tickers[-1], 1, "up", 0.95, ["missing-id"], 0.0))
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
