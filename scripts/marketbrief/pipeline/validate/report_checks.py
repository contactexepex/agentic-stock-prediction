"""Report stage: numbers in the narrative against the data pool, ranges and the report files."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import narrative_numbers
from marketbrief.core.settings import load_settings
from marketbrief.core import calendar, database, market_config, paths
from marketbrief.constants.validation import FETCH_COL
from marketbrief.pipeline.validate.collect_checks import check_files
from marketbrief.pipeline.validate.gate_result import Result, work_dir


def records(con, sql: str, params=(), notes: list | None = None) -> list[dict]:
    """Rows of a source query; a failure (e.g. a view a market does not have) is noted, not raised."""
    try:
        return con.execute(sql, list(params)).df().to_dict("records")
    except Exception as e:  # noqa: BLE001 - noted in info.number_sources
        if notes is not None:
            notes.append(f"source query skipped ({type(e).__name__}: {str(e).splitlines()[0][:120]}): {sql[:80]}")
        return []


def build_pool(cfg: dict, con, validate_config: dict, today: date, texts: list[str]) -> narrative_numbers.Pool:
    """The numbers the narrative may quote, by kind and scope (see narrative_numbers.py): the
    script-written texts (context pack, skeletons) line by line, stored rows per ticker or symbol
    (newest features, the newest ranges, quotes of the last 3 days, returns of the last 10 days),
    market-level rows (regime, row counts), collector summaries, and the text of recent news,
    filings and announcements under their own ids."""
    pool = narrative_numbers.Pool(narrative_numbers.Entities(cfg))
    notes = pool.notes
    for ticker_name in texts:
        pool.add_text(ticker_name, pct_sections=True)
    pool.add_rows(
        records(
            con,
            "SELECT DISTINCT ON (ticker) * EXCLUDE (warnings) FROM features_latest ORDER BY ticker, as_of_date DESC",
            notes=notes,
        ),
        "ticker",
    )
    pool.add_rows(records(con, "SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1", notes=notes), None)
    pool.add_rows(
        records(
            con,
            "SELECT * FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)",
            notes=notes,
        ),
        "ticker",
    )
    pool.add_rows(
        records(
            con,
            "SELECT symbol, price, prev_close, change_pct FROM quotes WHERE collected_at >= ?",
            [today - timedelta(days=3)],
            notes,
        ),
        "symbol",
    )
    pool.add_rows(
        records(
            con,
            "SELECT ticker, close, ret_1d, ret_5d, ret_20d FROM returns WHERE date >= ?",
            [today - timedelta(days=10)],
            notes,
        ),
        "ticker",
    )
    # row counts the narrative may quote ("902 headlines"): per kind today and in total
    for kind, col in (
        *FETCH_COL.items(),
        ("news_enriched", "analyzed_at"),
        ("predictions", "made_at"),
        ("ranges", "made_at"),
        ("events", "first_seen_at"),
    ):
        for count_row in (
            records(
                con,
                f"SELECT count(*) FILTER (WHERE CAST({col} AS DATE) = ?) AS a, count(*) AS b FROM {kind}",
                [today],
                notes,
            )
            or [{}]
        )[0].values():
            pool.add(None, "plain", count_row)
        # rows per fetch batch today ("72 new items"): one batch per first_seen/collected minute
        if kind in FETCH_COL:
            for row in records(
                con,
                f"SELECT count(*) AS n FROM {kind} WHERE CAST({col} AS DATE) = ? GROUP BY date_trunc('minute', {col})",
                [today],
                notes,
            ):
                pool.add(None, "plain", row["n"])
    # configured counts: watchlist size, market symbols, news feeds ("31 feeds")
    pool.add(None, "plain", len(cfg["tickers"]))
    pool.add(None, "plain", len(cfg["symbols"]))
    try:
        from marketbrief.collectors.news import build_jobs

        pool.add(None, "plain", len(build_jobs(cfg.get("news") or {}, cfg)))
    except Exception as e:  # noqa: BLE001 - only a source of numbers: noted, the check goes on
        notes.append(f"news feed count unavailable ({type(e).__name__}: {e})")
    steps = work_dir() / "steps"
    narrative_numbers.collector_summaries(pool, sorted(steps.glob("collect_*.json")) if steps.exists() else [])
    since = today - timedelta(days=validate_config["narrative_news_days"])
    for sql in (
        "SELECT id, title FROM news WHERE first_seen_at >= ?",
        "SELECT id, summary FROM news_enriched WHERE analyzed_at >= ?",
        "SELECT id, description FROM filings WHERE first_seen_at >= ?",
        "SELECT id, subject FROM announcements WHERE first_seen_at >= ?",
    ):
        for index, text in con.execute(sql, [since]).fetchall():
            if text:
                pool.add_text(str(text), scope_by_line=False, scope=("id", index))
    return pool


def skeletons(cfg: dict, session: str) -> tuple[str | None, str | None]:
    """The script-written report and Slack draft (work/ copies report.py saves; else rebuilt)."""
    report_path = work_dir() / f"report_{cfg['market']}_{session}.skeleton.md"
    slack_path = work_dir() / f"slack_{cfg['market']}.skeleton.md"
    if report_path.exists() and slack_path.exists():
        return report_path.read_text(encoding="utf-8"), slack_path.read_text(encoding="utf-8")
    from marketbrief.presentation.report import build
    from marketbrief.presentation.report import gather

    settings = load_settings()
    report_data = gather.gather(cfg, database.connect(cfg["market"]))
    report_text, slack_text, _ = build.build(cfg, report_data, settings)
    return report_text, slack_text


def agent_lines(filled: str, skeleton: str) -> list[str]:
    script = {line.strip() for line in skeleton.splitlines()}
    return [line for line in filled.splitlines() if line.strip() and line.strip() not in script]


def check_ranges(res: Result, cfg: dict, con, now: pd.Timestamp):
    from marketbrief.analytics.range_context import target_date

    ranges_config = market_config.load_ranges_config(cfg["market"])
    as_of = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    if as_of is None:
        return
    have = {
        (row[0], int(row[1]))
        for row in con.execute("SELECT ticker, horizon_days FROM ranges WHERE as_of_date = ?", [as_of]).fetchall()
    }
    feats = {
        row[0] for row in con.execute("SELECT ticker FROM features_latest WHERE as_of_date = ?", [as_of]).fetchall()
    }
    first = target_date(cfg, as_of, 1)
    skipped, missing = {}, []
    for horizon in ranges_config["horizons"]:
        tgt = target_date(cfg, as_of, horizon)
        for ticker in cfg["tickers"]:
            if (ticker, horizon) in have:
                continue
            if now >= calendar.session_close_utc(cfg, tgt):
                skipped.setdefault(f"{horizon}d: target {tgt} closed (late run)", []).append(ticker)
            elif tgt == first and now >= calendar.session_open_utc(cfg, first):
                skipped.setdefault(f"{horizon}d: target {tgt} opened (mid-session run)", []).append(ticker)
            elif ticker not in feats:
                skipped.setdefault(f"{horizon}d: no feature row as of {as_of}", []).append(ticker)
            else:
                missing.append(f"{ticker} {horizon}d")
    if missing:
        res.block(
            "MISSING_RANGE",
            f"no range as of {as_of} and no skip reason: {missing[:10]}",
            [missing_item.split()[0] for missing_item in missing],
        )
    res.info["ranges_skipped"] = {key: len(skipped_count) for key, skipped_count in skipped.items()}


def report_session(con, status: dict) -> str:
    """The session report.py names the report after (the latest ranges' session_date)."""
    row = con.execute(
        "SELECT session_date FROM ranges_latest ORDER BY as_of_date DESC, made_at DESC LIMIT 1"
    ).fetchone()
    return str(row[0])[:10] if row and row[0] else status["session_date"]


def report_file(cfg: dict, con, status: dict) -> Path:
    return paths.ROOT / "reports" / cfg["market"] / f"{report_session(con, status)}.md"


def stage_report(
    res, cfg, con, status, now, today, validate_config, report_path: Path | None = None, slack_path: Path | None = None
):
    session = report_session(con, status)
    report_path = report_path or report_file(cfg, con, status)
    slack_path = slack_path or work_dir() / f"slack_{cfg['market']}.md"
    check_files(
        res, cfg, ("news_enriched", "predictions", "ranges"), today, now, validate_config
    )  # appended since collect
    check_ranges(res, cfg, con, now)
    if not report_path.exists():
        res.block(
            "MISSING_REPORT",
            f"{report_path.relative_to(paths.ROOT) if report_path.is_relative_to(paths.ROOT) else report_path} not "
            f"written",
        )
        return
    filled = report_path.read_text(encoding="utf-8")
    slack = slack_path.read_text(encoding="utf-8") if slack_path.exists() else None
    if "<!-- AGENT:" in filled:
        res.block("AGENT_MARKERS", f"{report_path.name} still has {filled.count('<!-- AGENT:')} AGENT marker(s)")
    if "<!-- report-data:" not in filled:
        res.block("REPORT_DATA_LINE", f"{report_path.name} lost its report-data line")
    if slack is None:
        res.block("MISSING_SLACK_DRAFT", f"{slack_path.name} not written")
    elif "<!-- AGENT:" in slack:
        res.block("AGENT_MARKERS", f"{slack_path.name} still has AGENT marker(s)")
    skel_r, skel_s = skeletons(cfg, session)
    pack = work_dir() / "context.md"
    pool = build_pool(
        cfg,
        con,
        validate_config,
        today,
        [skel_r or "", skel_s or "", pack.read_text(encoding="utf-8") if pack.exists() else ""],
    )
    if pool.notes:
        res.info["number_sources"] = pool.notes
    small = validate_config["narrative_small_int"]
    targets = [(report_path, agent_lines(filled, skel_r or ""))]
    if slack is not None:
        targets.append((slack_path, agent_lines(slack, skel_s or "")))
    summary = paths.ROOT / "summaries" / cfg["market"] / "daily" / f"{today}.md"
    if summary.exists():
        targets.append((summary, summary.read_text(encoding="utf-8").splitlines()))
    checked = {}
    for path, lines in targets:
        bad = narrative_numbers.unmatched(lines, pool, small)
        checked[path.relative_to(paths.ROOT).as_posix() if path.is_relative_to(paths.ROOT) else str(path)] = {
            "agent_lines": len(lines),
            "unmatched": len(bad),
        }
        if bad:
            res.block(
                "UNMATCHED_NUMBER",
                f"{path.name}: {len(bad)} number(s) with no same-kind source number for "
                "the companies or symbols named (context pack, script-written report, cited news text, "
                "stored rows): "
                + "; ".join(
                    f'{narrative_number["token"]!r} in "{narrative_number["sentence"][:90]}"'
                    for narrative_number in bad[:12]
                ),
                [
                    entity
                    for narrative_number in bad
                    for entity in narrative_number["entities"]
                    if entity in cfg["tickers"]
                ],
            )
    if not pack.exists():
        res.warn(
            "NO_CONTEXT_PACK", "work/context.md missing: narrative numbers checked against the skeleton and DuckDB only"
        )
    res.info["report"] = checked
