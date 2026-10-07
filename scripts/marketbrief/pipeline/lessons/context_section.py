"""The context pack's section of lessons from past calls (only those available by now)."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics.call_basis import label
from marketbrief.core.clock import clock


def context_section(cfg: dict, con, per_ticker: int = 3, market_wide: int = 3) -> tuple[str, str]:
    """("Lessons from past calls", markdown): the latest `market_wide` lessons market-wide and each
    ticker's last `per_ticker`, using only lessons with available_from <= now (core.clock.clock(), so an
    MB_NOW replay sees only what was settled by then). Newest version of a lesson id wins."""
    now = clock()
    frame = con.execute(
        """
        SELECT * FROM lessons WHERE available_from <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY written_at DESC) = 1
        ORDER BY available_from DESC, target_date DESC, id""",
        [now.isoformat()],
    ).df()
    title = "Lessons from past calls (settled before now; anecdotes, n=1 each: weigh against the track record)"
    if frame.empty:
        return title, "_none_\n"

    def table(rows: pd.DataFrame) -> str:
        """A markdown table of lesson rows."""
        out = [
            "| ticker | call | conf | result | return % | close vs range | lesson |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows.itertuples(index=False):
            return_text = (
                "" if pd.isna(row.actual_return) else f"{100 * row.actual_return:+.2f} ({label(row.label_basis)})"
            )
            pos = "" if row.range_position is None or pd.isna(row.range_position) else row.range_position
            lesson = str(row.lesson).replace("|", "/").replace("\n", " ")
            out.append(
                f"| {row.ticker} | {row.prediction_id} {row.direction} | {row.confidence:.2f} | "
                f"{'hit' if row.hit else 'miss'} | {return_text} | {pos} | {lesson} |"
            )
        return "\n".join(out) + "\n"

    tickers = [ticker for ticker in cfg["tickers"] if ticker in set(frame["ticker"])]
    by_t = (
        pd.concat([frame[frame["ticker"] == ticker].head(per_ticker) for ticker in tickers])
        if tickers
        else frame.head(0)
    )
    body = (
        f"Most recent {market_wide}, market-wide:\n\n{table(frame.head(market_wide))}\n"
        f"Last {per_ticker} per ticker:\n\n{table(by_t)}"
    )
    return title, body
