"""Collect stage: files, duplicates, price bars, fetch results and the collectors' summaries."""

from __future__ import annotations

import json
from datetime import date, timedelta
import pandas as pd
from marketbrief.utils.timefmt import as_utc_timestamp
from marketbrief.core import market_config, paths, schemas
from marketbrief.constants.validation import FETCH_COL, TRADING_DATE_KINDS
from marketbrief.pipeline.validate.gate_result import Result, work_dir
from marketbrief.pipeline.validate.row_checks import check_rows, read_rows, tickers_in, todays_files
from marketbrief.constants.validation import (
    MSG_BIG_ONE_DAY_MOVE_WITHOUT_ACTION,
    MSG_BENCHMARK_VOL_INDEX_NO_BARS_STORED,
    MSG_BAD_CLOSE_ON_RECENT_BAR,
    MSG_DUPLICATED_KEYS,
    MSG_COLLECTOR_FAILED,
    MSG_ZERO_ROWS_WITHOUT_REASON,
    MSG_IS_NOT_A_JSON_SUMMARY,
    MSG_LATE_RUN_SESSION_HAS_CLOSED_BUT,
    MSG_MARKET_SYMBOLS_WITH_NO_BARS_STORED,
    MSG_COLLECTOR_PROBLEM,
    MSG_COLLECTOR_FILE_PROBLEM,
    MSG_NEWEST_BAR_OLDER_THAN_THE_LAST,
    MSG_NO_ROWS_WRITTEN_TODAY_NO_COLLECTOR,
    MSG_NO_STORED_PRICE_BARS,
    MSG_PRICES_PRICE_BASIS_WARNING_S,
)


def check_files(res: Result, cfg: dict, kinds, today: date, now: pd.Timestamp, validate_config: dict) -> dict:
    """Empty, truncated or malformed files written today, and their rows against the schemas."""
    counts, tol = {}, timedelta(minutes=validate_config["future_tolerance_minutes"])
    for kind in kinds:
        files = todays_files(cfg["market"], kind, today)
        row_count = 0
        for path in files:
            rows, problems = read_rows(path)
            rel = path.relative_to(paths.ROOT).as_posix()
            if problems:
                res.block(
                    "BAD_FILE",
                    MSG_COLLECTOR_FILE_PROBLEM.format(rel=rel, value="; ".join(problems[:3])),
                    tickers_in(rows),
                )
            if kind in TRADING_DATE_KINDS:
                col = TRADING_DATE_KINDS[kind]
                rows = [row for row in rows if row.get(col) and str(row[col])[:10] == str(today)]
            row_count += len(rows)
            bad = check_rows(kind, rows, path.suffix == ".csv", now, tol)
            if bad:
                res.block("SCHEMA", MSG_COLLECTOR_FILE_PROBLEM.format(rel=rel, value="; ".join(bad)), tickers_in(rows))
        counts[kind] = row_count
    return counts


def check_duplicates(res: Result, _cfg: dict, con, validate_config: dict):
    keys = {kind: "id" for kind in validate_config["unique_id_kinds"]} | dict(validate_config.get("unique_keys") or {})
    for kind, key in keys.items():
        if kind not in schemas.SCHEMAS:
            continue
        rows = con.execute(
            f"SELECT {key}, count(*) FROM {kind} GROUP BY 1 HAVING count(*) > 1 ORDER BY 1 LIMIT 20"
        ).fetchall()
        if rows:
            res.block(
                "DUPLICATE_ID",
                MSG_DUPLICATED_KEYS.format(kind=kind, count=len(rows), key=key, value=[row[0] for row in rows[:5]]),
            )


