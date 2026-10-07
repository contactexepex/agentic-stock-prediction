"""The mirrored tables: what the cockpit needs from a market's DuckDB views, each rebuilt as of the run's
cut-off time (MB_NOW-aware) so nothing stored after it reaches the warehouse. Each query picks rows the way
its view in sql/views.sql does, with the cut-off added on the column that says when a row was stored; the
bars reuse the dashboard's cut-off-aware ohlc query (presentation/dashboard/reads.py)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from marketbrief.presentation.dashboard import reads

BARS_START = date(1900, 1, 1)
# a plain http(s) link or NULL (view_data.safe_url in SQL): feed links are stored unchecked
SAFE_URL_SQL = "CASE WHEN regexp_full_match(trim({col}), '(?i)https?://\\S+') THEN trim({col}) END"


@dataclass(frozen=True)
class Table:
    """One mirrored table: its name in the market's schema and the query that builds it ($cutoff)."""

    name: str
    sql: str
    what: str


TABLES = (
    Table(
        "quotes_latest",
        """SELECT DISTINCT ON (symbol) * FROM quotes WHERE collected_at <= $cutoff
           ORDER BY symbol, collected_at DESC""",
        "newest quote per symbol",
    ),
    Table(
        "features",
        """SELECT DISTINCT ON (ticker, as_of_date) * FROM features WHERE computed_at <= $cutoff
           ORDER BY ticker, as_of_date, computed_at DESC""",
        "indicator snapshots, newest per ticker and as-of date (features_latest)",
    ),
    Table(
        "regime",
        """SELECT DISTINCT ON (as_of_date) * FROM regime WHERE computed_at <= $cutoff
           ORDER BY as_of_date, computed_at DESC""",
        "market regime per as-of date (regime_latest)",
    ),
    Table(
        "predictions",
        """SELECT DISTINCT ON (id) * FROM predictions WHERE made_at <= $cutoff ORDER BY id, made_at""",
        "the forecaster's calls, first row per id",
    ),
    Table(
        "track_record",
        """WITH p AS (SELECT DISTINCT ON (id) * FROM predictions WHERE made_at <= $cutoff ORDER BY id, made_at),
           o AS (SELECT DISTINCT ON (prediction_id) * FROM outcomes WHERE scored_at <= $cutoff
                 ORDER BY prediction_id, scored_at)
           SELECT p.*, o.base_date, o.target_date, o.actual_return, o.hit, o.scored_at,
                  coalesce(o.label_basis, 'close_to_close') AS label_basis, o.entry_date, o.entry_open
           FROM p JOIN o ON o.prediction_id = p.id ORDER BY p.id""",
        "scored calls with label_basis (track_record)",
    ),
    Table(
        "track_summary",
        """WITH p AS (SELECT DISTINCT ON (id) * FROM predictions WHERE made_at <= $cutoff ORDER BY id, made_at),
           o AS (SELECT DISTINCT ON (prediction_id) * FROM outcomes WHERE scored_at <= $cutoff
                 ORDER BY prediction_id, scored_at)
           SELECT coalesce(o.label_basis, 'close_to_close') AS label_basis, p.horizon_days,
                  count(*) AS calls, count(*) FILTER (WHERE o.hit) AS hits,
                  count(*) FILTER (WHERE o.hit) / count(*) AS hit_rate, avg(p.confidence) AS mean_confidence
           FROM p JOIN o ON o.prediction_id = p.id GROUP BY ALL ORDER BY label_basis, p.horizon_days""",
        "hit rate per label basis and horizon, the two bases never pooled",
    ),
    Table(
        "ranges",
        """SELECT DISTINCT ON (id) * FROM ranges WHERE made_at <= $cutoff ORDER BY id, made_at""",
        "published ranges, first row per id (ranges_latest)",
    ),
    Table(
        "range_record",
        """WITH r AS (SELECT DISTINCT ON (id) * FROM ranges WHERE made_at <= $cutoff ORDER BY id, made_at),
           o AS (SELECT DISTINCT ON (range_id) * FROM range_outcomes WHERE scored_at <= $cutoff
                 ORDER BY range_id, scored_at)
           SELECT r.*, o.actual_close, o.z, o.hit50, o.hit80, o.naive_hit50, o.naive_hit80, o.is80_pct,
                  o.width80_pct, o.center_err_pct, o.scored_at
           FROM r JOIN o ON o.range_id = r.id ORDER BY r.id""",
        "scored ranges (range_record)",
    ),
    Table(
        "model_scores_latest",
        """SELECT DISTINCT ON (id) * FROM model_scores WHERE computed_at <= $cutoff
           ORDER BY id, computed_at DESC, prob_up, model_id""",
        "the signal model's newest P(up) per id",
    ),
    Table(
        "model_versions",
        """SELECT DISTINCT ON (id) * FROM model_versions WHERE fitted_at <= $cutoff
           ORDER BY id, fitted_at DESC, CAST(model AS VARCHAR), platt_rows""",
        "stored model fits (model_versions_latest)",
    ),
    Table(
        "news",
        f"""WITH n AS (SELECT DISTINCT ON (id) * FROM news_asof($cutoff) ORDER BY id, first_seen_at),
           t AS (SELECT n.*, coalesce(n.published_at, n.first_seen_at) AS ts,
                        unnest(CASE WHEN len(n.tickers) > 0 THEN n.tickers ELSE [NULL] END) AS ticker FROM n),
           e AS (SELECT * FROM news_enriched_asof($cutoff)),
           s AS (SELECT * FROM news_status_ids_asof($cutoff))
           SELECT t.id, t.ticker,
                  CASE WHEN list_contains(t.primary_tickers, t.ticker) THEN 'primary' ELSE 'mentioned' END AS role,
                  t.title, {SAFE_URL_SQL.format(col="t.url")} AS url, t.source, t.source_domain, t.category,
                  t.published_at, t.first_seen_at, t.ts, t.tag_confidence,
                  e.relevance, e.sentiment, e.novelty, e.materiality, e.event_type, e.urgency, e.priced_in,
                  e.summary, coalesce(s.status, 'unverified') AS status
           FROM t LEFT JOIN e USING (id) LEFT JOIN s ON s.news_id = t.id AND s.ticker = t.ticker
           WHERE t.ts <= $cutoff ORDER BY t.ticker NULLS FIRST, t.ts DESC, t.id""",
        "headlines per ticker with enrichment and verification status as of the cut-off",
    ),
    Table(
        "news_verified",
        """SELECT * FROM news_verified_asof($cutoff) ORDER BY cluster_id, coalesce(claim_id, ''), id""",
        "event and fact statuses as of the cut-off (news_verified_asof)",
    ),
    Table(
        "events",
        """SELECT DISTINCT ON (id) * FROM events WHERE first_seen_at <= $cutoff ORDER BY id, first_seen_at""",
        "scheduled and company events, first row per id (event_history plus market events)",
    ),
    Table(
        "company_events",
        """SELECT DISTINCT ON (ticker, type) * FROM events
           WHERE ticker IS NOT NULL AND NOT ends_with(coalesce(source, ''), '_history') AND first_seen_at <= $cutoff
           ORDER BY ticker, type, first_seen_at DESC, date""",
        "latest known date per ticker and event type (company_events)",
    ),
    Table(
        "agent_reasoning",
        """SELECT DISTINCT ON (as_of_date, ticker) * FROM agent_reasoning WHERE written_at <= $cutoff
           ORDER BY as_of_date, ticker, written_at DESC, id""",
        "bull case, bear case and verdict per ticker and as-of date",
    ),
    Table(
        "lessons",
        """SELECT DISTINCT ON (id) * FROM lessons WHERE written_at <= $cutoff AND available_from <= $cutoff
           ORDER BY id, written_at""",
        "the reflection log, lessons available by the cut-off",
    ),
    Table(
        "reviews",
        """SELECT * FROM reviews WHERE computed_at <= $cutoff ORDER BY computed_at, id""",
        "weekly reviews (model_skill)",
    ),
)


