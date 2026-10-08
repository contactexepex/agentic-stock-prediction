"""The per-page read models (docs/ARCHITECTURE.md section 4; payload schemas in api/openapi.yaml): one JSON
payload per (market, page_key) that the app reads with one keyed SELECT. Every payload is sliced from the
dashboard's own data (presentation/dashboard/assemble.gather_dashboard, as of the run's clock); nothing is
recomputed here. The upcoming company events of the stock page are read with the dashboard's as-of rule.

  rm.overview      page_key _        Overview: header, session plan, skill verdict, market overview tiles
  rm.watchlist     page_key _        Watchlist: one row per stock (last session, P(up), calls, ranges)
  rm.stock         page_key ticker   StockDetail: the dashboard's stock data without bars, plus events
  rm.bars          page_key ticker   Bars: split-adjusted OHLC bars and the published ranges

`build_rows` runs every registered builder (warehouse/rm_registry.py; these four 1.0 pages are rm_dashboard.py's) and
checks each payload against its schema in api/openapi.yaml before it is written.

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
    RM_BARS,
    RM_OVERVIEW,
    RM_STOCK,
    RM_WATCHLIST,
)
from marketbrief.presentation.dashboard import reads
from marketbrief.presentation.dashboard.stock import iso_day
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import openapi_spec, rm_registry, schema_check
from marketbrief.warehouse.rm_registry import BuildContext, PageBuilder

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
# the stock page's upcoming company events: the company_events rule as of the cut-off, dated after the as-of date
EVENTS_SQL = f"""SELECT ticker, id, date, type, name, source, timing, amount FROM ({reads.COMPANY_EVENTS_ASOF_SQL})
WHERE date > $as_of ORDER BY ticker, date, type, id"""
WATCHLIST_COMPANY_FIELDS = ("ticker", "name", "sector", "last", "calls", "ranges", "earnings")
WATCHLIST_INDICATOR_FIELDS = ("ret_1d", "ret_5d", "quality", "days_to_earnings")
WATCHLIST_SCORE_FIELDS = ("h", "id", "prob_up", "calibrated")
HEADER = ("market", "name", "currency", "symbol", "as_of", "disclaimer", "not_available", "empty", "plan", "skill")


def upcoming_events(con, as_of, cutoff: str) -> dict[str, list[dict]]:
    """ticker -> its upcoming company events (CompanyEvent) as known by the cut-off."""
    events_by_ticker: dict[str, list[dict]] = {}
    for event in reads.frame(con, EVENTS_SQL, {"as_of": as_of, "cutoff": cutoff}).itertuples():
        events_by_ticker.setdefault(event.ticker, []).append(
            {
                "id": event.id,
                "date": iso_day(event.date),
                "type": event.type,
                "name": event.name,
                "source": event.source,
                "timing": None if pd.isna(event.timing) else event.timing,
                "amount": json_safe_float(event.amount),
            }
        )
    return events_by_ticker


def watchlist_row(company: dict) -> dict:
    """One stock's row of the watchlist page."""
    indicators = company.get("indicators") or {}
    model = [{key: score[key] for key in WATCHLIST_SCORE_FIELDS} for score in company["model"]]
    return {
        **{key: company[key] for key in WATCHLIST_COMPANY_FIELDS},
        **{key: indicators.get(key) for key in WATCHLIST_INDICATOR_FIELDS},
        "model": model,
    }


def stock_payload(data: dict, company: dict, events: list[dict]) -> dict:
    """The stock page: the dashboard's stock data without bars, the fits behind its scores and its events."""
    model_ids = {score["model_id"] for score in company["model"]}
    return {
        **{key: value for key, value in company.items() if key != "bars"},
        "as_of": data["as_of"],
        "plan": data["plan"],
        "skill": data["skill"],
        "models": [version for version in data.get("models") or [] if version.get("id") in model_ids],
        "events": events,
    }


def bars_payload(data: dict, company: dict) -> dict:
    """The chart page: the stock's split-adjusted bars and published ranges."""
    return {
        "ticker": company["ticker"],
        "as_of": data["as_of"],
        "columns": BAR_COLUMNS,
        "bars": company["bars"],
        "ranges": company["ranges"],
        "spans": data["spans"],
        "default_span": data["default_span"],
    }


def page_payloads(data: dict, events: dict[str, list[dict]]) -> dict[str, dict[str, dict]]:
    """table -> page_key -> payload for one market's dashboard data."""
    header = {key: data.get(key) for key in HEADER}
    page_basics = {"market": data["market"], "as_of": data["as_of"], "plan": data["plan"], "skill": data["skill"]}
    companies = data["companies"]
    return {
        RM_OVERVIEW: {MARKET_PAGE_KEY: {**header, "overview": data["overview"]}},
        RM_WATCHLIST: {MARKET_PAGE_KEY: {**page_basics, "rows": [watchlist_row(company) for company in companies]}},
        RM_STOCK: {
            company["ticker"]: stock_payload(data, company, events.get(company["ticker"], [])) for company in companies
        },
        RM_BARS: {company["ticker"]: bars_payload(data, company) for company in companies},
    }


def canonical(payload: dict) -> str:
    """The canonical JSON of a payload: sorted keys, no whitespace, strict (a NaN is an error)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def page_row(envelope: dict, page_key: str, payload: dict) -> dict:
    """One rm row: the build's envelope, the page key, the canonical payload and its SHA-256."""
    text = canonical(payload)
    return {
        **envelope,
        "page_key": page_key,
        "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "payload": text,
    }


def page_problems(builder: PageBuilder, payload: dict, document: dict) -> list[str]:
    """The payload's problems against its schema in the bundled contract (empty = valid)."""
    return schema_check.errors(payload, {"$ref": f"#/components/schemas/{builder.schema}"}, document)


def build_rows(
    cfg: dict, con, cutoff_time: datetime, source_commit: str, built_at: str
) -> tuple[dict, list[tuple[str, str, list[str]]]]:
    """(table -> page_key -> row, invalid pages) of a market as of the cut-off, from every registered builder
    (rm_registry). A row has READ_MODEL_COLUMNS with the payload as canonical JSON text; a page that fails its
    schema in api/openapi.yaml is left out and listed as (table, page_key, problems)."""
    ctx = BuildContext(cfg, con, cutoff_time)
    document = openapi_spec.spec()
    envelope = {
        "market": cfg["market"],
        "as_of": ctx.as_of,
        "cutoff": ctx.cutoff,
        "built_at": built_at,
        "schema_version": openapi_spec.version(document),
        "source_commit": source_commit,
    }
    rows, invalid = {}, []
    for builder in rm_registry.builders():
        rows[builder.table] = {}
        for page_key, payload in builder.build(ctx).items():
            problems = page_problems(builder, payload, document)
            if problems:
                invalid.append((builder.table, page_key, problems))
            else:
                rows[builder.table][page_key] = page_row(envelope, page_key, payload)
    return rows, invalid
