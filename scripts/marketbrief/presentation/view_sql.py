"""The SQL of view_data.gather_view (moved out of view_data.py to keep it under the size limit; view_data re-exports
the names other modules import). The stored-row reads are bounded by now(): the run's clock, frozen to MB_NOW by
core.database.connect, so a page rebuilt as of a past time never sees rows stored later (C2)."""
from __future__ import annotations

from marketbrief.constants.horizon_names import BASIS_KEY_SQL

# calls by stated-confidence band (exact decimal average: no dependence on row order) and the scored
# calls in a fixed order for scoring.call_scores / reliability (docs/REFACTOR_PLAN.md, nondeterminism)
# (per scoring basis key, never pooled: analytics/call_basis.py; {src} = the track record as of the day's made_at)
BANDS_SQL = f"""SELECT CASE WHEN confidence < 0.6 THEN '50-59%' WHEN confidence < 0.7 THEN '60-69%'
                          WHEN confidence < 0.8 THEN '70-79%' ELSE '80-90%' END AS band, {BASIS_KEY_SQL} AS label_basis,
                     count(*) AS n, avg(TRY_CAST(confidence AS DECIMAL(38,10))) AS conf, avg(hit::INT) AS hit
              FROM {{src}} GROUP BY ALL ORDER BY band, label_basis"""
SCORED_CALLS_SQL = ("SELECT confidence, hit FROM {src} WHERE confidence IS NOT NULL AND hit IS NOT NULL "
                    f"AND {BASIS_KEY_SQL} = ? ORDER BY id, scored_at")
# the same for report.py: its confidence bands, and range_record with the averaged % columns as exact decimals
CONF_BANDS_SQL = f"""SELECT CASE WHEN confidence < 0.6 THEN '0.50-0.59' WHEN confidence < 0.7 THEN '0.60-0.69'
                               WHEN confidence < 0.8 THEN '0.70-0.79' ELSE '0.80-0.90' END AS band,
                          {BASIS_KEY_SQL} AS label_basis, count(*) AS n,
                          avg(TRY_CAST(confidence AS DECIMAL(38,10))) AS conf, avg(hit::INT) AS hit
                   FROM track_record GROUP BY ALL ORDER BY band, label_basis"""
EXACT_COLUMNS = ("width80_pct", "naive_width80_pct", "is80_pct", "naive_is80_pct", "center_err_pct",
                 "naive_center_err_pct")
RANGE_RECORD_EXACT = ("(SELECT * REPLACE ("
                      + ", ".join(f"TRY_CAST({c} AS DECIMAL(38,10)) AS {c}" for c in EXACT_COLUMNS)
                      + ") FROM range_record)")

# the day's published ranges, regime, indicator snapshots, AI calls, filings and announcements, stored by the clock
RANGES_SQL = """SELECT * FROM ranges_latest WHERE made_at <= now()
                AND as_of_date = (SELECT max(as_of_date) FROM ranges_latest WHERE made_at <= now())"""
REGIME_SQL = "SELECT * FROM regime WHERE computed_at <= now() ORDER BY as_of_date DESC, computed_at DESC LIMIT 1"
FEATURES_SQL = """SELECT DISTINCT ON (ticker) * FROM features WHERE as_of_date = ? AND computed_at <= now()
                  ORDER BY ticker, computed_at DESC"""
PREDICTIONS_SQL = """SELECT DISTINCT ON (id) * FROM predictions WHERE as_of_date = ? AND made_at <= now()
                     ORDER BY id, made_at"""
FILINGS_SQL = ("SELECT DISTINCT ON (id) id, ticker, form, url, accepted_at, description FROM filings "
               "WHERE first_seen_at <= now() ORDER BY id, first_seen_at, ticker, form, url, accepted_at, description")
ANNOUNCEMENTS_SQL = ("SELECT id, ticker, subject, url, published_at, source FROM announcements_latest "
                     "WHERE first_seen_at <= now() ORDER BY id")
# the company events of the next weeks: sql/views.sql company_events (the newest row per ticker and type, history rows
# left out) over the rows first seen by the clock, so an event collected later never shows on an earlier page
COMPANY_EVENTS_SQL = """SELECT date, type, ticker, name, amount FROM (
    SELECT DISTINCT ON (ticker, type) * FROM events
    WHERE ticker IS NOT NULL AND NOT ends_with(coalesce(source, ''), '_history') AND first_seen_at <= now()
    ORDER BY ticker, type, first_seen_at DESC, date)
WHERE date BETWEEN ? AND ? ORDER BY date, ticker, type, name"""
