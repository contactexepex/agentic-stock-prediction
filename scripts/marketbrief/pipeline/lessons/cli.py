"""Reflection log: one short lesson per settled call, read by later forecasts.

Pattern adapted from TauricResearch/TradingAgents (Apache-2.0; tradingagents/memory/reflection.py and settlement.py):
settle past decisions against realised outcomes, write a one-paragraph lesson, and let later decisions read the same
ticker's recent lessons plus recent ones market-wide, only those already known at the decision time. Here the facts
are deterministic (this script) and only the paragraph is written by an agent (`.claude/agents/reflector.md`), checked
by `validate`.

  prepare  [--max N] [--out F]   settled calls without a lesson -> F (default work/lesson_facts.jsonl):
                                 the call (direction, confidence, rationale, evidence ids and what they
                                 said), the outcome (return, hit) and its published range (position of
                                 the close vs the 50%/80% bands). A call whose range is still open
                                 (not late, not yet scored) waits for it.
  validate F                     checks the reflector's records (JSON summary; exit 1 on any error)
  add F                          validate, then append the full records to data/<market>/lessons/
                                 (all or nothing; a lesson id already stored is refused)

The reflector writes one JSON object per lesson: {"prediction_id", "lesson", "prompt_version"}, optionally with copied
fact fields, each of which must equal the stored value. `validate` checks: the prediction id exists and is settled (an
outcome is stored); no lesson for it is stored or repeated in the file; the lesson is 1-60 words; every number in its
text matches the call or its outcome (with a % sign: the return, the close's % distance from a band edge, confidence
in %; without: closes, band edges, confidence, the horizon; either way: the 50/80 band names and numbers already in
the stored rationale; dates and ids are skipped), and a signed return has the right sign. `add` stores the facts
recomputed from data/ (never the agent's copy) plus the text.

Availability: `settled_at` = the outcome's scored_at; `available_from` = the latest scored_at of the facts the lesson
cites (the outcome, and the range outcome when a range is cited). The context pack (context.py) shows a lesson only
once available_from <= its clock (MB_NOW-aware), so a lesson never reveals an outcome unknown at made_at."""

from __future__ import annotations

import json
from pathlib import Path

from marketbrief.constants.lessons import DEFAULT_MAX
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.pipeline.lessons.facts import evidence, settled, stored_ids
from marketbrief.pipeline.lessons.validation import check


def main() -> int:
    """Run `prepare`, `validate` or `add` of the reflection log and print the JSON summary."""
    parser = market_arg(__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    prepare_parser = sub.add_parser("prepare", help="write the facts of settled calls without a lesson")
    prepare_parser.add_argument("--max", type=int, default=DEFAULT_MAX, help="at most N calls, newest settled first")
    prepare_parser.add_argument("--out", type=Path, default=paths.ROOT / "work" / "lesson_facts.jsonl")
    for name in ("validate", "add"):
        file_parser = sub.add_parser(name)
        file_parser.add_argument("file", type=Path)
    args = parser.parse_args()
    cfg = require_market(args)
    market = cfg["market"]
    if args.cmd == "prepare":
        con = connect(market)
        facts, done = settled(cfg, con), stored_ids(con)
        todo = [fact for pid, fact in facts.items() if fact is not None and f"lesson-{pid}" not in done]
        waiting = sorted(pid for pid, fact in facts.items() if fact is None and f"lesson-{pid}" not in done)
        todo.sort(key=lambda fact: (fact["settled_at"], fact["prediction_id"]), reverse=True)
        todo = todo[: args.max]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "".join(
                json.dumps({**fact, "evidence": evidence(con, fact["evidence_ids"])}, default=str) + "\n"
                for fact in todo
            ),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "step": "lessons.prepare",
                    "market": market,
                    "facts": str(args.out),
                    "n": len(todo),
                    "waiting_for_range": waiting,
                    "already_stored": len(done),
                    "now": utc_now(),
                },
                indent=2,
            )
        )
        return 0
    good, bad, record_count = check(cfg, args.file)
    if args.cmd == "validate" or bad:
        print(
            json.dumps(
                {
                    "step": f"lessons.{args.cmd}",
                    "market": market,
                    "file": str(args.file),
                    "records": record_count,
                    "valid": len(good),
                    "errors": bad,
                    "appended": 0,
                },
                indent=2,
                default=str,
            )
        )
        return 1 if bad else 0
    now = utc_now()
    rows = [{**valid_record, "written_at": now} for valid_record in good]
    path = day_file(market, "lessons", utc_today())
    append_jsonl(path, rows)
    print(
        json.dumps(
            {
                "step": "lessons.add",
                "market": market,
                "file": str(args.file),
                "records": record_count,
                "valid": len(good),
                "errors": [],
                "appended": len(rows),
                "to": str(path),
            },
            indent=2,
        )
    )
    return 0
