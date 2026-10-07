"""AI traders, EOD analyst and research director (docs/SPEC.md F4, F6; session B3). Research only: every prediction
and paper trade is a record, never an order. Run from the repo root:

    PYTHONPATH=scripts python -m marketbrief.traders <command> --market india|us ...

Pre-open (F4; one call per trader, in parallel):
  check                                  the registry and the agent files agree; which traders are switched on
  prepare  --strategy ID [--pack F]      work/traders/<ID>.md: the trader's only input (pack: work/context.md)
  validate --strategy ID FILE            gate the trader's file (JSON summary; exit 1 on any error)
  add      --strategy ID FILE --attempt N   store what passed; attempt 1 with errors stores nothing (exit 1),
                                         attempt 2 stores the valid predictions and abstentions for the rest;
                                         kill switch off -> `killed`, past the deadline -> `timeout` for everyone
Post-close (F6.1; settle first with session B2's engine: `python scripts/lab.py --market <m> settle`):
  eod-prepare [--session D]              work/eod_facts.json: the day's results and the trades to explain
  eod-validate FILE [--session D]        gate the analyst's file
  eod-add FILE [--session D] [--valid-only]   store reasons and the day's analysis
Weekly (F6.2):
  director-prepare                       work/research_inputs.json
  director-validate FILE                 gate the director's file (diffs must apply; nothing is applied)
  director-add FILE                      write reports/<market>/research-<week>.md and the research_reviews row"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from marketbrief.core import paths
from marketbrief.core.calendar import last_complete_session
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now
from marketbrief.core.database import connect
from marketbrief.traders import constants as c
from marketbrief.traders import director, director_facts, director_report, eod, eod_facts, eod_gate, outcome, prepare
from marketbrief.traders.inputs import InputsUnavailableError, load_inputs
from marketbrief.traders.registry import load_traders, trader, trader_problems
from marketbrief.traders.run import file_stamp, gate_lines, read_lines, timed_out

WORK = Path("work")


def parser():
    """The argument parser with every command."""
    root = market_arg(__doc__)
    sub = root.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    for name in ("prepare", "validate", "add"):
        one = sub.add_parser(name)
        one.add_argument("--strategy", required=True)
        if name == "prepare":
            one.add_argument("--pack", type=Path, default=WORK / "context.md")
        else:
            one.add_argument("file", type=Path)
        if name == "add":
            one.add_argument("--attempt", type=int, choices=(1, 2), required=True)
    for name in ("eod-prepare", "eod-validate", "eod-add"):
        one = sub.add_parser(name)
        one.add_argument("--session", help="the session date (default: the last completed session)")
        if name != "eod-prepare":
            one.add_argument("file", type=Path)
        if name == "eod-add":
            one.add_argument("--valid-only", action="store_true")
    sub.add_parser("director-prepare")
    for name in ("director-validate", "director-add"):
        sub.add_parser(name).add_argument("file", type=Path)
    return root


def emit(summary: dict, code: int = 0) -> int:
    """Print the JSON summary and return the exit code."""
    print(json.dumps(summary, indent=2, default=str))
    return code


def work_path(*parts: str) -> Path:
    """A path under the root's work/ folder, its parent created."""
    path = paths.ROOT.joinpath(WORK, *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def trader_command(args, cfg: dict) -> int:
    """prepare, validate, add of one trader."""
    one = trader(args.strategy)
    step = {"step": f"traders.{args.cmd}", "market": cfg["market"], "strategy_id": one.strategy_id, "now": utc_now()}
    try:
        gi = load_inputs(cfg, clock())
    except InputsUnavailableError as error:
        return emit({**step, "error": c.CODE_INPUTS, "detail": str(error)}, 2)
    if args.cmd == "prepare":
        pack = args.pack if args.pack.is_absolute() else paths.ROOT / args.pack
        text, summary = prepare.build(one, gi, pack.read_text(encoding="utf-8") if pack.exists() else "")
        out = work_path(c.WORK_DIR, f"{one.strategy_id}.md")
        out.write_text(text, encoding="utf-8")
        return emit({**step, "enabled": one.enabled, "input": str(out), "bytes": len(text.encode()), **summary,
                     "timed_out": timed_out(gi)})
    if args.cmd == "validate":
        if timed_out(gi):
            return emit({**step, "error": c.CODE_TIMEOUT, "detail": "past the deadline: run add, which abstains"}, 1)
        gated = gate_lines(read_lines(args.file), one, gi, file_stamp(args.file, gi))
        return emit({**step, "records": len(read_lines(args.file)), "valid": len(gated["rows"]),
                     "errors": gated["errors"], "warnings": gated["warnings"]}, 1 if gated["errors"] else 0)
    code, summary = outcome.add(one, gi, args.file, args.attempt)
    return emit({**step, **summary}, code)


def session_of(args, cfg: dict) -> date:
    """The --session date, else the last completed session by the run's clock."""
    return date.fromisoformat(args.session) if args.session else last_complete_session(cfg, clock())


def eod_command(args, cfg: dict) -> int:
    """eod-prepare, eod-validate, eod-add."""
    market, now = cfg["market"], clock()
    facts = eod_facts.eod_facts(connect(market), market, session_of(args, cfg), now)
    step = {"step": f"traders.{args.cmd}", "market": market, "session_date": facts["session_date"],
            "settled_trades": facts["settled_trades"], "items": len(facts["items"])}
    if args.cmd == "eod-prepare":
        out = work_path(c.EOD_FACTS_FILE)
        out.write_text(json.dumps(facts, indent=1, default=str) + "\n", encoding="utf-8")
        return emit({**step, "facts": str(out), "needs_agent": bool(facts["items"]) or (
            facts["settled_trades"] > 0 and not facts["summary_stored"])})
    good, summary, errors = eod_gate.validate(read_lines(args.file), facts)
    if args.cmd == "eod-validate" or (errors and not args.valid_only):
        return emit({**step, "valid": len(good), "errors": errors, "appended": 0}, 1 if errors else 0)
    written = eod.store(facts, good, summary, utc_now(), now.date())
    return emit({**step, "valid": len(good), "errors": errors, **written})


def director_command(args, cfg: dict) -> int:
    """director-prepare, director-validate, director-add."""
    market, now = cfg["market"], clock()
    con = connect(market)
    facts = director_facts.director_facts(con, market, last_complete_session(cfg, now), now)
    step = {"step": f"traders.{args.cmd}", "market": market, "iso_week": facts["iso_week"]}
    if args.cmd == "director-prepare":
        out = work_path("research_inputs.json")
        out.write_text(json.dumps(facts, indent=1, default=str) + "\n", encoding="utf-8")
        return emit({**step, "inputs": str(out), "citable_ids": len(director_facts.citable(facts))})
    try:
        review = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return emit({**step, "errors": [f"cannot read {args.file}: {error}"]}, 1)
    errors = director.validate(review, facts)
    stored = con.execute("SELECT count(*) FROM research_reviews WHERE id = ?", [facts["id"]]).fetchone()[0]
    if stored:
        errors.append(c.MSG_EOD_STORED.format(id=facts["id"]))
    if args.cmd == "director-validate" or errors:
        return emit({**step, "errors": errors}, 1 if errors else 0)
    return emit({**step, "errors": [], **director_report.store(facts, review, utc_now(), now.date())})


def main(argv: list[str] | None = None) -> int:
    """Run one command and print its JSON summary."""
    args = parser().parse_args(argv)
    cfg = require_market(args)
    if args.cmd == "check":
        traders = load_traders()
        problems = trader_problems()
        return emit({"step": "traders.check", "traders": {k: {"enabled": t.enabled, "model": t.agent_model,
                                                                "prompt_version": t.prompt_version,
                                                                "file": t.agent_file.name}
                                                            for k, t in traders.items()},
                     "problems": problems}, 1 if problems else 0)
    if args.cmd.startswith("eod-"):
        return eod_command(args, cfg)
    if args.cmd.startswith("director-"):
        return director_command(args, cfg)
    return trader_command(args, cfg)
