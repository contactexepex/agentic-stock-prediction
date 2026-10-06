"""The projected kinds: read query, shaper and statements of each."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from marketbrief.graph.neo4j.cypher import (
    company_node_statement,
    holder_statement,
    market_node_statement,
    scored_statement,
    source_statement,
)
from marketbrief.graph.neo4j.shapes import (
    clean,
    company_id,
    shape_13f,
    shape_deal,
    shape_event,
    shape_feature,
    shape_financials,
    shape_fundamentals,
    shape_graph,
    shape_insider,
    shape_market_day,
    shape_news,
    shape_outcome,
    shape_prediction,
    shape_range,
    shape_range_outcome,
    shape_shareholding,
    shape_source,
    shape_stake,
)
from marketbrief.graph.neo4j.statements import (
    CONFIG_STATEMENTS,
    EVENTS_CURRENT,
    EVENT_STATEMENTS,
    GRAPH_STATEMENTS,
    HOLDINGS_13F_SQL,
    INSIDERS_SQL,
    NEWS_SQL,
    NEWS_STATEMENT,
    PREDICTION_STATEMENT,
    RANGE_STATEMENT,
    SHAREHOLDING_SQL,
)


@dataclass
class Kind:
    name: str
    sql: str | None  # rows come from DuckDB (must expose _ts) ...
    statements: list[tuple[str, Callable[[dict], bool] | None]]
    shape: Callable[[str, dict], dict]  # DuckDB row -> parameter row
    incremental: bool = True  # False: derived view, all rows every run
    rows_fn: Callable | None = None  # ... or from the market config


# config: Market, Sector, Company
def config_rows(cfg: dict, _con, _since) -> list[dict]:
    market, src = cfg["market"], f"config/markets/{cfg['market']}.yaml"
    rows = [
        {
            "id": market,
            "source_id": src,
            "recorded_at": None,
            "node": "market",
            "props": {key: clean(cfg.get(key)) for key in ("name", "timezone", "currency", "calendar")},
        }
    ]
    for ticker, meta in sorted(cfg["tickers"].items()):
        rows.append(
            {
                "id": company_id(market, ticker),
                "ticker": ticker,
                "source_id": src,
                "recorded_at": None,
                "node": "company",
                "sector_id": f"{market}:{meta['sector']}" if meta.get("sector") else None,
                "sector": meta.get("sector"),
                "sector_etf": meta.get("sector_etf"),
                "props": {
                    "name": meta.get("name"),
                    "yahoo": meta.get("yahoo"),
                    "sector": meta.get("sector"),
                    "ticker": ticker,
                    "watchlist": True,
                },
            }
        )
    return rows


def events_current_rows(cfg: dict, con, _since) -> list[dict]:
    ids = [row[0] for row in con.execute("SELECT id FROM company_events ORDER BY id").fetchall()]
    return [{"id": f"{cfg['market']}:events_current", "ids": ids, "source_id": "company_events", "recorded_at": None}]


def keep_stored_row(_market: str, stored_row: dict) -> dict:
    """Shaper of the kinds whose rows come ready-made from their rows function."""
    return stored_row


KINDS: list[Kind] = [
    Kind("config", None, CONFIG_STATEMENTS, keep_stored_row, incremental=False, rows_fn=config_rows),
    Kind("news", NEWS_SQL, [(NEWS_STATEMENT, None)], shape_news),
    Kind(
        "filings",
        "SELECT DISTINCT ON (id) *, first_seen_at AS _ts FROM filings ORDER BY id, first_seen_at",
        [(source_statement("Filing", ("filing_date",), ("accepted_at", "first_seen_at")), None)],
        shape_source,
    ),
    Kind(
        "announcements",
        "SELECT *, greatest(first_seen_at, analyzed_at) AS _ts FROM announcements_enriched",
        [(source_statement("Announcement", (), ("published_at", "first_seen_at", "analyzed_at")), None)],
        shape_source,
    ),
    Kind(
        "events",
        "SELECT DISTINCT ON (id) *, first_seen_at AS _ts FROM events ORDER BY id, first_seen_at",
        EVENT_STATEMENTS,
        shape_event,
    ),
    Kind(
        "events_current",
        None,
        [(EVENTS_CURRENT, None)],
        keep_stored_row,
        incremental=False,
        rows_fn=events_current_rows,
    ),
    Kind(
        "insiders",
        INSIDERS_SQL,
        [
            (
                holder_statement(
                    "TRADED", ("trade_date", "trade_to", "filing_date"), ("disclosed_at", "first_seen_at")
                ),
                None,
            )
        ],
        shape_insider,
    ),
    Kind(
        "deals",
        "SELECT *, first_seen_at AS _ts FROM deals_scored",
        [(holder_statement("TRADED", ("date",), ("first_seen_at",)), None)],
        shape_deal,
    ),
    Kind(
        "stakes",
        "SELECT *, first_seen_at AS _ts FROM stake_filings",
        [(holder_statement("HOLDS", ("filing_date", "event_date"), ("accepted_at", "first_seen_at")), None)],
        shape_stake,
    ),
    Kind(
        "holdings_13f",
        HOLDINGS_13F_SQL,
        [(holder_statement("HOLDS", ("period", "prev_period"), ()), None)],
        shape_13f,
        incremental=False,
    ),
    Kind(
        "shareholding",
        SHAREHOLDING_SQL,
        [(holder_statement("HOLDS", ("period", "period_end", "prev_period"), ("filed_at",)), None)],
        shape_shareholding,
        incremental=False,
    ),
    Kind(
        "graph",
        "SELECT DISTINCT ON (id) *, added_at AS _ts FROM graph ORDER BY id, added_at DESC",
        GRAPH_STATEMENTS,
        shape_graph,
    ),
    Kind(
        "predictions",
        "SELECT DISTINCT ON (id) *, made_at AS _ts FROM predictions ORDER BY id, made_at",
        [(PREDICTION_STATEMENT, None)],
        shape_prediction,
    ),
    Kind(
        "outcomes",
        "SELECT DISTINCT ON (prediction_id) *, scored_at AS _ts FROM outcomes ORDER BY prediction_id, scored_at",
        [(scored_statement("Prediction", ("base_date", "target_date"), "r.hit = row.props.hit, "), None)],
        shape_outcome,
    ),
    Kind("ranges", "SELECT *, made_at AS _ts FROM ranges_latest", [(RANGE_STATEMENT, None)], shape_range),
    Kind(
        "range_outcomes",
        "SELECT DISTINCT ON (range_id) *, scored_at AS _ts FROM range_outcomes ORDER BY range_id, scored_at",
        [(scored_statement("Range", ("target_date",), "r.hit50 = row.props.hit50, r.hit80 = row.props.hit80, "), None)],
        shape_range_outcome,
    ),
    Kind(
        "regime",
        "SELECT *, computed_at AS _ts FROM regime_latest",
        [(market_node_statement("RegimeDay", "HAS_REGIME", ("as_of_date", "session_date"), ("computed_at",)), None)],
        shape_market_day(("as_of_date",)),
    ),
    Kind(
        "features",
        "SELECT *, computed_at AS _ts FROM features_latest",
        [
            (
                company_node_statement(
                    "FeatureDay", "HAS_FEATURES", ("as_of_date", "ex_dividend_date"), ("computed_at",)
                ),
                None,
            )
        ],
        shape_feature,
    ),
    Kind(
        "judgments",
        "SELECT DISTINCT ON (id) *, recorded_at AS _ts FROM judgments ORDER BY id, recorded_at",
        [(market_node_statement("Judgment", "HAS_JUDGMENT", ("run_date",), ("recorded_at",)), None)],
        shape_market_day(("id",)),
    ),
    Kind(
        "fundamentals",
        "SELECT *, CAST(filing_date AS TIMESTAMPTZ) AS _ts FROM fundamentals_metrics",
        [
            (
                company_node_statement(
                    "FinancialPeriod", "REPORTED", ("period_end", "filing_date", "yoy_period_end"), ()
                ),
                None,
            )
        ],
        shape_fundamentals,
        incremental=False,
    ),
    Kind(
        "financials",
        "SELECT *, first_seen_at AS _ts FROM financials_latest",
        [
            (
                company_node_statement(
                    "FinancialPeriod", "REPORTED", ("period_start", "period_end"), ("filed_at", "first_seen_at")
                ),
                None,
            )
        ],
        shape_financials,
    ),
    Kind(
        "flows",
        "SELECT *, first_seen_at AS _ts FROM flows_daily",
        [(market_node_statement("FlowDay", "HAS_FLOW", ("date",), ("first_seen_at",)), None)],
        shape_market_day(("date", "category")),
    ),
]
