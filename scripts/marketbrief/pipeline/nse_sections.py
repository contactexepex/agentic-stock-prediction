"""Context-pack sections for the India primary sources collected by collect_nse_india.py:
FII/DII flows, company announcements, latest financial results and delivery %. Empty for
markets without `relations.source: nse`. Used by context.py; numbers come from DuckDB views."""

from __future__ import annotations

from datetime import timedelta

from marketbrief.constants.nse_collection import (
    DELIVERY_WINDOW,
    MSG_PENDING_TICKERS,
    MSG_WHAT_RESULTS,
    MSG_WHAT_SHAREHOLDING,
    MSG_YOY_PENDING,
)
from marketbrief.core.clock import utc_today
from marketbrief.utils.markdown import cursor_markdown_table
from marketbrief.lifecycle.loader import active_tickers


def _flows(con) -> str:
    """The FII/DII flows section of the India context."""
    rows = con.execute("""
        WITH d AS (SELECT date, CASE WHEN category ILIKE 'FII%' THEN 'fii' ELSE 'dii' END AS who,
                          TRY_CAST(net_cr AS DECIMAL(38,10)) AS net_cr FROM flows_daily),
             w AS (SELECT date, CAST(sum(net_cr) FILTER (WHERE who = 'fii') AS DOUBLE) AS fii,
                          CAST(sum(net_cr) FILTER (WHERE who = 'dii') AS DOUBLE) AS dii
                   FROM d GROUP BY date ORDER BY date DESC LIMIT 5)
        SELECT * FROM w ORDER BY date DESC""").fetchall()
    if not rows:
        return "_none_\n"
    latest, fii5, dii5 = rows[0], sum(row[1] or 0 for row in rows), sum(row[2] or 0 for row in rows)
    line = (
        f"Latest {latest[0]}: FII/FPI net {latest[1]:+,.0f} cr, DII net {latest[2]:+,.0f} cr "
        f"(provisional). Last {len(rows)} reported days: FII {fii5:+,.0f} cr, DII {dii5:+,.0f} cr.\n\n"
    )
    table = "| date | fii_net_cr | dii_net_cr |\n|---|---|---|\n" + "".join(
        f"| {day} | {'' if fii_net is None else round(fii_net, 2)} | {'' if dii_net is None else round(dii_net, 2)} |\n"
        for day, fii_net, dii_net in rows
    )
    return line + table


def _coverage_notes(con, tickers: list[str]) -> str:
    """Partial-data notes of the results table (issue #12): blank y/y and tickers still pending."""
    blank_yoy = con.execute(
        """SELECT count(DISTINCT ticker) FROM financials_quarterly_yoy
           WHERE list_contains(?, ticker) AND revenue_yoy IS NULL AND net_profit_yoy IS NULL""",
        [tickers],
    ).fetchone()[0]
    with_results = {row[0] for row in con.execute("SELECT DISTINCT ticker FROM financials_latest").fetchall()}
    with_holdings = {row[0] for row in con.execute("SELECT DISTINCT ticker FROM holdings_quarterly").fetchall()}
    notes = []
    if blank_yoy:
        notes.append(MSG_YOY_PENDING.format(n=blank_yoy))
    for what, have in ((MSG_WHAT_RESULTS, with_results), (MSG_WHAT_SHAREHOLDING, with_holdings)):
        pending = [ticker for ticker in tickers if ticker not in have]
        if pending:
            notes.append(MSG_PENDING_TICKERS.format(what=what, n=len(pending), total=len(tickers),
                                                    tickers=", ".join(pending)))
    return "".join(f"_{note}_\n\n" for note in notes)


def _delivery_title(con, tickers: list[str]) -> str:
    """The delivery section title with the real number of sessions in the average (issue #12)."""
    low, high = con.execute(
        """SELECT min(n_prior), max(n_prior) FROM (SELECT n_prior FROM delivery_stats WHERE list_contains(?, ticker)
           QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1)""",
        [tickers],
    ).fetchone()
    if low is None or low == high == DELIVERY_WINDOW:
        sessions = f"the {DELIVERY_WINDOW} sessions before"
    else:
        span = str(high) if low == high else f"{low}-{high}"
        sessions = f"the {span} stored sessions before (up to {DELIVERY_WINDOW}; `sessions_in_avg` per ticker)"
    return f"Delivery % (latest session vs average of {sessions}; high delivery = positions taken home)"


def context_sections(cfg: dict, con) -> list[tuple[str, str]]:
    """The NSE announcement, results, delivery and flows sections."""
    if (cfg.get("relations") or {}).get("source") != "nse":
        return []
    tickers, today = active_tickers(cfg), utc_today()
    return [
        ("FII/DII cash-market flows (NSE provisional, INR crore)", _flows(con)),
        (
            "Company announcements on NSE, last 2 days (primary sources; ids usable as evidence; "
            "sentiment and materiality once the news-analyst has scored them)",
            cursor_markdown_table(
                con.execute(
                    """
            SELECT ticker, CAST(published_at AS VARCHAR)[:16] AS published_utc, category,
                   replace(left(subject, 160), '|', '/') AS subject, round(sentiment, 2) AS sentiment,
                   materiality, id
            FROM announcements_enriched
            WHERE published_at >= ? AND list_contains(?, ticker)
            ORDER BY published_at DESC, id LIMIT 40""",
                    [today - timedelta(days=2), tickers],
                )
            ),
        ),
        (
            "Latest quarterly results (consolidated where filed; INR crore; y/y vs same quarter)",
            _coverage_notes(con, tickers)
            + cursor_markdown_table(
                con.execute(
                    """
            SELECT ticker, basis, period_end, round(revenue / 1e7, 0) AS revenue_cr,
                   round(revenue_yoy * 100, 1) AS rev_yoy_pct, round(net_profit / 1e7, 0) AS net_profit_cr,
                   round(net_profit_yoy * 100, 1) AS np_yoy_pct, eps_basic, CAST(filed_at AS DATE) AS filed
            FROM financials_quarterly_yoy WHERE list_contains(?, ticker)
            QUALIFY row_number() OVER (PARTITION BY ticker
                                       ORDER BY period_end DESC, basis = 'consolidated' DESC) = 1
            ORDER BY ticker""",
                    [tickers],
                )
            ),
        ),
        (
            _delivery_title(con, tickers),
            cursor_markdown_table(
                con.execute(
                    """
            SELECT ticker, date, delivery_pct, round(delivery_pct_avg20, 2) AS avg20_pct,
                   round(delivery_pct - delivery_pct_avg20, 2) AS vs_avg_pp, n_prior AS sessions_in_avg
            FROM delivery_stats WHERE list_contains(?, ticker)
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
            ORDER BY ticker""",
                    [tickers],
                )
            ),
        ),
    ]
