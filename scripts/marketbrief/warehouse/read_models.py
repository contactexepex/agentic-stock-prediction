"""The per-page read models (docs/ARCHITECTURE.md section 4; payload schemas in api/openapi.yaml): one JSON
payload per (market, page_key) that the app reads with one keyed SELECT. Every payload is sliced from the
dashboard's own data (presentation/dashboard/assemble.gather_dashboard, as of the run's clock); nothing is
recomputed here. The upcoming company events of the stock page are read with the dashboard's as-of rule.

  rm.overview      page_key _        Overview: header, session plan, skill verdict, market overview tiles
  rm.watchlist     page_key _        Watchlist: one row per stock (last session, P(up), calls, ranges)
  rm.stock         page_key ticker   StockDetail: the dashboard's stock data without bars, plus events
  rm.bars          page_key ticker   Bars: split-adjusted OHLC bars and the published ranges
  rm.track_record  page_key _        TrackRecord: calls per scoring basis, ranges, replay, backtest

A payload carries no cut-off time (the envelope's `cutoff` does), so a rebuild that finds the same data
produces the same payload and hash (section 4.4)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pandas as pd

from marketbrief.constants.warehouse import (
    BAR_COLUMNS,
    MARKET_PAGE_KEY,
    READ_MODEL_SCHEMA_VERSION,
    REQUIRED_KEYS,
    RM_BARS,
    RM_OVERVIEW,
    RM_STOCK,
    RM_TRACK_RECORD,
    RM_WATCHLIST,
    WATCHLIST_ROW_REQUIRED,
)
from marketbrief.presentation.dashboard import reads
from marketbrief.presentation.dashboard.assemble import gather_dashboard
from marketbrief.presentation.dashboard.stock import iso_day
from marketbrief.utils.numbers import json_safe_float

READ_MODEL_COLUMNS = {
    "market": "VARCHAR",
    "page_key": "VARCHAR",
    "as_of": "DATE",
    "cutoff": "TIMESTAMPTZ",
    "built_at": "TIMESTAMPTZ",
    "schema_version": "VARCHAR",
    "source_commit": "VARCHAR",
    "payload_sha256": "VARCHAR",
    "payload": "JSON",
}
# the company_events view (latest date per ticker and type, "_history" sources left out) from the rows first
# seen by the cut-off, kept when the date is after the as-of date
EVENTS_SQL = """
SELECT ticker, id, date, type, name, source, timing, amount FROM (
  SELECT DISTINCT ON (ticker, type) * FROM events
  WHERE ticker IS NOT NULL AND NOT ends_with(coalesce(source, ''), '_history') AND first_seen_at <= $cutoff::TIMESTAMPTZ
  ORDER BY ticker, type, first_seen_at DESC, date)
WHERE date > $as_of ORDER BY ticker, date, type, id"""
HEADER = ("market", "name", "currency", "symbol", "as_of", "disclaimer", "not_available", "empty", "plan", "skill")


def upcoming_events(con, as_of, cutoff: str) -> dict[str, list[dict]]:
    """ticker -> its upcoming company events (CompanyEvent) as known by the cut-off."""
    rows = reads.frame(con, EVENTS_SQL, {"as_of": as_of, "cutoff": cutoff})
    out: dict[str, list[dict]] = {}
    for r in rows.itertuples():
        event = {"id": r.id, "date": iso_day(r.date), "type": r.type, "name": r.name, "source": r.source}
        event.update(timing=None if pd.isna(r.timing) else r.timing, amount=json_safe_float(r.amount))
        out.setdefault(r.ticker, []).append(event)
    return out


def watchlist_row(company: dict) -> dict:
    """One stock's row of the watchlist page."""
    ind = company.get("indicators") or {}
    model = [{k: m[k] for k in ("h", "id", "prob_up", "calibrated")} for m in company["model"]]
    return {
        **{k: company[k] for k in ("ticker", "name", "sector", "last", "calls", "ranges", "earnings")},
        "ret_1d": ind.get("ret_1d"),
        "ret_5d": ind.get("ret_5d"),
        "quality": ind.get("quality"),
        "days_to_earnings": ind.get("days_to_earnings"),
        "model": model,
    }


