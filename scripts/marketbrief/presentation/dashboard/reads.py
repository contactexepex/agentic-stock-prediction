"""Read helpers of the dashboard: every query takes the cut-off time (`cutoff`, ISO UTC) and the as-of
date, so nothing stored after the cut-off and no bar after the as-of date reaches the page. Each picks
rows the way its DuckDB view does (sql/views.sql), with the cut-off added."""

from __future__ import annotations

import pandas as pd

AS_OF_SQL = "SELECT max(as_of_date) FROM features WHERE computed_at <= ?::TIMESTAMPTZ"
# features_latest, as of the cut-off
FEATURES_SQL = """SELECT DISTINCT ON (ticker) * FROM features
                  WHERE as_of_date = ? AND computed_at <= ?::TIMESTAMPTZ ORDER BY ticker, computed_at DESC"""
# the ohlc view (sql/views.sql: ohlc_raw, price_adjustments, bar_factors) rebuilt from the rows stored by the
# cut-off: each bar's newest collection by then, the market's closed days left out, and only the split/bonus
# records detected (and not yet superseded) by then applied
BARS_SQL = """
WITH p AS (SELECT DISTINCT ON (ticker, date) * FROM prices
           WHERE collected_at <= $cutoff::TIMESTAMPTZ AND date <= $as_of AND date > $start
           ORDER BY ticker, date, collected_at DESC),
r AS (SELECT * FROM p WHERE NOT EXISTS (SELECT 1 FROM own_closed_days c WHERE c.ticker = p.ticker AND c.date = p.date)),
a AS (SELECT DISTINCT ON (id) * FROM adjustments WHERE detected_at <= $cutoff::TIMESTAMPTZ
      AND id NOT IN (SELECT supersedes FROM adjustments
                     WHERE supersedes IS NOT NULL AND detected_at <= $cutoff::TIMESTAMPTZ)
      ORDER BY id, detected_at),
f AS (SELECT r.ticker, r.date, coalesce(list_product(list_sort(list(a.factor))), 1.0) AS factor
      FROM r LEFT JOIN a ON a.ticker = r.ticker AND a.ex_date > r.date GROUP BY r.ticker, r.date)
SELECT r.ticker, r.date, r.open * f.factor AS open, r.high * f.factor AS high, r.low * f.factor AS low,
       r.close * f.factor AS close, CAST(round(r.volume / f.factor) AS BIGINT) AS volume
FROM r JOIN f USING (ticker, date) ORDER BY ticker, date"""
# ranges_latest (first stored row per id), as of the cut-off
RANGES_SQL = """SELECT DISTINCT ON (id) * FROM ranges
                WHERE as_of_date = ? AND made_at <= ?::TIMESTAMPTZ ORDER BY id, made_at"""
# model_scores_latest, as of the cut-off
SCORES_SQL = """SELECT DISTINCT ON (id) * FROM model_scores
                WHERE as_of_date = ? AND computed_at <= ?::TIMESTAMPTZ
                ORDER BY id, computed_at DESC, prob_up, model_id"""
# model_versions_latest, as of the cut-off
VERSIONS_SQL = """SELECT DISTINCT ON (id) * FROM model_versions WHERE fitted_at <= ?::TIMESTAMPTZ
                  ORDER BY id, fitted_at DESC, CAST(model AS VARCHAR), platt_rows"""
REASONING_SQL = """SELECT DISTINCT ON (ticker) * FROM agent_reasoning
                   WHERE as_of_date = ? AND written_at <= ?::TIMESTAMPTZ ORDER BY ticker, written_at DESC, id"""
NEWS_SQL = """WITH n AS (SELECT DISTINCT ON (id) * FROM news_asof(?::TIMESTAMPTZ)
                         ORDER BY id, first_seen_at),
              t AS (SELECT id, title, url, source, coalesce(published_at, first_seen_at) AS ts,
                           unnest(tickers) AS ticker FROM n)
              SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY ts DESC, id) AS k
                             FROM t WHERE ts <= ?::TIMESTAMPTZ)
              WHERE k <= ? ORDER BY ticker, ts DESC, id"""
NEWS_BY_ID_SQL = """SELECT DISTINCT ON (id) id, title, url, source, coalesce(published_at, first_seen_at) AS ts
                    FROM news_lookup_asof(?::TIMESTAMPTZ) ORDER BY id, first_seen_at"""
# the company_events view (latest known date per ticker and type, "_history" sources left out) built from the
# event rows first seen by the cut-off; the next earnings date is that date when it is after the as-of date
EARNINGS_SQL = """
SELECT ticker, date FROM (
  SELECT DISTINCT ON (ticker, type) * FROM events
  WHERE ticker IS NOT NULL AND NOT ends_with(coalesce(source, ''), '_history') AND first_seen_at <= $cutoff::TIMESTAMPTZ
  ORDER BY ticker, type, first_seen_at DESC, date)
WHERE type = $kind AND date > $as_of ORDER BY ticker"""
REGIME_SQL = """SELECT * FROM regime WHERE as_of_date <= ? AND computed_at <= ?::TIMESTAMPTZ
                ORDER BY as_of_date DESC, computed_at DESC LIMIT 1"""
