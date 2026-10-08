"""Deterministic gates for the daily run (routine/PROMPT.md; settings in config/validate.yaml).

    python scripts/validate.py --market M --stage collect|news_collect|news|features|context|forecast|report|all

Prints one JSON summary: `ok`, `failures` and `warnings` (each with `code`, `detail` and the affected `tickers`), plus
`info`. Exit 1 when any blocking failure is found, else 0.

Stages (each runs after the routine step of the same name):
- collect:  freshness of watchlist bars against the exchange calendar (the last completed session,
            market_status.py's `previous_session`; on a late run today's bar may still be missing),
            market symbols, and this run's fetches (quotes, news, filings, announcements); collector
            summaries saved in work/steps/ (or today's row counts); empty, truncated or malformed
            files written today; row schemas (marketbrief.core.schemas.SCHEMAS); ISO UTC timestamps not in the
            future; duplicate ids; close > 0; big 1-day moves; news only from configured outlets;
            today's news_articles rows (a warning: nothing reads them yet): known access, no stored
            article text (<= 3 sentences of <= 40 words), pages read only from allowlisted https URLs.
- news:     work/enriched.jsonl (news-analyst output) before it is appended.
- features: every watchlist ticker has a feature row for its latest bar and a regime row exists.
- context:  work/context.md exists, is the pack of today and names every watchlist ticker.
- forecast: work/predictions.jsonl before it is appended (prediction_rules.check_prediction,
            evidence published before made_at, no calls on a late or mid-session run, and each cited
            id's news verification status as of made_at: NEWS_STATUS_* codes; forecast_gate.py).
- report:   files appended since collect (news_enriched, predictions, ranges) as in collect; no
            AGENT markers left; each number in the agent-written lines of the report, the Slack
            draft and today's daily summary matches a source number of the same kind and scope
            (narrative_numbers.py: the companies or symbols its sentence names plus market-level
            rows, and the text of the news ids it cites); every ticker x horizon has a range or
            a skip reason the calendar explains.
- all:      every stage whose input exists.
- news_collect (not part of `all`): the news-only light run (routine/NEWS_PROMPT.md): files and rows of the
            news kinds written today, their duplicate ids, this run's news_runs row (from today, recent, ok),
            the collectors' summaries in work/steps/, news sources and article rows; no price or calendar check."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from marketbrief.constants.validation import MSG_REPORT_SKIPPED_NOT_WRITTEN, STAGE_NEWS_COLLECT, STAGES
from marketbrief.core import cli, clock, database
from marketbrief.pipeline.validate.gate_result import Result, load_config, run_status
from marketbrief.pipeline.validate.news_checks import stage_news
from marketbrief.pipeline.validate.report_checks import report_file, stage_report
from marketbrief.pipeline.validate.stages import (
    stage_collect,
    stage_context,
    stage_features,
    stage_forecast,
    stage_news_collect,
)


def run(cfg: dict, stage: str, paths: dict | None = None) -> dict:
    """Run the chosen stage (or all) of the gate for one market and return the verdict as a dict."""
    paths = paths or {}
    validate_config = load_config()
    con = database.connect(cfg["market"])
    now, today = pd.Timestamp(clock.clock()), clock.utc_today()
    status = run_status(cfg)
    res = Result()
    res.info["run"] = {
        key: status[key] for key in ("session_date", "previous_session", "late_run", "in_session", "trading_day")
    }
    stages = STAGES if stage == "all" else (stage,)
    for stage_name in stages:
        if stage_name == STAGE_NEWS_COLLECT:
            stage_news_collect(res, cfg, con, status, now, today, validate_config)
        elif stage_name == "collect":
            stage_collect(res, cfg, con, status, now, today, validate_config)
        elif stage_name == "news":
            stage_news(res, cfg, con, status, now, today, validate_config, paths.get("enriched"))
        elif stage_name == "features":
            stage_features(res, cfg, con, status, now, today, validate_config)
        elif stage_name == "context":
            stage_context(res, cfg, con, status, now, today, validate_config, paths.get("context"))
        elif stage_name == "forecast":
            stage_forecast(res, cfg, con, status, now, today, validate_config, paths.get("predictions"))
        elif stage_name == "report":
            report_path = paths.get("report") or report_file(cfg, con, status)
            if stage == "all" and not report_path.exists():
                res.info["report"] = MSG_REPORT_SKIPPED_NOT_WRITTEN.format(name=report_path.name)
                continue
            stage_report(res, cfg, con, status, now, today, validate_config, report_path, paths.get("slack"))
    return {
        "step": "validate",
        "market": cfg["market"],
        "stage": stage,
        "checked_at": now.isoformat(),
        "ok": not res.failures,
        "failures": res.failures,
        "warnings": res.warnings,
        "info": res.info,
    }


def main() -> int:
    """Parse the arguments, run the gate and print its JSON; the exit code is 1 on any failure."""
    parser = cli.market_arg(__doc__)
    parser.add_argument("--stage", required=True, choices=[*STAGES, STAGE_NEWS_COLLECT, "all"])
    for name in ("predictions", "enriched", "context", "report", "slack"):
        parser.add_argument(f"--{name}", type=Path, help=f"path of the {name} file (default: the routine's)")
    args = parser.parse_args()
    cfg = cli.require_market(args)
    out = run(
        cfg,
        args.stage,
        {
            key: getattr(args, key)
            for key in ("predictions", "enriched", "context", "report", "slack")
            if getattr(args, key)
        },
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1
