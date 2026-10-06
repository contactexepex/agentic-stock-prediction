"""The collect, features, context and forecast stages."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from marketbrief.pipeline import forecast_gate
from marketbrief.core import paths, schemas
from marketbrief.constants.validation import STAGE_KINDS
from marketbrief.pipeline.validate.collect_checks import check_bars, check_duplicates, check_fetches, check_files, check_summaries
from marketbrief.pipeline.validate.gate_result import work_dir
from marketbrief.pipeline.validate.news_checks import check_articles, check_news_sources


def stage_collect(res, cfg, con, st, now, today, vc):
    kinds = [k for k in schemas.SCHEMAS if k not in STAGE_KINDS["features"] and k not in ("ranges", "predictions",
                                                                                  "news_enriched", "judgments")]
    counts = check_files(res, cfg, kinds, today, now, vc)
    check_duplicates(res, cfg, con, vc)
    check_bars(res, cfg, con, st, vc)
    check_fetches(res, cfg, con, now, today, vc)
    res.info["collect"] = check_summaries(res, cfg, {k: v for k, v in counts.items() if v or k in ("prices", "quotes", "news")}, vc)
    check_news_sources(res, cfg, con, today)
    check_articles(res, cfg, today)


def stage_features(res, cfg, con, st, now, today, vc):
    check_files(res, cfg, STAGE_KINDS["features"], today, now, vc)
    last = dict(con.execute("SELECT ticker, max(date) FROM bars GROUP BY 1").fetchall())
    feats = {r[0]: (r[1], r[2]) for r in con.execute("SELECT DISTINCT ON (ticker) ticker, as_of_date, quality FROM features_latest "
                                                     "ORDER BY ticker, as_of_date DESC").fetchall()}
    missing = [t for t in cfg["tickers"] if t not in feats]
    behind = [t for t in cfg["tickers"] if t in feats and t in last and feats[t][0] < last[t]]
    if missing:
        res.block("MISSING_FEATURES", "no feature row", missing)
    if behind:
        res.block("STALE_FEATURES", "feature row older than the ticker's newest bar (run features.py)", behind)
    blocked = [t for t in cfg["tickers"] if t in feats and feats[t][1] == "BLOCKED"]
    if blocked:
        res.warn("QUALITY_BLOCKED", "indicator quality BLOCKED: no call allowed", blocked)
    need = date.fromisoformat(st["previous_session"])
    reg = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    if reg is None or reg < need:
        res.block("MISSING_REGIME", f"no regime row as of {need} (newest {reg})")


def stage_context(res, cfg, con, st, now, today, vc, path: Path | None = None):
    path = path or work_dir() / "context.md"
    if not path.exists() or path.stat().st_size == 0:
        res.block("MISSING_CONTEXT", f"{path.relative_to(paths.ROOT) if path.is_relative_to(paths.ROOT) else path} is missing or empty")
        return
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text else ""
    if not first.startswith("# Context pack") or str(today) not in first:
        res.block("STALE_CONTEXT", f"first line is not today's pack header: {first[:80]!r}")
    if "Traceback (most recent call last)" in text:
        res.block("CONTEXT_ERROR", "the context pack contains a Python traceback")
    absent = [t for t in cfg["tickers"] if not re.search(rf"(?<![\w&]){re.escape(t)}(?![\w&])", text)]
    if absent:
        res.block("CONTEXT_INCOMPLETE", "watchlist tickers not named in the context pack", absent)
    if "## Market regime" not in text:
        res.block("CONTEXT_INCOMPLETE", "no 'Market regime' section")


def stage_forecast(res, cfg, con, st, now, today, vc, path: Path | None = None):  # noqa: ARG001
    """work/predictions.jsonl (or `path`) before it is appended."""
    forecast_gate.stage_forecast(res, cfg, con, st, now, vc, path or work_dir() / "predictions.jsonl")