def check_symbol_bars(res: Result, cfg: dict, last: dict, need: date, validate_config: dict) -> None:
    """Benchmark, vol index and the other market symbols: bars must exist and not be too old."""
    core = [key for role in ("benchmark", "vol_index") for key in market_config.symbols_by_role(cfg, role)]
    never = [key for key in core if key not in last]
    if never:
        res.block(
            "MISSING_SYMBOL",
            MSG_BENCHMARK_VOL_INDEX_NO_BARS_STORED,
            never,
        )
    bad_core = [key for key in core if key in last and last[key] < need]
    if bad_core:
        res.block(
            "STALE_SYMBOL",
            f"benchmark / vol index bar older than {need} (the regime needs them; newest "
            + ", ".join(f"{key} {last[key]}" for key in bad_core)
            + ")",
            bad_core,
        )
    old = need - timedelta(days=validate_config["symbol_max_age_days"])
    others = [key for key in cfg["symbols"] if key not in core]
    never = [key for key in others if key not in last]
    if never:
        res.warn(
            "MISSING_SYMBOL",
            MSG_MARKET_SYMBOLS_WITH_NO_BARS_STORED,
            never,
        )
    stale = [key for key in others if key in last and last[key] < old]
    if stale:
        res.warn(
            "STALE_SYMBOL",
            f"market symbols with no bar since {old} (cues, factors, sector ETFs; newest "
            + ", ".join(f"{key} {last[key]}" for key in stale)
            + ")",
            stale,
        )


def check_bars(res: Result, cfg: dict, con, run_status: dict, validate_config: dict):
    need = date.fromisoformat(run_status["previous_session"])
    last = dict(con.execute("SELECT ticker, max(date) FROM bars GROUP BY 1").fetchall())
    missing = [ticker for ticker in cfg["tickers"] if ticker not in last]
    stale = [ticker for ticker in cfg["tickers"] if ticker in last and last[ticker] < need]
    if missing:
        res.block("MISSING_BARS", MSG_NO_STORED_PRICE_BARS, missing)
    if stale:
        res.block(
            "STALE_BARS",
            MSG_NEWEST_BAR_OLDER_THAN_THE_LAST.format(need=need, value=stale[0], value_2=last[stale[0]]),
            stale,
        )
    if run_status["late_run"]:
        # the run started after session_date closed: its bar is not required (the routine works as
        # of the previous session), but a missing one is noted
        sess = date.fromisoformat(run_status["session_date"])
        no_bar = [ticker for ticker in cfg["tickers"] if ticker in last and last[ticker] < sess]
        if no_bar:
            res.warn(
                "LATE_RUN_NO_SESSION_BAR",
                MSG_LATE_RUN_SESSION_HAS_CLOSED_BUT.format(sess=sess),
                no_bar,
            )
    check_symbol_bars(res, cfg, last, need, validate_config)
    # close > 0 on recent bars; big 1-day moves
    since = need - timedelta(days=14)
    bad = con.execute(
        "SELECT DISTINCT ticker FROM prices WHERE date >= ? AND (close IS NULL OR close <= 0) ORDER BY 1", [since]
    ).fetchall()
    if bad:
        res.block("BAD_CLOSE", MSG_BAD_CLOSE_ON_RECENT_BAR.format(since=since), [bad_move[0] for bad_move in bad])
    moves = con.execute(
        "SELECT DISTINCT ON (ticker) ticker, date, ret_1d FROM returns ORDER BY ticker, date DESC"
    ).fetchall()
    for ticker, day, row in moves:
        if ticker not in cfg["tickers"] or row is None or abs(row) <= validate_config["big_move_1d"]:
            continue
        if not corporate_action_near(con, ticker, day, validate_config):
            res.warn(
                "BIG_MOVE",
                MSG_BIG_ONE_DAY_MOVE_WITHOUT_ACTION.format(ticker=ticker, row=row, day=day),
                [ticker],
            )


def corporate_action_near(con, ticker: str, day: date, validate_config: dict) -> bool:
    window_start, window_end = (
        day - timedelta(days=validate_config["big_move_event_days"]),
        day + timedelta(days=validate_config["big_move_event_days"]),
    )
    words = [word.lower() for word in validate_config["big_move_event_words"]]
    texts = [
        " ".join(str(item) for item in event_row)
        for event_row in con.execute(
            "SELECT type, name FROM events WHERE ticker = ? AND date BETWEEN ? AND ?",
            [ticker, window_start, window_end],
        ).fetchall()
    ]
    texts += [
        " ".join(str(item) for item in event_row)
        for event_row in con.execute(
            "SELECT category, subject FROM announcements WHERE ticker = ? AND CAST(published_at AS DATE) BETWEEN ? "
            "AND ?",
            [ticker, window_start, window_end],
        ).fetchall()
    ]
    return any(word in text.lower() for text in texts for word in words)


