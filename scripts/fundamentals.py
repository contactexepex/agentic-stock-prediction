"""The compact "Fundamentals" section of the context pack (markets with `filings: sec`): the last
reported quarter per ticker with year-over-year growth, margins, free cash flow and the filed
date, the latest balance sheet, and a flag for reports filed in the last FRESH_DAYS days.
Inputs are the fundamentals views in sql/views.sql (collect_fundamentals.py writes the data).

No consensus estimates are available for free, so there is no "surprise" here: growth is
against the same fiscal quarter a year earlier, as reported to the SEC."""
from __future__ import annotations

from marketbrief.utils.markdown import cursor_markdown_table

FRESH_DAYS = 5

NOTE = ("Growth is year over year (same fiscal quarter a year earlier); no consensus estimates, so no "
        "surprise. `*` = derived from year-to-date totals (Q4 = FY - 9M; a derived EPS is approximate). "
        "Gross margin marked `c` = revenue minus cost of revenue (no gross profit tagged). "
        f"`new` = filed in the last {FRESH_DAYS} days.")

SECTIONS: list[tuple[str, str]] = [
    ("Last reported quarter (USD bn; growth and margins in %)", f"""
        WITH q AS (
            SELECT * FROM fundamentals_metrics WHERE revenue IS NOT NULL OR net_income IS NOT NULL
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) = 1
        )
        SELECT q.ticker, concat('FY', q.fiscal_year, ' ', q.fiscal_period, CASE WHEN q.derived THEN '*' END) AS quarter,
               q.period_end, r.form, r.filing_date AS filed,
               CASE WHEN r.filing_date >= current_date - {FRESH_DAYS} THEN 'new' END AS fresh,
               round(q.revenue / 1e9, 2) AS revenue, round(q.revenue_yoy * 100, 1) AS rev_yoy,
               round(q.eps_diluted, 2) AS eps, round(q.eps_yoy * 100, 1) AS eps_yoy,
               round(q.net_income_yoy * 100, 1) AS ni_yoy,
               concat(round(q.gross_margin * 100, 1), CASE WHEN q.gross_profit_computed THEN ' c' END) AS gross_margin,
               round(q.operating_margin * 100, 1) AS op_margin, round(q.fcf / 1e9, 2) AS fcf
        FROM q LEFT JOIN fundamentals_latest_report r USING (ticker)
        ORDER BY r.filing_date DESC NULLS LAST, q.ticker"""),
    ("Balance sheet, latest (USD bn; shares in millions)", """
        WITH b AS (
            SELECT * FROM fundamentals_balance WHERE cash IS NOT NULL OR total_debt IS NOT NULL
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) = 1
        ), s AS (
            SELECT ticker, value AS shares, period_end AS shares_as_of FROM fundamentals_latest
            WHERE concept = 'shares_outstanding'
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) = 1
        )
        SELECT b.ticker, b.period_end AS as_of, round(b.cash / 1e9, 2) AS cash, round(b.total_debt / 1e9, 2) AS total_debt,
               b.debt_basis, round(s.shares / 1e6, 1) AS shares_out, s.shares_as_of
        FROM b LEFT JOIN s USING (ticker) ORDER BY b.ticker"""),
]


def markdown(cfg: dict, con) -> str:
    """The "Fundamentals" block of the context pack ('' for markets without SEC data)."""
    if cfg.get("filings") != "sec":
        return ""
    fresh = con.execute(f"""
        SELECT ticker, form, fiscal_year, fiscal_period, filing_date FROM fundamentals_latest_report
        WHERE filing_date >= current_date - {FRESH_DAYS} ORDER BY filing_date DESC, ticker""").fetchall()
    out = ["## Fundamentals (SEC 10-Q/10-K via XBRL)\n", NOTE + "\n"]
    if fresh:
        out.append(f"Filed in the last {FRESH_DAYS} days: " + "; ".join(
            f"{t} {form} FY{fy} {fp} ({d})" for t, form, fy, fp, d in fresh) + "\n")
    for title, sql in SECTIONS:
        out.append(f"### {title}\n\n{cursor_markdown_table(con.execute(sql))}")
    return "\n".join(out)
