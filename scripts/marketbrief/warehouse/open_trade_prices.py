"""The prices of an Open-trade record (rm_entities.open_trades; docs/ws/b4.md): a trade is open from D's open. Its
entry is D's stored open, else the open of D from its newest intraday check (B9's trade_checks) by the cut-off; its
last price is the newer of the last stored close and that check's price."""

from __future__ import annotations

import pandas as pd

from marketbrief.warehouse.rm_registry import BuildContext

# each trade's newest intraday check stored by the cut-off (B9's trade_checks: D's open and the latest price)
CHECKS_SQL = """SELECT DISTINCT ON (trade_id) trade_id, session_date, entry_price, last_price, last_time
FROM trade_check_rows WHERE check_at <= ?::TIMESTAMPTZ AND computed_at <= ?::TIMESTAMPTZ AND list_contains(?, trade_id)
ORDER BY trade_id, check_at DESC, id"""
SOURCE_BAR, SOURCE_CHECK, SOURCE_CLOSE = "daily_bar", "intraday_check", "daily_close"


def iso_day(value) -> str | None:
    """A stored date or time as YYYY-MM-DD, or None."""
    return None if _missing(value) else pd.Timestamp(value).date().isoformat()


def iso_time(value) -> str | None:
    """An aware time as ISO UTC with a Z, or None."""
    return None if _missing(value) else pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_checks(ctx: BuildContext, trade_ids: list[str]) -> dict[str, dict]:
    """trade_id -> its newest intraday check stored by the cut-off: session_date, entry_price (D's open on D's basis),
    last_price (raw, that session's basis) and last_time."""
    if not trade_ids:
        return {}
    frame = ctx.con.execute(CHECKS_SQL, [ctx.cutoff_time, ctx.cutoff_time, trade_ids]).df()
    return {row["trade_id"]: row for row in frame.to_dict("records")}


def trade_prices(trade: dict, open_price, close: tuple, check: dict | None) -> dict | None:
    """Entry and last price of a trade: entry = D's stored open, else its newest check's entry price; last = the
    newest of the last stored close and the check's price (a check of a later session wins; on the close's own
    session the stored close, which is final). None when no entry or no price is known yet."""
    last_date, last = close
    entry, entry_source = (open_price, SOURCE_BAR) if open_price is not None else (None, None)
    if entry is None and check is not None and not _missing(check["entry_price"]):
        entry, entry_source = float(check["entry_price"]), SOURCE_CHECK
    last_source, last_time = SOURCE_CLOSE, None
    if check is not None and not _missing(check["last_price"]):
        check_day = iso_day(check["session_date"])
        if last is None or check_day > last_date:
            last, last_date, last_source = float(check["last_price"]), check_day, SOURCE_CHECK
            last_time = iso_time(check["last_time"])
    if entry is None or last is None or last_date < trade["entry_date"].isoformat():
        return None
    return {
        "entry": float(entry),
        "entry_source": entry_source,
        "last": float(last),
        "last_date": last_date,
        "last_source": last_source,
        "last_time": last_time,
    }


def _missing(value) -> bool:
    return value is None or pd.isna(value)
