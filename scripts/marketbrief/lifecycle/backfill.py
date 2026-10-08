"""Onboarding backfill (F8.3) for one candidate company, with the loader in candidate mode (MB_LIFECYCLE_CANDIDATE):
the collectors' own code stores only the candidate's rows, in the usual kinds and formats.

- prices: the price collector (Yahoo, split checks, holiday drops, NSE fallback for India) from the market's first
  stored price day, so the company has the same stored window as the others;
- news: the candidate's Google News company query over the news collector's current catch-up window, tagged with the
  whole watchlist plus the candidate; no news_runs row is written (that row steers the routine's own catch-up window);
- filings (US): the SEC submissions of the candidate's CIK, as collect_filings stores them;
- announcements (India): NSE corporate announcements of the candidate's symbol over `backfill.announcement_days`, as
  collect_nse_india --since stores them;
- long history: up to `long_history_years` (15) of Yahoo daily bars into the long-history cache
  work/model_history/<market>/ (model/history_cache.py's cleaning and format; gitignored, never data/), merged into
  the market's cache when one exists (the candidate's rows replaced, every other symbol kept).
Each step returns (status ok | failed | skipped, detail)."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from contextlib import contextmanager
from datetime import date, timedelta

import pandas as pd

from marketbrief.constants.config_keys import CFG_FILING_FORMS, CFG_FILING_LOOKBACK_DAYS, CFG_FILINGS, CFG_TICKERS
from marketbrief.constants.filings import DEFAULT_FILING_FORMS, DEFAULT_LOOKBACK_DAYS, SEEN_LOOKBACK_DAYS
from marketbrief.constants.kinds import KIND_ANNOUNCEMENTS, KIND_FILINGS, KIND_NEWS
from marketbrief.core import paths
from marketbrief.constants.model import FILE_HISTORY_BARS, FILE_HISTORY_MANIFEST
from marketbrief.core.calendar import last_complete_session
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.market_config import load_market
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.lifecycle.constants import DIR_WORK_LIFECYCLE, ENV_CANDIDATE, FAILED, OK, SKIPPED
from marketbrief.lifecycle.identity import meta_from_identity
from marketbrief.lifecycle.seed import history_start
from marketbrief.model.history_cache import cache_dir, clean_frame, own_sessions


@contextmanager
def candidate_mode(company: dict):
    """The loader in candidate mode for the duration (the candidate's identity in a work/ file)."""
    work = paths.ROOT / DIR_WORK_LIFECYCLE
    work.mkdir(parents=True, exist_ok=True)
    path = work / f"candidate-{company['market']}-{company['ticker'].replace('&', '_')}.json"
    path.write_text(json.dumps(company, default=str))
    before = os.environ.get(ENV_CANDIDATE)
    os.environ[ENV_CANDIDATE] = str(path)
    try:
        yield load_market(company["market"])
    finally:
        if before is None:
            os.environ.pop(ENV_CANDIDATE, None)
        else:
            os.environ[ENV_CANDIDATE] = before


def backfill_prices(cfg: dict, yfinance) -> tuple[str, dict]:
    """Daily bars of the candidate from the market's first stored price day."""
    from marketbrief.collectors.prices import PriceCollector

    start = history_start(cfg["market"])

    class FromStoredStart(PriceCollector):
        """The price collector asking Yahoo from the first stored day instead of a period."""

        def history(self, yf, symbol: str, **window):
            if "period" in window and start is not None:
                window = {"start": start.date().isoformat()}
            return super().history(yf, symbol, **window)

    collector = FromStoredStart(cfg, "max")
    summary = collector.collect(yfinance)
    detail = {"new_bars": collector.written, "from": start.date().isoformat() if start else None,
              "failed": summary.get("failed"), "warnings": summary.get("warnings"), "held": summary.get("held")}
    # bars an earlier, refused attempt stored stay (append-only) and count: the gate checks the stored bars
    return (FAILED if summary.get("failed") else OK), detail


def backfill_news(cfg_with_candidate: dict, ticker: str) -> tuple[str, dict]:
    """The candidate's Google News company query, stored like the news collector's rows (no news_runs row)."""
    from marketbrief.collectors.news import NewsCollector, build_jobs

    collector = NewsCollector(cfg_with_candidate)
    google = collector.google
    if not google:
        return SKIPPED, {"reason": "no google_news feed in the market config"}
    jobs = build_jobs({"google_news": google}, {CFG_TICKERS: {ticker: cfg_with_candidate[CFG_TICKERS][ticker]}},
                      collector.window.google_when)
    for job in jobs:
        collector.run_job(job)
    written = append_jsonl(day_file(collector.market, KIND_NEWS, utc_today()), collector.items.values())
    status = FAILED if jobs and collector.failed_feeds() == len(jobs) else OK
    return status, {"queries": len(jobs), "new_items": written, "window": collector.window.summary(),
                    "failed": collector.failed}


def with_candidate(full_cfg: dict, company: dict) -> dict:
    """The full watchlist config plus the candidate (for news tagging)."""
    return {**full_cfg, CFG_TICKERS: {**full_cfg[CFG_TICKERS], company["ticker"]: meta_from_identity(company)}}


def backfill_filings(cfg: dict, company: dict, edgar) -> tuple[str, dict]:
    """The candidate's SEC filings of the configured forms and lookback (US)."""
    from marketbrief.collectors.filings import filing_rows
    from marketbrief.sources.sec_filings import related_ciks, ticker_submissions

    if not cfg.get(CFG_FILINGS):
        return SKIPPED, {"reason": "market has no SEC filings"}
    forms = set(cfg.get(CFG_FILING_FORMS, DEFAULT_FILING_FORMS))
    since = utc_today() - timedelta(days=int(cfg.get(CFG_FILING_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS)))
    seen = recent_ids(cfg["market"], KIND_FILINGS, days=SEEN_LOOKBACK_DAYS)
    recent, errors = ticker_submissions(edgar, company["ticker"], int(company["cik"]), related_ciks(cfg))
    if recent is None:
        return FAILED, {"errors": errors}
    rows = filing_rows(recent, company["ticker"], forms, since, seen, utc_now())
    written = append_jsonl(day_file(cfg["market"], KIND_FILINGS, utc_today()), rows)
    return OK, {"new_filings": written, "since": since.isoformat(), "errors": errors}


def backfill_announcements(cfg: dict, nse, days: int) -> tuple[str, dict]:
    """The candidate's NSE corporate announcements of the last `days` days (India; one call per week, as the
    collector's --since does)."""
    from types import SimpleNamespace

    from marketbrief.collectors.nse_india import collect

    since = utc_today() - timedelta(days=days)
    summary = collect(cfg, nse, [KIND_ANNOUNCEMENTS], args=SimpleNamespace(since=since, full=False))
    written = (summary.get("new") or {}).get(KIND_ANNOUNCEMENTS)
    return (FAILED if written is None else OK), {"summary": summary}



def backfill_long_history(cfg: dict, yfinance, years: int) -> tuple[str, dict]:
    """The candidate's long daily history into the market's long-history cache (where Yahoo has it)."""
    now = clock()
    folder = cache_dir(cfg["market"])
    manifest_path = folder / FILE_HISTORY_MANIFEST
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    start = date.fromisoformat(manifest["start"]) if manifest else date(now.year - years, now.month, min(now.day, 28))
    ticker, meta = next(iter(cfg[CFG_TICKERS].items()))
    frame = yfinance.Ticker(meta["yahoo"]).history(start=start.isoformat(), interval="1d", auto_adjust=False)
    if frame is None or frame.empty:
        return FAILED, {"error": "Yahoo served no daily history", "requested_from": start.isoformat()}
    cut = {"today": now.date(), "own_through": last_complete_session(cfg, now),
           "sessions": own_sessions(cfg, start, now.date())}
    rows, counts = clean_frame(cfg, ticker, frame, cut)
    bars = rows
    if (folder / FILE_HISTORY_BARS).exists():
        old = pd.read_csv(io.BytesIO(gzip.decompress((folder / FILE_HISTORY_BARS).read_bytes())), parse_dates=["date"])
        old["date"] = old["date"].dt.date
        bars = pd.concat([old[old["ticker"] != ticker], rows]).sort_values(["ticker", "date"])
    payload = gzip.compress(bars.to_csv(index=False).encode(), mtime=0)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE_HISTORY_BARS).write_bytes(payload)
    first = rows["date"].min() if len(rows) else None
    fetched_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = manifest or {"market": cfg["market"], "start": start.isoformat(), "file": FILE_HISTORY_BARS,
                            "symbols": {}, "failed": [], "fetched_at": fetched_at}
    # the cache-wide fetched_at stays the full fetch's time; this symbol carries its own
    manifest["symbols"][ticker] = {"yahoo": meta["yahoo"], "role": "ticker", "rows": len(rows),
                                   "first": str(first) if first else None,
                                   "last": str(rows["date"].max()) if len(rows) else None, **counts,
                                   "fetched_at": fetched_at}
    manifest.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), rows=len(bars))
    manifest_path.write_text(json.dumps(manifest, indent=1))
    years_found = round((now.date() - first).days / 365.25, 1) if first else 0.0
    detail = {"rows": len(rows), "first": str(first) if first else None, "years": years_found,
              "requested_from": start.isoformat(), "cache": f"work/model_history/{cfg['market']}/"}
    return (OK if len(rows) else FAILED), detail
