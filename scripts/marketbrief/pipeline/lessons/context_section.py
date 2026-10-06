"""The context pack's section of lessons from past calls (only those available by now)."""
from __future__ import annotations

import pandas as pd
from marketbrief.core.clock import clock


def context_section(cfg: dict, con, per_ticker: int = 3, market_wide: int = 3) -> tuple[str, str]:
    """("Lessons from past calls", markdown): the latest `market_wide` lessons market-wide and each
    ticker's last `per_ticker`, using only lessons with available_from <= now (core.clock.clock(), so an
    MB_NOW replay sees only what was settled by then). Newest version of a lesson id wins."""
    now = clock()
    df = con.execute("""
        SELECT * FROM lessons WHERE available_from <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY written_at DESC) = 1
        ORDER BY available_from DESC, target_date DESC, id""", [now.isoformat()]).df()
    title = "Lessons from past calls (settled before now; anecdotes, n=1 each: weigh against the track record)"
    if df.empty:
        return title, "_none_\n"

    def table(rows: pd.DataFrame) -> str:
        out = ["| ticker | call | conf | result | return % | close vs range | lesson |", "|---|---|---|---|---|---|---|"]
        for r in rows.itertuples(index=False):
            ret = "" if pd.isna(r.actual_return) else f"{100 * r.actual_return:+.2f}"
            pos = "" if r.range_position is None or pd.isna(r.range_position) else r.range_position
            lesson = str(r.lesson).replace("|", "/").replace("\n", " ")
            out.append(f"| {r.ticker} | {r.prediction_id} {r.direction} | {r.confidence:.2f} | "
                       f"{'hit' if r.hit else 'miss'} | {ret} | {pos} | {lesson} |")
        return "\n".join(out) + "\n"

    tickers = [t for t in cfg["tickers"] if t in set(df["ticker"])]
    by_t = pd.concat([df[df["ticker"] == t].head(per_ticker) for t in tickers]) if tickers else df.head(0)
    body = (f"Most recent {market_wide}, market-wide:\n\n{table(df.head(market_wide))}\n"
            f"Last {per_ticker} per ticker:\n\n{table(by_t)}")
    return title, body
