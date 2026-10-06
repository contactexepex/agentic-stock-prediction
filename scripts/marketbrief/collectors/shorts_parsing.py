"""Parsers of the FINRA short-selling sources: the Reg SHO daily short-sale volume file (pipe-separated, with a
header and a trailer line holding the number of data rows) and the consolidated short interest JSON."""

from __future__ import annotations

from datetime import date

from marketbrief.constants.columns import COL_DATE, COL_ID, COL_TICKER
from marketbrief.constants.config_keys import CFG_TICKERS
from marketbrief.constants.free_sources import (
    MSG_EMPTY_FILE,
    MSG_FILE_WRONG_DATE,
    MSG_NO_TRAILER,
    MSG_TRAILER_MISMATCH,
    MSG_UNEXPECTED_HEADER,
    SOURCE_FINRA_INTEREST,
    SOURCE_FINRA_REGSHO,
    VOLUME_HEADER_PREFIX,
    VOLUME_MIN_FIELDS,
)
from marketbrief.utils.numbers import parse_accounting_amount

HEADER_PREVIEW = 60
SHORT_PERCENT_DECIMALS = 2
MARKETS_INDEX = 5


def finra_symbols(cfg: dict) -> dict[str, str]:
    """FINRA symbol -> watchlist ticker (a ticker may set `finra:`)."""
    return {meta.get("finra", ticker).upper(): ticker for ticker, meta in cfg[CFG_TICKERS].items()}


def volume_problem(trailer: list[str], data: list[list[str]]) -> str | None:
    """Why the row-count trailer does not vouch for the file (missing, or a count that differs), or None."""
    if not trailer or not trailer[-1].isdigit():
        return MSG_NO_TRAILER
    if int(trailer[-1]) != len(data):
        return MSG_TRAILER_MISMATCH.format(trailer=trailer[-1], rows=len(data))
    return None


def volume_row(parts: list[str], day: date, ticker: str, now: str) -> dict:
    """One `shorts` row of a data line (Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market(s))."""
    short, exempt, total = (
        parse_accounting_amount(parts[2]),
        parse_accounting_amount(parts[3]),
        parse_accounting_amount(parts[4]),
    )
    return {
        COL_ID: f"finra-shvol-{day}-{ticker}",
        COL_DATE: str(day),
        COL_TICKER: ticker,
        "short_volume": short,
        "short_exempt_volume": exempt,
        "total_volume": total,
        "short_pct": round(short / total * 100, SHORT_PERCENT_DECIMALS) if short is not None and total else None,
        "markets": parts[MARKETS_INDEX] if len(parts) > MARKETS_INDEX else None,
        "source": SOURCE_FINRA_REGSHO,
        "first_seen_at": now,
    }


def parse_volume(text: str, day: date, symbols: dict[str, str], now: str) -> tuple[list[dict], str | None]:
    """Rows for watchlist symbols, and a problem (truncated file, wrong date) or None. The file is
    pipe-separated with a header and a trailer line holding the number of data rows."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(VOLUME_HEADER_PREFIX):
        preview = lines[0][:HEADER_PREVIEW] if lines else MSG_EMPTY_FILE
        return [], MSG_UNEXPECTED_HEADER.format(preview=preview)
    data = [line.split("|") for line in lines[1:] if "|" in line]
    problem = volume_problem([line for line in lines[1:] if "|" not in line], data)
    rows = []
    for parts in data:
        if len(parts) < VOLUME_MIN_FIELDS:
            continue
        ticker = symbols.get(parts[1].upper())
        if not ticker:
            continue
        if parts[0] != f"{day:%Y%m%d}":
            problem = MSG_FILE_WRONG_DATE.format(day=day, found=parts[0])
            continue
        rows.append(volume_row(parts, day, ticker, now))
    return rows, problem


def parse_short_interest(payload, symbols: dict[str, str], now: str) -> list[dict]:
    """The `short_interest` rows of FINRA's consolidated short interest answer for the watchlist symbols."""
    rows = []
    for record in payload if isinstance(payload, list) else []:
        ticker = symbols.get((record.get("symbolCode") or "").upper())
        settlement = record.get("settlementDate")
        if not ticker or not settlement:
            continue
        rows.append(
            {
                COL_ID: f"finra-si-{settlement}-{ticker}",
                "settlement_date": settlement,
                COL_TICKER: ticker,
                "short_interest": parse_accounting_amount(record.get("currentShortPositionQuantity")),
                "prev_short_interest": parse_accounting_amount(record.get("previousShortPositionQuantity")),
                "change_pct": parse_accounting_amount(record.get("changePercent")),
                "avg_daily_volume": parse_accounting_amount(record.get("averageDailyVolumeQuantity")),
                "days_to_cover": parse_accounting_amount(record.get("daysToCoverQuantity")),
                "revised": bool(record.get("revisionFlag")),
                "source": SOURCE_FINRA_INTEREST,
                "first_seen_at": now,
            }
        )
    return rows
