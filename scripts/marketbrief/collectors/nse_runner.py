"""Shared plumbing of the NSE collectors (relations_india and nse_india): argument parsing, the market check, the
replay guard, one NSE session, storing new rows and the JSON summary.

NSE serves its JSON only to browser-like clients: one session per run loads the home page for its cookies, then
calls /api/... with a Referer, pausing between requests (marketbrief/sources/nse_client.py). The environment must
allow www.nseindia.com and nsearchives.nseindia.com. `--replay DIR` reads responses from local files instead of the
network; replayed rows can be synthetic, so replay only writes to an explicit scratch root (nse_replay_guard.py)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from marketbrief.collectors.collector_store import Problems, summary
from marketbrief.collectors.nse_replay_guard import replay_problem, write_target
from marketbrief.constants.columns import COL_ID
from marketbrief.constants.config_keys import (CFG_MARKET, CFG_RELATIONS, REL_ARCHIVES, REL_BASE, REL_PAUSE_SECONDS,
                                               REL_SOURCE, REL_SOURCE_NSE)
from marketbrief.constants.nse_collection import (EXIT_REPLAY_REFUSED, MSG_ENDPOINT_EMPTY, MSG_ONLY_HELP,
                                                  MSG_REPLAY_HELP, MSG_REPLAY_REFUSED, MSG_ROWS_FOR_WATCHLIST,
                                                  MSG_ROWS_RETURNED, MSG_SINCE_HELP, MSG_SKIPPED_NO_NSE,
                                                  MSG_TODAY_HELP, MSG_TODAY_NEEDS_REPLAY, SEEN_LOOKBACK_DAYS,
                                                  SINCE_WINDOW_DAYS)
from marketbrief.constants.sources import NSE_ARCHIVES_URL, NSE_BASE_URL, NSE_DEFAULT_PAUSE_SECONDS
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_MARKET, SUMMARY_NEW, SUMMARY_SKIPPED
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.sources.nse_client import Nse


@dataclass
class NseRun:
    """What every kind's collection step needs: the NSE session, the NSE symbol -> ticker map, the collection date
    and time, the market and the problems list of the run."""
    nse: Nse
    symbols: dict[str, str]
    today: date
    now: str
    market: str
    problems: Problems


def store(market: str, kind: str, rows: list[dict], today: date, seen_days: int = SEEN_LOOKBACK_DAYS) -> int:
    """Append rows whose id is new (append-only, de-duplicated against recent files)."""
    seen = recent_ids(market, kind, days=seen_days)
    fresh = {row[COL_ID]: row for row in rows if row[COL_ID] not in seen}
    return append_jsonl(day_file(market, kind, today), fresh.values())


def date_windows(start: date, end: date, days: int = SINCE_WINDOW_DAYS) -> list[tuple[date, date]]:
    """Consecutive [from, to] windows of at most `days` days covering start..end (inclusive)."""
    windows, window_start = [], start
    while window_start <= end:
        window_end = min(end, window_start + timedelta(days=days - 1))
        windows.append((window_start, window_end))
        window_start = window_end + timedelta(days=1)
    return windows


def since_arg(parser) -> None:
    """Add the --since option (backfill from a date in one-week windows)."""
    parser.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD", help=MSG_SINCE_HELP)


def coverage(source: str, total: int, matched: int | None, problems: Problems) -> None:
    """Say how many rows an endpoint returned market-wide and how many were for the watchlist,
    so an endpoint that returns nothing at all (blocked, retired or changed) is never mistaken
    for a quiet period with nothing for our tickers."""
    if total == 0:
        problems.warnings.append(MSG_ENDPOINT_EMPTY.format(source=source))
    else:
        problems.notes.append(MSG_ROWS_RETURNED.format(source=source, total=total)
                              + ("" if matched is None else MSG_ROWS_FOR_WATCHLIST.format(matched=matched)))


def open_nse(cfg: dict, replay: Path | None) -> Nse:
    """The run's NSE client: from the replay folder, or the network paced as the market config says."""
    relations = cfg.get(CFG_RELATIONS) or {}
    return Nse(relations.get(REL_BASE, NSE_BASE_URL), relations.get(REL_ARCHIVES, NSE_ARCHIVES_URL), replay,
               pause=0 if replay else float(relations.get(REL_PAUSE_SECONDS, NSE_DEFAULT_PAUSE_SECONDS)))


def collector_main(doc: str, name: str, kinds: list[str], collect, extra_args=None) -> int:
    """Argument parsing, market check, replay guard, one NSE session, JSON summary.
    `collect(cfg, nse, kinds, today, args) -> summary`."""
    parser = market_arg(doc)
    parser.add_argument("--replay", type=Path, help=MSG_REPLAY_HELP)
    parser.add_argument("--only", choices=kinds, action="append", help=MSG_ONLY_HELP)
    parser.add_argument("--today", type=date.fromisoformat, help=MSG_TODAY_HELP)
    if extra_args:
        extra_args(parser)
    args = parser.parse_args()
    cfg = require_market(args)
    market = cfg[CFG_MARKET]
    if (cfg.get(CFG_RELATIONS) or {}).get(REL_SOURCE) != REL_SOURCE_NSE:
        print(json.dumps({SUMMARY_COLLECTOR: name, SUMMARY_MARKET: market, SUMMARY_SKIPPED: MSG_SKIPPED_NO_NSE}))
        return 0
    if args.today and not args.replay:
        raise SystemExit(MSG_TODAY_NEEDS_REPLAY)
    only, today = args.only or kinds, args.today or utc_today()
    if args.replay:
        problem = replay_problem(paths.ROOT, [write_target(market, kind, today) for kind in only])
        if problem:
            print(json.dumps({SUMMARY_COLLECTOR: name, SUMMARY_MARKET: market,
                              "error": MSG_REPLAY_REFUSED.format(problem=problem)}))
            return EXIT_REPLAY_REFUSED
    result = collect(cfg, open_nse(cfg, args.replay), only, today, args)
    print(json.dumps(result, indent=2))
    return 1 if all(v is None for v in result[SUMMARY_NEW].values()) else 0


def run_summary(name: str, run: NseRun, new: dict) -> dict:
    """The JSON summary of an NSE collector run."""
    return summary(name, run.market, new, run.problems, run.nse)
