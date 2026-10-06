"""Context-pack sections for the India primary sources collected by collect_nse_india.py:
FII/DII flows, company announcements, latest financial results and delivery %. Empty for
markets without `relations.source: nse`. Used by context.py; numbers come from DuckDB views."""
from __future__ import annotations

from datetime import timedelta

from marketbrief.core.clock import utc_today
from marketbrief.utils.markdown import cursor_markdown_table


def _flows(con) -> str:
    rows = con.execute("""
        WITH d AS (SELECT date, CASE WHEN category ILIKE 'FII%' THEN 'fii' ELSE 'dii' END AS who,
                          TRY_CAST(net_cr AS DECIMAL(38,10)) AS net_cr FROM flows_daily),
             w AS (SELECT date, CAST(sum(net_cr) FILTER (WHERE who = 'fii') AS DOUBLE) AS fii,
                          CAST(sum(net_cr) FILTER (WHERE who = 'dii') AS DOUBLE) AS dii
                   FROM d GROUP BY date ORDER BY date DESC LIMIT 5)
        SELECT * FROM w ORDER BY date DESC""").fetchall()
    if not rows:
        return "_none_\n"
    latest, fii5, dii5 = rows[0], sum(r[1] or 0 for r in rows), sum(r[2] or 0 for r in rows)
    line = (f"Latest {latest[0]}: FII/FPI net {latest[1]:+,.0f} cr, DII net {latest[2]:+,.0f} cr "
            f"(provisional). Last {len(rows)} reported days: FII {fii5:+,.0f} cr, DII {dii5:+,.0f} cr.\n\n")
    table = "| date | fii_net_cr | dii_net_cr |\n|---|---|---|\n" + "".join(
        f"| {d} | {'' if f is None else round(f, 2)} | {'' if x is None else round(x, 2)} |\n" for d, f, x in rows)
    return line + table


def context_sections(cfg: dict, con) -> list[tuple[str, str]]:
    if (cfg.get("relations") or {}).get("source") != "nse":
        return []
    tickers, today = list(cfg["tickers"]), utc_today()
    return [
        ("FII/DII cash-market flows (NSE provisional, INR crore)", _flows(con)),
        ("Company announcements on NSE, last 2 days (primary sources; ids usable as evidence; "
         "sentiment and materiality once the news-analyst has scored them)", cursor_markdown_table(con.execute("""
            SELECT ticker, CAST(published_at AS VARCHAR)[:16] AS published_utc, category,
                   replace(left(subject, 160), '|', '/') AS subject, round(sentiment, 2) AS sentiment,
                   materiality, id
            FROM announcements_enriched
            WHERE published_at >= ? AND list_contains(?, ticker)
            ORDER BY published_at DESC, id LIMIT 40""", [today - timedelta(days=2), tickers]))),
        ("Latest quarterly results (consolidated where filed; INR crore; y/y vs same quarter)",
         cursor_markdown_table(con.execute("""
            SELECT ticker, basis, period_end, round(revenue / 1e7, 0) AS revenue_cr,
                   round(revenue_yoy * 100, 1) AS rev_yoy_pct, round(net_profit / 1e7, 0) AS net_profit_cr,
                   round(net_profit_yoy * 100, 1) AS np_yoy_pct, eps_basic, CAST(filed_at AS DATE) AS filed
            FROM financials_quarterly_yoy WHERE list_contains(?, ticker)
            QUALIFY row_number() OVER (PARTITION BY ticker
                                       ORDER BY period_end DESC, basis = 'consolidated' DESC) = 1
            ORDER BY ticker""", [tickers]))),
        ("Delivery % (latest session vs average of the 20 sessions before; high delivery = positions taken home)",
         cursor_markdown_table(con.execute("""
            SELECT ticker, date, delivery_pct, round(delivery_pct_avg20, 2) AS avg20_pct,
                   round(delivery_pct - delivery_pct_avg20, 2) AS vs_avg_pp, n_prior AS sessions_in_avg
            FROM delivery_stats WHERE list_contains(?, ticker)
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
            ORDER BY ticker""", [tickers]))),
    ]
