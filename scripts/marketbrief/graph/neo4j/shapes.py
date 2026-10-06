"""Row shapers: one stored row of each kind to the parameters of its Cypher statement."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable
from marketbrief.utils.text import slugify_with_unknown_fallback
from marketbrief.constants.neo4j import PERSON_CATEGORIES


def clean(v):
    """A JSON- and Neo4j-safe value: dates as ISO strings, NaN as null, no nested maps."""
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v if x is not None]
    if isinstance(v, dict):
        return json.dumps(v, default=str, sort_keys=True)
    return v


def base_row(market: str, r: dict, node_id: str, source_id, drop: tuple = ()) -> dict:
    props = {k: clean(v) for k, v in r.items() if k not in ("id", "_ts") + drop}
    return {"id": node_id, "source_id": str(source_id) if source_id is not None else None,
            "recorded_at": clean(r.get("_ts")), "props": props}


def company_id(market: str, ticker: str | None) -> str:
    return f"{market}:{ticker}"


def holder_id(m: str, cik, name) -> str:
    return f"{m}:cik:{cik}" if cik else f"{m}:name:{slugify_with_unknown_fallback(name)}"


def shape_news(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"], drop=("day",))
    row["props"]["outlet"] = row["props"].pop("source", None)
    row["tickers"], row["day"] = row["props"].get("tickers") or [], clean(r.get("day"))
    row["mentions"] = {k: row["props"].get(k) for k in ("sentiment", "relevance", "materiality", "event_type",
                                                         "novelty", "analyzed_at", "prompt_version")}
    return row


def shape_source(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row["ticker"], row["company_id"] = r.get("ticker"), company_id(m, r.get("ticker"))
    return row


def shape_event(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row["ticker"], row["company_id"] = r.get("ticker"), company_id(m, r.get("ticker"))
    return row


def shape_insider(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:insider:{r['id']}", r["id"], drop=("holder_name", "holder_cik"))
    cat = str(r.get("role") or "").lower()
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, r.get("holder_cik"), r.get("holder_name")), holder_name=r.get("holder_name"),
               holder_cik=r.get("holder_cik"), holder_kind="insider",
               holder_person=bool(r.get("is_director") or r.get("is_officer") or any(p in cat for p in PERSON_CATEGORIES)))
    row["props"]["via"] = "insider"
    return row


def shape_deal(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:deal:{r['id']}", r["id"])
    side = str(r.get("side") or "").lower()
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, None, r.get("client")), holder_name=r.get("client"), holder_cik=None,
               holder_kind="deal_client", holder_person=False)
    row["props"].update(via=str(r.get("deal_type") or "deal").lower(),
                        side="buy" if side.startswith("buy") else "sell" if side.startswith("sell") else side or None)
    return row


def shape_stake(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:stake:{r['id']}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, r.get("filer_cik"), r.get("filer_name")), holder_name=r.get("filer_name"),
               holder_cik=r.get("filer_cik"), holder_kind="stake_filer", holder_person=False)
    row["props"]["via"] = r.get("kind") or r.get("form")
    return row


def shape_13f(m: str, r: dict) -> dict:
    key = f"{r['filer_cik']}|{r['ticker']}|{clean(r['period'])}"
    row = base_row(m, r, f"{m}:13f:{key}", r["id"], drop=("filer_name",))
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, r["filer_cik"], r.get("filer_name")), holder_name=r.get("filer_name"),
               holder_cik=r["filer_cik"], holder_kind="13f_filer", holder_person=False)
    row["props"]["via"] = "13F"
    return row


def shape_shareholding(m: str, r: dict) -> dict:
    key = f"{r['ticker']}|{clean(r['period_end'])}"
    row = base_row(m, r, f"{m}:shp:{key}", ",".join(r["source_ids"] or []))
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]), holder_id=f"{m}:promoters:{r['ticker']}",
               holder_name=f"Promoter group of {r['ticker']}", holder_cik=None, holder_kind="promoter_group",
               holder_person=False)
    row["props"].update(via="shareholding", period=row["props"].get("period_end"))
    return row


def shape_graph(m: str, r: dict) -> dict:
    row = base_row(m, r, r["id"], r["id"])
    row["id"] = f"{m}:graph:{r['id']}"
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]), status=r.get("status") or "active",
               target_ticker=r.get("target_ticker"),
               target_id=company_id(m, r["target_ticker"]) if r.get("target_ticker") else f"{m}:name:{slugify_with_unknown_fallback(r.get('target'))}",
               target_name=r.get("target"), target_person=r.get("target_kind") == "person")
    return row


def shape_prediction(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               evidence=[{"id": f"{m}:{e}", "record_id": e} for e in (r.get("evidence_ids") or []) if e])
    return row


def shape_outcome(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:call:{r['prediction_id']}", r["prediction_id"])
    row["props"]["kind"] = "call"
    row["parent_id"], row["parent_record"] = f"{m}:{r['prediction_id']}", r["prediction_id"]
    return row


def shape_range(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]), prediction_id=f"{m}:{r['id']}")
    return row


def shape_range_outcome(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:range:{r['range_id']}", r["range_id"])
    row["props"]["kind"] = "range"
    row["parent_id"], row["parent_record"] = f"{m}:{r['range_id']}", r["range_id"]
    return row


def shape_market_day(key_fields: tuple) -> Callable[[str, dict], dict]:
    def shape(m: str, r: dict) -> dict:
        key = ":".join(str(clean(r.get(k))) for k in key_fields)
        return base_row(m, r, f"{m}:{key}", r.get("id") or key)
    return shape


def shape_feature(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['ticker']}:{clean(r['as_of_date'])}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]))
    return row


def shape_fundamentals(m: str, r: dict) -> dict:
    key = f"{r['ticker']}:sec:{clean(r['period_end'])}"
    row = base_row(m, r, f"{m}:{key}", f"fundamentals_metrics:{r['ticker']}:{clean(r['period_end'])}")
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]))
    row["props"]["basis"] = "sec_xbrl"
    return row


def shape_financials(m: str, r: dict) -> dict:
    key = f"{r['ticker']}:{r.get('basis')}:{clean(r.get('period_start'))}:{clean(r['period_end'])}"
    row = base_row(m, r, f"{m}:{key}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]))
    return row
