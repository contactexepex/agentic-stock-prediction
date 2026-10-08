"""Context-pack section "Earnings estimates (Yahoo consensus)" (issue #17): per watchlist ticker the last
reported quarter's consensus EPS, reported EPS and surprise, and the consensus for the next report, as known now
(earnings_estimates_asof(now()), so MB_NOW applies). Shown for reading only: no range or forecast rule uses it."""

from __future__ import annotations

from marketbrief.lifecycle.loader import active_tickers
from marketbrief.utils.markdown import cursor_markdown_table

TITLE = "Earnings estimates (Yahoo consensus EPS; not a range or forecast input)"
NOTE = ("Yahoo's consensus (yfinance), stored when first seen or changed. `surprise_pct` = reported vs estimate. "
        "`seen` = when we first stored the next report's current estimate; a last-report estimate first seen "
        "after that report says nothing about what was expected before it.\n\n")

SQL = """
WITH e AS (SELECT * FROM earnings_estimates_asof(now()) WHERE list_contains(?, ticker)),
done AS (SELECT * FROM e WHERE reported AND reported_eps IS NOT NULL
         QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY report_at DESC) = 1),
nxt AS (SELECT * FROM e WHERE NOT reported
        QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY report_at) = 1)
SELECT t.ticker, done.report_date AS last_report, done.eps_estimate AS last_estimate, done.reported_eps,
       done.surprise_pct, nxt.report_date AS next_report, nxt.eps_estimate AS next_estimate,
       CAST(nxt.collected_at AS DATE) AS seen
FROM (SELECT unnest(?::VARCHAR[]) AS ticker) t
LEFT JOIN done ON done.ticker = t.ticker LEFT JOIN nxt ON nxt.ticker = t.ticker
WHERE done.ticker IS NOT NULL OR nxt.ticker IS NOT NULL
ORDER BY t.ticker"""


def context_section(cfg: dict, con) -> tuple[str, str]:
    """(title, body) of the section; `_none_` before any estimate is stored."""
    tickers = sorted(active_tickers(cfg))
    table = cursor_markdown_table(con.execute(SQL, [tickers, tickers]))
    return TITLE, (NOTE + table) if not table.startswith("_none_") else table
