"""Smart-money signals (docs/DESIGN.md phase 5): the compact "Smart money" section of the
context pack and the range risk flags. Inputs are the SEC relationship views in sql/views.sql
(insider_flow, insider_trades, stake_filings, activist_stakes, holdings_quarter).

In ranges these are a risk flag only: a fresh activist 13D adds a note to the range, and widens
it only if config/ranges.yaml sets `activist_13d_factor` above 1.0 (default 1.0, off until the
weekly review shows that it improves coverage)."""
from __future__ import annotations

from datetime import date, timedelta

from common import md_table

SECTIONS: list[tuple[str, str]] = [
    ("Insider open-market trades by ticker (Form 4; USD; P buys vs S sales, last 30/90 days)", """
        SELECT ticker, round(buy_value_30d) AS buys_30d, round(sell_value_30d) AS sales_30d,
               round(net_value_30d) AS net_30d, round(net_value_90d) AS net_90d,
               buyers_30d, sellers_30d, planned_sell_share_30d AS planned_sales_share, cluster_buy,
               last_buy, last_sale
        FROM insider_flow ORDER BY cluster_buy DESC, net_value_30d DESC, ticker"""),
    ("Largest insider buys and sales, last 7 days (P/S only)", """
        SELECT ticker, transaction_date AS date, insider_name, role, code, round(shares) AS shares,
               round(price, 2) AS price, round(value) AS value, round(shares_after) AS held_after, plan_10b5_1
        FROM insider_trades
        WHERE NOT derivative AND code IN ('P', 'S') AND transaction_date >= current_date - 7
        ORDER BY code = 'P' DESC, value DESC NULLS LAST LIMIT 10"""),
    ("13D/13G filings, last 30 days (13D = active holder >5%; 13G = passive)", """
        SELECT ticker, form, filing_date, filer_name, percent, round(shares) AS shares
        FROM stake_filings WHERE filing_date >= current_date - 30
        ORDER BY kind = '13D' DESC, filing_date DESC, ticker LIMIT 15"""),
    ("13F tracked filers: latest quarter vs previous (common shares)", """
        SELECT ticker, period, filers_holding, round(value_usd / 1e9, 2) AS value_bn,
               round(change_pct * 100, 1) AS change_pct, n_new, n_exit, n_add, n_trim
        FROM holdings_quarter
        WHERE period = (SELECT max(period) FROM holdings_quarter q WHERE q.ticker = holdings_quarter.ticker)
        ORDER BY change_pct DESC NULLS LAST, ticker"""),
]


def markdown(cfg: dict, con) -> str:
    """The "Smart money" block of the context pack ('' for markets without SEC data)."""
    if cfg.get("filings") != "sec":
        return ""
    out = ["## Smart money (SEC: insiders, big stakes, 13F)\n"]
    for title, sql in SECTIONS:
        out.append(f"### {title}\n\n{md_table(con.execute(sql))}")
    return "\n".join(out)


def range_flags(con, as_of: date, rc: dict) -> dict[str, tuple[float, list[str]]]:
    """ticker -> (sigma factor, notes) for fresh activist 13D stakes (filed on or after
    as_of - activist_13d_days). Factor 1.0 unless ranges.yaml turns the widen on."""
    days = int(rc.get("activist_13d_days", 30))
    factor = max(1.0, float(rc.get("activist_13d_factor", 1.0)))
    rows = con.execute("""
        SELECT ticker, filing_date, filer_name, percent FROM activist_stakes
        WHERE filing_date >= ? ORDER BY ticker, filing_date""", [as_of - timedelta(days=days)]).fetchall()
    flags: dict[str, tuple[float, list[str]]] = {}
    for ticker, filed, filer, pct in rows:
        f, notes = flags.get(ticker, (1.0, []))
        size = f" {pct:g}%" if pct is not None else ""
        notes.append(f"new 13D: {filer or 'unknown filer'}{size} filed {filed}" + (f" x{factor}" if factor > 1 else ""))
        flags[ticker] = (factor, notes)
    return flags