QUOTES_SQL = """SELECT DISTINCT ON (symbol) symbol, price, prev_close, change_pct, ts, collected_at FROM quotes
                WHERE collected_at <= ?::TIMESTAMPTZ ORDER BY symbol, collected_at DESC"""
REVIEW_SQL = "SELECT * FROM reviews WHERE computed_at <= ?::TIMESTAMPTZ ORDER BY computed_at DESC, id LIMIT 1"
REPLAY_SQL = "SELECT * FROM replays WHERE computed_at <= ?::TIMESTAMPTZ ORDER BY computed_at DESC, id LIMIT 1"
PREDICTIONS_SQL = """SELECT DISTINCT ON (id) * FROM predictions
                     WHERE as_of_date = ? AND made_at <= ?::TIMESTAMPTZ ORDER BY id, made_at"""


def frame(con, sql: str, params: list | dict | None = None) -> pd.DataFrame:
    """A query result as a DataFrame; an empty frame when the view is missing (no such files yet)."""
    try:
        return con.execute(sql, params or []).df()
    except Exception as exc:  # duckdb raises CatalogException for a missing view or macro
        if "Catalog" in type(exc).__name__ or "does not exist" in str(exc):
            return pd.DataFrame()
        raise


def as_of_date(con, cutoff: str):
    """The newest indicator snapshot date stored by the cut-off, or None."""
    value = con.execute(AS_OF_SQL, [cutoff]).fetchone()[0]
    return None if value is None or pd.isna(value) else pd.Timestamp(value).date()


def features(con, as_of, cutoff: str) -> pd.DataFrame:
    """One indicator row per ticker for the as-of date."""
    return frame(con, FEATURES_SQL, [as_of, cutoff])


def bars(con, as_of, start, cutoff: str) -> pd.DataFrame:
    """Split-adjusted daily OHLC bars after `start` up to and including the as-of date, as stored by the cut-off."""
    return frame(con, BARS_SQL, {"as_of": as_of, "start": start, "cutoff": cutoff})


def ranges(con, as_of, cutoff: str) -> pd.DataFrame:
    """The published ranges of the as-of date."""
    return frame(con, RANGES_SQL, [as_of, cutoff])


def scores(con, as_of, cutoff: str) -> pd.DataFrame:
    """The signal model's scores of the as-of date."""
    return frame(con, SCORES_SQL, [as_of, cutoff])


def versions(con, cutoff: str) -> pd.DataFrame:
    """The stored model fits (formula, Platt calibration) known by the cut-off."""
    return frame(con, VERSIONS_SQL, [cutoff])


def reasoning(con, as_of, cutoff: str) -> pd.DataFrame:
    """The forecaster's bull case, bear case and verdict per ticker for the as-of date."""
    return frame(con, REASONING_SQL, [as_of, cutoff])


def predictions(con, as_of, cutoff: str) -> pd.DataFrame:
    """The forecaster's calls of the as-of date."""
    return frame(con, PREDICTIONS_SQL, [as_of, cutoff])


def news(con, cutoff: str, per_ticker: int) -> pd.DataFrame:
    """The newest headlines per ticker published and stored by the cut-off."""
    return frame(con, NEWS_SQL, [cutoff, cutoff, per_ticker])


def news_by_id(con, cutoff: str) -> pd.DataFrame:
    """Every item stored by the cut-off with its headline then, under each of its ids (for the ids the agents
    cite; a stored duplicate's id gives its item)."""
    return frame(con, NEWS_BY_ID_SQL, [cutoff])


def earnings(con, kind: str, as_of, cutoff: str) -> dict:
    """ticker -> the next earnings date after the as-of date, as known by the cut-off."""
    rows = frame(con, EARNINGS_SQL, {"kind": kind, "as_of": as_of, "cutoff": cutoff})
    return {r.ticker: pd.Timestamp(r.date).date() for r in rows.itertuples()}


def regime(con, as_of, cutoff: str) -> dict | None:
    """The newest regime row on or before the as-of date."""
    rows = frame(con, REGIME_SQL, [as_of, cutoff])
    return None if rows.empty else rows.iloc[0].to_dict()


def quotes(con, cutoff: str) -> pd.DataFrame:
    """The newest quote per symbol collected by the cut-off."""
    return frame(con, QUOTES_SQL, [cutoff])


def review(con, cutoff: str) -> dict | None:
    """The newest weekly review record computed by the cut-off."""
    rows = frame(con, REVIEW_SQL, [cutoff])
    return None if rows.empty else rows.iloc[0].to_dict()


def replay(con, cutoff: str) -> dict | None:
    """The newest historical replay record computed by the cut-off."""
    rows = frame(con, REPLAY_SQL, [cutoff])
    return None if rows.empty else rows.iloc[0].to_dict()