def tickers_frame(cfg: dict) -> pd.DataFrame:
    """The watchlist from the market config: ticker, name, sector, position in the config."""
    sector_of = {t: s for s, members in (cfg.get("sectors") or {}).items() for t in members}
    rows = [
        {
            "ticker": t,
            "name": (meta or {}).get("name", t),
            "sector": sector_of.get(t),
            "market": cfg["market"],
            "currency": cfg.get("currency"),
            "position": i,
        }
        for i, (t, meta) in enumerate(cfg["tickers"].items())
    ]
    return pd.DataFrame(rows, columns=["ticker", "name", "sector", "market", "currency", "position"])


def table_queries(cutoff: str) -> list[tuple[str, str, dict]]:
    """(name, SQL, parameters) of every mirrored table but the watchlist, as of the cut-off (ISO UTC). The
    bars are the dashboard's ohlc query with no start and every bar stored by the cut-off."""
    cutoff_day = pd.Timestamp(cutoff).date()
    bars_params = {"as_of": cutoff_day + timedelta(days=1), "start": BARS_START, "cutoff": cutoff}
    out = [("bars", reads.BARS_SQL, bars_params)]
    for table in TABLES:
        out.append((table.name, table.sql.replace("$cutoff", "$cutoff::TIMESTAMPTZ"), {"cutoff": cutoff}))
    return out


def stage_tables(cfg: dict, con, cutoff: str, folder) -> dict[str, int]:
    """Write every mirrored table as <folder>/<name>.parquet (column types kept); name -> row count."""
    counts = {}
    con.register("_warehouse_tickers", tickers_frame(cfg))
    queries = [("tickers", "SELECT * FROM _warehouse_tickers ORDER BY position", {}), *table_queries(cutoff)]
    for name, sql, params in queries:
        path = (folder / f"{name}.parquet").as_posix()
        con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet)", params)
        counts[name] = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
    con.unregister("_warehouse_tickers")
    return counts


def count_tables(cfg: dict, con, cutoff: str) -> dict[str, int]:
    """The row count of every mirrored table, writing nothing (dry run)."""
    counts = {"tickers": len(tickers_frame(cfg))}
    for name, sql, params in table_queries(cutoff):
        counts[name] = con.execute(f"SELECT count(*) FROM ({sql})", params).fetchone()[0]
    return counts