def fetch_kinds(cfg: dict) -> list[str]:
    kinds = ["quotes", "news"]
    if cfg.get("filings") == "sec":
        kinds.append("filings")
    if cfg["market"] == "india":
        kinds.append("announcements")
    return kinds


def check_fetches(res: Result, cfg: dict, con, now: pd.Timestamp, today: date, validate_config: dict):
    for kind in fetch_kinds(cfg):
        col = FETCH_COL[kind]
        newest = con.execute(f"SELECT max({col}) FROM {kind}").fetchone()[0]
        limit = validate_config["fetch_max_age_hours"][kind]
        newest_time = as_utc_timestamp(newest)
        if newest_time is None:
            res.add(validate_config["fetch_severity"], "NOT_FETCHED", f"{kind}: no stored rows at all")
        elif newest_time.date() != today or now - newest_time > pd.Timedelta(hours=limit):
            res.add(
                validate_config["fetch_severity"],
                "NOT_FETCHED",
                f"{kind}: newest {col} {newest_time.isoformat()} is not from this run (today {today}, max age "
                f"{limit} h)",
            )


def check_summaries(res: Result, cfg: dict, counts: dict, validate_config: dict) -> dict:
    """Collector summaries saved by the routine (work/steps/<collector>.json); without them, today's
    row counts per kind stand in."""
    seen = {}
    steps = work_dir() / "steps"
    for summary_path in sorted(steps.glob("collect_*.json")) if steps.exists() else []:
        try:
            collector_summary = json.loads(summary_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            res.warn("COLLECTOR_SUMMARY", MSG_IS_NOT_A_JSON_SUMMARY.format(name=summary_path.name, error=e))
            continue
        name = collector_summary.get("collector") or summary_path.stem.removeprefix("collect_")
        seen[name] = collector_summary
        if collector_summary.get("market") not in (None, cfg["market"]):
            continue
        if collector_summary.get("error"):
            res.warn(
                "COLLECTOR_ERROR", MSG_COLLECTOR_PROBLEM.format(name=name, value=str(collector_summary["error"])[:200])
            )
        failed = collector_summary.get("failed")
        if failed:
            what = [
                failure.get("symbol")
                or failure.get("feed")
                or failure.get("ticker")
                or failure.get("series")
                or str(failure)[:60]
                if isinstance(failure, dict)
                else str(failure)
                for failure in (failed if isinstance(failed, list) else [failed])
            ]
            res.warn(
                "COLLECTOR_FAILED",
                MSG_COLLECTOR_FAILED.format(name=name, count=len(what), value=what[:10]),
                [warning for warning in what if warning in cfg["tickers"]],
            )
        if name == "prices" and collector_summary.get(
            "warnings"
        ):  # split/bonus checks (issue #31): basis left unconfirmed
            warning_texts = [str(warning) for warning in collector_summary["warnings"]]
            res.warn(
                "PRICE_BASIS",
                MSG_PRICES_PRICE_BASIS_WARNING_S.format(
                    count=len(warning_texts), value="; ".join(warning_texts[:5])[:600]
                ),
                [warning.split(":", 1)[0] for warning in warning_texts if warning.split(":", 1)[0] in cfg["tickers"]],
            )
        key = (validate_config.get("expect_output") or {}).get(name)
        explained = (
            collector_summary.get("failed")
            or collector_summary.get("warnings")
            or collector_summary.get("error")
            or collector_summary.get("skipped")
        )
        if key and collector_summary.get(key) == 0 and not explained:
            res.warn("EMPTY_OUTPUT", MSG_ZERO_ROWS_WITHOUT_REASON.format(name=name, key=key))
    if not seen:
        for kind in validate_config.get("expect_output") or {}:
            if counts.get(kind, 0) == 0 and kind in counts:
                res.warn("EMPTY_OUTPUT", MSG_NO_ROWS_WRITTEN_TODAY_NO_COLLECTOR.format(kind=kind))
    return {"summaries": sorted(seen), "rows_today": counts}
