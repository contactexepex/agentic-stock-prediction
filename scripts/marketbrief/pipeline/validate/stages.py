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


def stage_collect(res, cfg, con, status, now, today, validate_config):  # noqa: PLR0913 (uniform stage signature)
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
        res.block("MISSING_FEATURES", "no feature row", missing)
    if behind:
        res.block("STALE_FEATURES", "feature row older than the ticker's newest bar (run features.py)", behind)
    blocked = [ticker for ticker in cfg["tickers"] if ticker in feats and feats[ticker][1] == "BLOCKED"]
    if blocked:
        res.warn("QUALITY_BLOCKED", "indicator quality BLOCKED: no call allowed", blocked)
    need = date.fromisoformat(status["previous_session"])
    reg = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    if reg is None or reg < need:
        res.block("MISSING_REGIME", f"no regime row as of {need} (newest {reg})")


def stage_context(  # noqa: PLR0913 (uniform stage signature)
    res, cfg, _con, _status, _now, today, _validate_config, path: Path | None = None
):
    path = path or work_dir() / "context.md"
    if not path.exists() or path.stat().st_size == 0:
        res.block(
            "MISSING_CONTEXT",
            f"{path.relative_to(paths.ROOT) if path.is_relative_to(paths.ROOT) else path} is missing or empty",
        )
        return
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text else ""
    if not first.startswith("# Context pack") or str(today) not in first:
        res.block("STALE_CONTEXT", f"first line is not today's pack header: {first[:80]!r}")
    if "Traceback (most recent call last)" in text:
        res.block("CONTEXT_ERROR", "the context pack contains a Python traceback")
    absent = [ticker for ticker in cfg["tickers"] if not re.search(rf"(?<![\w&]){re.escape(ticker)}(?![\w&])", text)]
    if absent:
        res.block("CONTEXT_INCOMPLETE", "watchlist tickers not named in the context pack", absent)
    if "## Market regime" not in text:
        res.block("CONTEXT_INCOMPLETE", "no 'Market regime' section")


def stage_forecast(  # noqa: PLR0913 (uniform stage signature)
    res, cfg, con, status, now, _today, validate_config, path: Path | None = None
):
    """work/predictions.jsonl (or `path`) before it is appended."""
    forecast_gate.stage_forecast(res, cfg, con, status, now, validate_config, path or work_dir() / "predictions.jsonl")
