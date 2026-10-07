"""Context-pack sections for the free market-wide sources (issue #9): "Macro & flows" (US:
Treasury curve, FRED credit spreads, Cboe put/call ratios; India: NSDL FPI investment and NSE
index closes with valuation) and, US, "Short selling (FINRA)". Each section appears only when its
market's config has the collector's section. Numbers come from the DuckDB views in sql/views.sql."""

from __future__ import annotations

from marketbrief.utils.markdown import cursor_markdown_table
from marketbrief.lifecycle.loader import active_tickers

# The order series are listed in; others follow alphabetically.
US_ORDER = ["UST_3M", "UST_2Y", "UST_5Y", "UST_10Y", "UST_30Y", "UST_10Y_2Y", "UST_10Y_3M"]
US_SHOWN = {"UST_3M", "UST_2Y", "UST_5Y", "UST_10Y", "UST_30Y", "UST_10Y_2Y", "UST_10Y_3M"}


def _us_macro(con) -> str:
    """Yields and spreads change in basis points, ratios in points, index levels in %."""
    rows = con.execute(
        """
        SELECT series, name, unit, date, value, chg_1, chg_5, date_5,
               CASE WHEN unit = 'index' THEN value - chg_1 END AS prev_1,
               CASE WHEN unit = 'index' THEN value - chg_5 END AS prev_5
        FROM macro_latest
        WHERE source <> 'treasury' OR list_contains(?, series)""",
        [sorted(US_SHOWN)],
    ).fetchall()
    if not rows:
        return "_none_\n"
    rank = {series: position for position, series in enumerate(US_ORDER)}
    rows.sort(key=lambda row: (rank.get(row[0], len(rank)), row[0]))

    def chg(unit, change, prev):
        """A series change as basis points, percent of the previous value or points, by unit."""
        if change is None:
            return ""
        if unit == "pct":
            return f"{change * 100:+.0f} bp"
        if unit == "index":
            return f"{change / prev * 100:+.2f}%" if prev else ""
        return f"{change:+.2f}"

    out = ["| series | name | date | value | chg 1 obs | chg 5 obs | 5 obs back |", "|---|---|---|---|---|---|---|"]
    for series, name, unit, latest_date, value, change_1, change_5, date_5, previous_1, previous_5 in rows:
        val = f"{value:.2f}%" if unit == "pct" else f"{value:.2f}"
        out.append(
            f"| {series} | {name} | {latest_date} | {val} | {chg(unit, change_1, previous_1)} | "
            f"{chg(unit, change_5, previous_5)} | {date_5 or ''} |"
        )
    return (
        "Changes are versus the series' own previous observations (sessions for daily series). "
        "Credit spreads (OAS) widening = risk-off; put/call above ~1 = heavy hedging.\n\n" + "\n".join(out) + "\n"
    )


def _us_shorts(con, tickers: list[str]) -> str:
    """The short-selling section of the US context."""
    return (
        "Daily short-sale volume is FINRA-reported (off-exchange) volume only: compare with the ticker's "
        "own average, not across tickers. prior_avg_pct = average of the up to 20 sessions before the "
        "latest; prior_n says how many (below 20 = a shorter, less reliable baseline). Short interest "
        "settles twice a month and is published about a week later.\n\n"
        + cursor_markdown_table(
            con.execute(
                """
        SELECT coalesce(v.ticker, s.ticker) AS ticker, v.date, round(v.short_pct, 1) AS short_pct,
               round(v.short_pct_5d, 1) AS avg5_pct, round(v.short_pct_prior_avg, 1) AS prior_avg_pct,
               v.n_prior AS prior_n, round(v.short_pct_5d - v.short_pct_prior_avg, 1) AS avg5_vs_prior_pp,
               s.settlement_date AS si_settled, round(s.short_interest / 1e6, 2) AS short_interest_m,
               round(s.change_pct, 1) AS si_chg_pct, s.days_to_cover
        FROM shorts_latest v FULL JOIN short_interest_latest s USING (ticker)
        WHERE list_contains(?, coalesce(v.ticker, s.ticker)) ORDER BY 1""",
                [tickers],
            )
        )
    )


def _india_fpi(con) -> str:
    """The FPI flows section of the India context."""
    latest = cursor_markdown_table(
        con.execute("""
        SELECT reporting_date, asset_class, route, gross_purchases_cr, gross_sales_cr, net_cr, net_usd_mn
        FROM fpi_latest
        WHERE route ILIKE 'sub-total' OR asset_class = 'Total'
           OR (asset_class = 'Equity' AND route ILIKE 'stock exchange')
        ORDER BY asset_class = 'Total', asset_class = 'Equity' DESC, asset_class, route""")
    )
    trend = con.execute("""
        WITH e AS (SELECT reporting_date, net_cr FROM fpi_daily WHERE asset_class = 'Equity' AND route ILIKE 'sub-total'
                   ORDER BY reporting_date DESC LIMIT 5)
        SELECT count(*), CAST(sum(TRY_CAST(net_cr AS DECIMAL(38,10))) AS DOUBLE), min(reporting_date),
               max(reporting_date) FROM e""").fetchone()
    line = ""
    if trend and trend[0]:
        line = (
            f"Equity net over the last {trend[0]} stored reports ({trend[2]} to {trend[3]}): {trend[1]:+,.0f} cr.\n\n"
        )
    return (
        "NSDL reports depository-confirmed FPI trades of the previous trading day(s) on the reporting date "
        "(NSE's provisional FII/DII figures are in their own section).\n\n" + line + latest
    )


def _india_indices(con) -> str:
    """The NSE index valuation section of the India context."""
    return cursor_markdown_table(
        con.execute("""
        SELECT index_name, coalesce(sector, '') AS watchlist_sector, date, round(close, 2) AS close,
               round(change_pct, 2) AS d1_pct, round(ret_5_pct, 2) AS d5_pct, date_5, pe, pb, div_yield
        FROM indices_latest ORDER BY sector IS NULL, sector, index_name""")
    )


def context_sections(cfg: dict, con) -> list[tuple[str, str]]:
    """The macro, flows and short-selling sections of the context pack."""
    out = []
    if cfg.get("macro"):
        out.append(
            ("Macro & flows (US Treasury curve, FRED credit spreads, Cboe put/call; latest values)", _us_macro(con))
        )
    if cfg.get("shorts"):
        out.append(
            (
                "Short selling (FINRA; latest session and latest short-interest settlement)",
                _us_shorts(con, active_tickers(cfg)),
            )
        )
    if cfg.get("india_flows"):
        flows = cfg["india_flows"]
        if flows.get("fpi", True):
            out.append(("Macro & flows: FPI investment (NSDL daily, INR crore; latest report)", _india_fpi(con)))
        if flows.get("indices"):
            out.append(
                (
                    "Macro & flows: NSE indices (latest close; d1 from NSE's change %, d5 vs 5 stored sessions "
                    "back; valuation P/E, P/B, dividend yield %)",
                    _india_indices(con),
                )
            )
    return out
