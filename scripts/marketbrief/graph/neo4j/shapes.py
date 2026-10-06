"""Row shapers: one stored row of each kind to the parameters of its Cypher statement."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable
from marketbrief.utils.text import slugify_with_unknown_fallback
from marketbrief.constants.neo4j import PERSON_CATEGORIES


def clean(value):
    """A JSON- and Neo4j-safe value: dates as ISO strings, NaN as null, no nested maps."""
    if isinstance(value, date):  # a datetime is a date
        if isinstance(value, datetime) and not value.tzinfo:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value if item is not None]
    if isinstance(value, dict):
        return json.dumps(value, default=str, sort_keys=True)
    return value


def base_row(row: dict, node_id: str, source_id, drop: tuple = ()) -> dict:
    props = {key: clean(value) for key, value in row.items() if key not in ("id", "_ts") + drop}
    return {
        "id": node_id,
        "source_id": str(source_id) if source_id is not None else None,
        "recorded_at": clean(row.get("_ts")),
        "props": props,
    }


def company_id(market: str, ticker: str | None) -> str:
    return f"{market}:{ticker}"


def holder_id(market: str, cik, name) -> str:
    return f"{market}:cik:{cik}" if cik else f"{market}:name:{slugify_with_unknown_fallback(name)}"


def shape_news(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:{stored_row['id']}", stored_row["id"], drop=("day",))
    row["props"]["outlet"] = row["props"].pop("source", None)
    row["tickers"], row["day"] = row["props"].get("tickers") or [], clean(stored_row.get("day"))
    row["mentions"] = {
        key: row["props"].get(key)
        for key in ("sentiment", "relevance", "materiality", "event_type", "novelty", "analyzed_at", "prompt_version")
    }
    return row


def shape_source(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:{stored_row['id']}", stored_row["id"])
    row["ticker"], row["company_id"] = stored_row.get("ticker"), company_id(market, stored_row.get("ticker"))
    return row


def shape_event(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:{stored_row['id']}", stored_row["id"])
    row["ticker"], row["company_id"] = stored_row.get("ticker"), company_id(market, stored_row.get("ticker"))
    return row


def shape_insider(market: str, stored_row: dict) -> dict:
    row = base_row(
        stored_row, f"{market}:insider:{stored_row['id']}", stored_row["id"], drop=("holder_name", "holder_cik")
    )
    cat = str(stored_row.get("role") or "").lower()
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        holder_id=holder_id(market, stored_row.get("holder_cik"), stored_row.get("holder_name")),
        holder_name=stored_row.get("holder_name"),
        holder_cik=stored_row.get("holder_cik"),
        holder_kind="insider",
        holder_person=bool(
            stored_row.get("is_director")
            or stored_row.get("is_officer")
            or any(category in cat for category in PERSON_CATEGORIES)
        ),
    )
    row["props"]["via"] = "insider"
    return row


def shape_deal(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:deal:{stored_row['id']}", stored_row["id"])
    side = str(stored_row.get("side") or "").lower()
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        holder_id=holder_id(market, None, stored_row.get("client")),
        holder_name=stored_row.get("client"),
        holder_cik=None,
        holder_kind="deal_client",
        holder_person=False,
    )
    row["props"].update(
        via=str(stored_row.get("deal_type") or "deal").lower(),
        side="buy" if side.startswith("buy") else "sell" if side.startswith("sell") else side or None,
    )
    return row


def shape_stake(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:stake:{stored_row['id']}", stored_row["id"])
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        holder_id=holder_id(market, stored_row.get("filer_cik"), stored_row.get("filer_name")),
        holder_name=stored_row.get("filer_name"),
        holder_cik=stored_row.get("filer_cik"),
        holder_kind="stake_filer",
        holder_person=False,
    )
    row["props"]["via"] = stored_row.get("kind") or stored_row.get("form")
    return row


def shape_13f(market: str, stored_row: dict) -> dict:
    key = f"{stored_row['filer_cik']}|{stored_row['ticker']}|{clean(stored_row['period'])}"
    row = base_row(stored_row, f"{market}:13f:{key}", stored_row["id"], drop=("filer_name",))
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        holder_id=holder_id(market, stored_row["filer_cik"], stored_row.get("filer_name")),
        holder_name=stored_row.get("filer_name"),
        holder_cik=stored_row["filer_cik"],
        holder_kind="13f_filer",
        holder_person=False,
    )
    row["props"]["via"] = "13F"
    return row


def shape_shareholding(market: str, stored_row: dict) -> dict:
    key = f"{stored_row['ticker']}|{clean(stored_row['period_end'])}"
    row = base_row(stored_row, f"{market}:shp:{key}", ",".join(stored_row["source_ids"] or []))
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        holder_id=f"{market}:promoters:{stored_row['ticker']}",
        holder_name=f"Promoter group of {stored_row['ticker']}",
        holder_cik=None,
        holder_kind="promoter_group",
        holder_person=False,
    )
    row["props"].update(via="shareholding", period=row["props"].get("period_end"))
    return row


def shape_graph(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, stored_row["id"], stored_row["id"])
    row["id"] = f"{market}:graph:{stored_row['id']}"
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        status=stored_row.get("status") or "active",
        target_ticker=stored_row.get("target_ticker"),
        target_id=company_id(market, stored_row["target_ticker"])
        if stored_row.get("target_ticker")
        else f"{market}:name:{slugify_with_unknown_fallback(stored_row.get('target'))}",
        target_name=stored_row.get("target"),
        target_person=stored_row.get("target_kind") == "person",
    )
    return row


def shape_prediction(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:{stored_row['id']}", stored_row["id"])
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        evidence=[
            {"id": f"{market}:{evidence_id}", "record_id": evidence_id}
            for evidence_id in (stored_row.get("evidence_ids") or [])
            if evidence_id
        ],
    )
    return row


def shape_outcome(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:call:{stored_row['prediction_id']}", stored_row["prediction_id"])
    row["props"]["kind"] = "call"
    row["parent_id"], row["parent_record"] = f"{market}:{stored_row['prediction_id']}", stored_row["prediction_id"]
    return row


def shape_range(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:{stored_row['id']}", stored_row["id"])
    row.update(
        ticker=stored_row["ticker"],
        company_id=company_id(market, stored_row["ticker"]),
        prediction_id=f"{market}:{stored_row['id']}",
    )
    return row


def shape_range_outcome(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:range:{stored_row['range_id']}", stored_row["range_id"])
    row["props"]["kind"] = "range"
    row["parent_id"], row["parent_record"] = f"{market}:{stored_row['range_id']}", stored_row["range_id"]
    return row


def shape_market_day(key_fields: tuple) -> Callable[[str, dict], dict]:
    def shape(market: str, row: dict) -> dict:
        key = ":".join(str(clean(row.get(field))) for field in key_fields)
        return base_row(row, f"{market}:{key}", row.get("id") or key)

    return shape


def shape_feature(market: str, stored_row: dict) -> dict:
    row = base_row(stored_row, f"{market}:{stored_row['ticker']}:{clean(stored_row['as_of_date'])}", stored_row["id"])
    row.update(ticker=stored_row["ticker"], company_id=company_id(market, stored_row["ticker"]))
    return row


def shape_fundamentals(market: str, stored_row: dict) -> dict:
    key = f"{stored_row['ticker']}:sec:{clean(stored_row['period_end'])}"
    row = base_row(
        stored_row,
        f"{market}:{key}",
        f"fundamentals_metrics:{stored_row['ticker']}:{clean(stored_row['period_end'])}",
    )
    row.update(ticker=stored_row["ticker"], company_id=company_id(market, stored_row["ticker"]))
    row["props"]["basis"] = "sec_xbrl"
    return row


def shape_financials(market: str, stored_row: dict) -> dict:
    key = (
        f"{stored_row['ticker']}:{stored_row.get('basis')}:{clean(stored_row.get('period_start'))}:"
        f"{clean(stored_row['period_end'])}"
    )
    row = base_row(stored_row, f"{market}:{key}", stored_row["id"])
    row.update(ticker=stored_row["ticker"], company_id=company_id(market, stored_row["ticker"]))
    return row