def stock_payload(data: dict, company: dict, events: list[dict]) -> dict:
    """The stock page: the dashboard's stock data without bars, the fits behind its scores and its events."""
    used = {m["model_id"] for m in company["model"]}
    body = {k: v for k, v in company.items() if k != "bars"}
    models = [v for v in data.get("models") or [] if v.get("id") in used]
    return {
        **body,
        "as_of": data["as_of"],
        "plan": data["plan"],
        "skill": data["skill"],
        "models": models,
        "events": events,
    }


def page_payloads(data: dict, events: dict[str, list[dict]]) -> dict[str, dict[str, dict]]:
    """table -> page_key -> payload for one market's dashboard data."""
    head = {k: data.get(k) for k in HEADER}
    common = {"market": data["market"], "as_of": data["as_of"], "plan": data["plan"], "skill": data["skill"]}
    companies = data["companies"]
    return {
        RM_OVERVIEW: {MARKET_PAGE_KEY: {**head, "overview": data["overview"]}},
        RM_WATCHLIST: {MARKET_PAGE_KEY: {**common, "rows": [watchlist_row(c) for c in companies]}},
        RM_STOCK: {c["ticker"]: stock_payload(data, c, events.get(c["ticker"], [])) for c in companies},
        RM_BARS: {
            c["ticker"]: {
                "ticker": c["ticker"],
                "as_of": data["as_of"],
                "columns": BAR_COLUMNS,
                "bars": c["bars"],
                "ranges": c["ranges"],
                "spans": data["spans"],
                "default_span": data["default_span"],
            }
            for c in companies
        },
        RM_TRACK_RECORD: {MARKET_PAGE_KEY: {"skill": data["skill"], **data["track"], "backtest": data["backtest"]}},
    }


def missing_keys(table: str, payload: dict) -> list[str]:
    """Required keys (api/openapi.yaml) the payload lacks; watchlist rows are checked too."""
    missing = [k for k in REQUIRED_KEYS[table] if k not in payload]
    if table == RM_WATCHLIST:
        for i, row in enumerate(payload.get("rows") or []):
            missing += [f"rows[{i}].{k}" for k in WATCHLIST_ROW_REQUIRED if k not in row]
    return missing


def canonical(payload: dict) -> str:
    """The canonical JSON of a payload: sorted keys, no whitespace, strict (a NaN is an error)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def build_rows(cfg: dict, con, cutoff_time: datetime, source_commit: str, built_at: str) -> tuple[dict, list[str]]:
    """(table -> page_key -> row, invalid pages) of a market as of the cut-off. A row has READ_MODEL_COLUMNS
    with the payload as canonical JSON text; a page missing a required key is left out and listed as
    (table, page_key, missing keys)."""
    data = gather_dashboard(cfg, con, cutoff_time)
    cutoff = pd.Timestamp(cutoff_time).isoformat()
    events = upcoming_events(con, data["as_of"], cutoff) if data["as_of"] else {}
    out, invalid = {}, []
    for table, pages in page_payloads(data, events).items():
        out[table] = {}
        for page_key, payload in pages.items():
            missing = missing_keys(table, payload)
            if missing:
                invalid.append((table, page_key, missing))
                continue
            text = canonical(payload)
            out[table][page_key] = {
                "market": cfg["market"],
                "page_key": page_key,
                "as_of": data["as_of"],
                "cutoff": cutoff,
                "built_at": built_at,
                "schema_version": READ_MODEL_SCHEMA_VERSION,
                "source_commit": source_commit,
                "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "payload": text,
            }
    return out, invalid
