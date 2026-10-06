"""The collect, features, context and forecast stages."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from marketbrief.pipeline import forecast_gate
from marketbrief.core import paths, schemas
from marketbrief.constants.validation import STAGE_KINDS
from marketbrief.pipeline.validate.collect_checks import (
    check_bars,
    check_duplicates,
    check_fetches,
    check_files,
    check_summaries,
)
from marketbrief.pipeline.validate.gate_result import work_dir
from marketbrief.pipeline.validate.news_checks import check_articles, check_news_sources
from marketbrief.constants.validation import (
    MSG_FEATURE_ROW_OLDER_THAN_THE_TICKER,
    MSG_FIRST_LINE_IS_NOT_TODAY_S,
    MSG_INDICATOR_QUALITY_BLOCKED_NO_CALL_ALLOWED,
    MSG_IS_MISSING_OR_EMPTY,
    MSG_NO_FEATURE_ROW,
    MSG_NO_MARKET_REGIME_SECTION,
    MSG_NO_REGIME_ROW_AS_OF_NEWEST,
    MSG_THE_CONTEXT_PACK_CONTAINS_A_PYTHON,
    MSG_WATCHLIST_TICKERS_NOT_NAMED_IN_THE,
)


def stage_collect(res, cfg, con, status, now, today, validate_config):  # noqa: PLR0913 (uniform stage signature)
    """Collect stage: files, duplicates, bars, fetches and the collectors' summaries."""
    kinds = [
        key
        for key in schemas.SCHEMAS
        if key not in STAGE_KINDS["features"] and key not in ("ranges", "predictions", "news_enriched", "judgments")
    ]
    counts = check_files(res, cfg, kinds, today, now, validate_config)
    check_duplicates(res, cfg, con, validate_config)
    check_bars(res, cfg, con, status, validate_config)
    check_fetches(res, cfg, con, now, today, validate_config)
    res.info["collect"] = check_summaries(
        res,
        cfg,
        {key: value for key, value in counts.items() if value or key in ("prices", "quotes", "news")},
        validate_config,
    )
    check_news_sources(res, cfg, con, today)
    check_articles(res, cfg, today)


def stage_features(res, cfg, con, status, now, today, validate_config):  # noqa: PLR0913 (uniform stage signature)
    """Features stage: every ticker has a current feature row; the regime row exists."""
    check_files(res, cfg, STAGE_KINDS["features"], today, now, validate_config)
    last = dict(con.execute("SELECT ticker, max(date) FROM bars GROUP BY 1").fetchall())
    feats = {
        row[0]: (row[1], row[2])
        for row in con.execute(
            "SELECT DISTINCT ON (ticker) ticker, as_of_date, quality FROM features_latest "
            "ORDER BY ticker, as_of_date DESC"
        ).fetchall()
    }
    missing = [ticker for ticker in cfg["tickers"] if ticker not in feats]
    behind = [
        ticker for ticker in cfg["tickers"] if ticker in feats and ticker in last and feats[ticker][0] < last[ticker]
    ]
    if missing:
        res.block("MISSING_FEATURES", MSG_NO_FEATURE_ROW, missing)
    if behind:
        res.block("STALE_FEATURES", MSG_FEATURE_ROW_OLDER_THAN_THE_TICKER, behind)
    blocked = [ticker for ticker in cfg["tickers"] if ticker in feats and feats[ticker][1] == "BLOCKED"]
    if blocked:
        res.warn("QUALITY_BLOCKED", MSG_INDICATOR_QUALITY_BLOCKED_NO_CALL_ALLOWED, blocked)
    need = date.fromisoformat(status["previous_session"])
    reg = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    if reg is None or reg < need:
        res.block("MISSING_REGIME", MSG_NO_REGIME_ROW_AS_OF_NEWEST.format(need=need, reg=reg))


def stage_context(  # noqa: PLR0913 (uniform stage signature)
    res, cfg, _con, _status, _now, today, _validate_config, path: Path | None = None
):
    """Context stage: the context pack exists, has its header and names every ticker."""
    path = path or work_dir() / "context.md"
    if not path.exists() or path.stat().st_size == 0:
        res.block(
            "MISSING_CONTEXT",
            MSG_IS_MISSING_OR_EMPTY.format(
                value=path.relative_to(paths.ROOT) if path.is_relative_to(paths.ROOT) else path
            ),
        )
        return
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text else ""
    if not first.startswith("# Context pack") or str(today) not in first:
        res.block("STALE_CONTEXT", MSG_FIRST_LINE_IS_NOT_TODAY_S.format(value=first[:80]))
    if "Traceback (most recent call last)" in text:
        res.block("CONTEXT_ERROR", MSG_THE_CONTEXT_PACK_CONTAINS_A_PYTHON)
    absent = [ticker for ticker in cfg["tickers"] if not re.search(rf"(?<![\w&]){re.escape(ticker)}(?![\w&])", text)]
    if absent:
        res.block("CONTEXT_INCOMPLETE", MSG_WATCHLIST_TICKERS_NOT_NAMED_IN_THE, absent)
    if "## Market regime" not in text:
        res.block("CONTEXT_INCOMPLETE", MSG_NO_MARKET_REGIME_SECTION)


def stage_forecast(  # noqa: PLR0913 (uniform stage signature)
    res, cfg, con, status, now, _today, validate_config, path: Path | None = None
):
    """work/predictions.jsonl (or `path`) before it is appended."""
    forecast_gate.stage_forecast(res, cfg, con, status, now, validate_config, path or work_dir() / "predictions.jsonl")
