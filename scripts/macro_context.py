"""Context-pack sections for the free market-wide sources (issue #9): "Macro & flows" (US:
Treasury curve, FRED credit spreads, Cboe put/call ratios; India: NSDL FPI investment and NSE
index closes with valuation) and, US, "Short selling (FINRA)". Each section appears only when its
market's config has the collector's section. Numbers come from the DuckDB views in sql/views.sql."""
from __future__ import annotations

from common import md_table

# The order series are listed in; others follow alphabetically.
US_ORDER = ["UST_3M", "UST_2Y", "UST_5Y", "UST_10Y", "UST_30Y", "UST_10Y_2Y", "UST_10Y_3M"]
US_SHOWN = {"UST_3M", "UST_2Y", "UST_5Y", "UST_10Y", "UST_30Y", "UST_10Y_2Y", "UST_10Y_3M"}


def _us_macro(con) -> str:
    """Yields and spreads change in basis points, ratios in points, index levels in %."""
    rows = con.execute("""
        SELECT series, name, unit, date, value, chg_1, chg_5, date_5,
               CASE WHEN unit = 'index' THEN value - chg_1 END AS prev_1, CASE WHEN unit = 'index' THEN value - chg_5 END AS prev_5
        FROM macro_latest
        WHERE source <> 'treasury' OR list_contains(?, series)""", [sorted(US_SHOWN)]).fetchall()
    if not rows:
        return "_none_\n"
    rank = {s: i for i, s in enumerate(US_ORDER)}
    rows.sort(key=lambda r: (rank.get(r[0], len(rank)), r[0]))

    def chg(unit, c, prev):
        if c is None:
            return ""
        if unit == "pct":
            return f"{c * 100:+.0f} bp"
        if unit == "index":
            return f"{c / prev * 100:+.2f}%" if prev else ""
        return f"{c:+.2f}"

    out = ["| series | name | date | value | chg 1 obs | chg 5 obs | 5 obs back |", "|---|---|---|---|---|---|---|"]
    for s, name, unit, d, v, c1, c5, d5, p1, p5 in rows:
        val = f"{v:.2f}%" if unit == "pct" else f"{v:.2f}"
        out.append(f"| {s} | {name} | {d} | {val} | {chg(unit, c1, p1)} | {chg(unit, c5, p5)} | {d5 or ''} |")
    return ("Changes are versus the series' own previous observations (sessions for daily series). "
            "Credit spreads (OAS) widening = risk-off; put/call above ~1 = heavy hedging.\n\n" + "\n".join(out) + "\n")


def _us_shorts(con, tickers: list[str]) -> str:
    return ("Daily short-sale volume is FINRA-reported (off-exchange) volume only: compare with the ticker's "
            "own average, not across tickers. prior_avg_pct = average of the up to 20 sessions before the "
            "latest; prior_n says how many (below 20 = a shorter, less reliable baseline). Short interest "
            "settles twice a month and is published about a week later.\n\n" + md_table(con.execute("""
        SELECT coalesce(v.ticker, s.ticker) AS ticker, v.date, round(v.short_pct, 1) AS short_pct,
               round(v.short_pct_5d, 1) AS avg5_pct, round(v.short_pct_prior_avg, 1) AS prior_avg_pct,
               v.n_prior AS prior_n, round(v.short_pct_5d - v.short_pct_prior_avg, 1) AS avg5_vs_prior_pp,
               s.settlement_date AS si_settled, round(s.short_interest / 1e6, 2) AS short_interest_m,
               round(s.change_pct, 1) AS si_chg_pct, s.days_to_cover
        FROM shorts_latest v FULL JOIN short_interest_latest s USING (ticker)
        WHERE list_contains(?, coalesce(v.ticker, s.ticker)) ORDER BY 1""", [tickers])))


def _india_fpi(con) -> str:
    latest = md_table(con.execute("""
        SELECT reporting_date, asset_class, route, gross_purchases_cr, gross_sales_cr, net_cr, net_usd_mn
        FROM fpi_latest
        WHERE route ILIKE 'sub-total' OR asset_class = 'Total' OR (asset_class = 'Equity' AND route ILIKE 'stock exchange')
        ORDER BY asset_class = 'Total', asset_class = 'Equity' DESC, asset_class, route"""))
    trend = con.execute("""
        WITH e AS (SELECT reporting_date, net_cr FROM fpi_daily WHERE asset_class = 'Equity' AND route ILIKE 'sub-total'
                   ORDER BY reporting_date DESC LIMIT 5)
        SELECT count(*), CAST(sum(TRY_CAST(net_cr AS DECIMAL(38,10))) AS DOUBLE), min(reporting_date),
               max(reporting_date) FROM e""").fetchone()
    line = ""
    if trend and trend[0]:
        line = (f"Equity net over the last {trend[0]} stored reports ({trend[2]} to {trend[3]}): "
                f"{trend[1]:+,.0f} cr.\n\n")
    return ("NSDL reports depository-confirmed FPI trades of the previous trading day(s) on the reporting date "
            "(NSE's provisional FII/DII figures are in their own section).\n\n" + line + latest)


def _india_indices(con) -> str:
    return md_table(con.execute("""
        SELECT index_name, coalesce(sector, '') AS watchlist_sector, date, round(close, 2) AS close,
               round(change_pct, 2) AS d1_pct, round(ret_5_pct, 2) AS d5_pct, date_5, pe, pb, div_yield
        FROM indices_latest ORDER BY sector IS NULL, sector, index_name"""))


def context_sections(cfg: dict, con) -> list[tuple[str, str]]:
    out = []
    if cfg.get("macro"):
        out.append(("Macro & flows (US Treasury curve, FRED credit spreads, Cboe put/call; latest values)", _us_macro(con)))
    if cfg.get("shorts"):
        out.append(("Short selling (FINRA; latest session and latest short-interest settlement)",
                    _us_shorts(con, list(cfg["tickers"]))))
    if cfg.get("india_flows"):
        flows = cfg["india_flows"]
        if flows.get("fpi", True):
            out.append(("Macro & flows: FPI investment (NSDL daily, INR crore; latest report)", _india_fpi(con)))
        if flows.get("indices"):
            out.append(("Macro & flows: NSE indices (latest close; d1 from NSE's change %, d5 vs 5 stored sessions "
                        "back; valuation P/E, P/B, dividend yield %)", _india_indices(con)))
    return out
