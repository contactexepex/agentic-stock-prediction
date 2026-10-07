"""Recording paper trades: validation, the stored row, corrections (supersedes) and the append.

add_trade() checks, as of the run's clock: the ticker is in the market's watchlist; trade_date is a session and
not after the clock's date; the price is the stored bar's open or close (price_basis open | close) or a manual
price inside that bar's low-high (config trades.manual_price_tolerance); the idempotency key is new (trades and
requests); a `supersedes` target exists and is still active, with the same ticker; and the active trades after
the change never sell more than is held (trades.allow_short false). Nothing is stored unless every check
passes. Rows are appended via a temp file in work/ (CLAUDE.md data rules 1-2); they are never edited."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pandas as pd

from marketbrief.core import paths
from marketbrief.core.calendar import is_session
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.portfolio import ledger, reads
from marketbrief.portfolio import constants as text
from marketbrief.portfolio.constants import BASIS_MANUAL, SIDE_CANCEL, TRADE_ID_PREFIX, TRADE_SIDES

KEY_DIGITS = 16


def digest(*parts) -> str:
    """A short stable hash of the parts (ids and default idempotency keys)."""
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:KEY_DIGITS]


def default_key(market: str, fields: dict) -> str:
    """The idempotency key when none is given: the same command twice is the same trade (a retried message)."""
    return digest(market, fields["ticker"], fields["side"], fields["quantity"], fields["price_basis"],
                  fields.get("price"), fields["trade_date"], fields.get("supersedes"))


def used_keys(con, clock: datetime) -> dict[str, str]:
    """{idempotency_key: row id} of every trade and request stored by the clock."""
    keys = {}
    for frame in (reads.trade_rows(con, clock), reads.request_rows(con, clock)):
        if not frame.empty:
            keys.update(dict(zip(frame["idempotency_key"], frame["id"])))
    return keys


def check_fields(cfg: dict, settings: dict, fields: dict, clock: datetime) -> list[str]:
    """Enum, watchlist, session and date checks that need no stored data."""
    rules, errors = settings["trades"], []
    if fields["market"] != cfg["market"]:
        errors.append(text.ERR_MARKET.format(market=fields["market"], config=cfg["market"]))
    if fields["ticker"] not in cfg["tickers"]:
        errors.append(text.ERR_TICKER.format(ticker=fields["ticker"], market=cfg["market"]))
    if fields["side"] not in TRADE_SIDES:
        errors.append(text.ERR_SIDE.format(allowed=", ".join(TRADE_SIDES)))
    if not isinstance(fields["quantity"], (int, float)) or not fields["quantity"] > 0:
        errors.append(text.ERR_QUANTITY)
    if fields["price_basis"] not in rules["price_bases"]:
        errors.append(text.ERR_BASIS.format(allowed=", ".join(rules["price_bases"])))
    if fields["source"] not in rules["sources"]:
        errors.append(text.ERR_SOURCE.format(allowed=", ".join(rules["sources"])))
    day = fields["trade_date"]
    if not is_session(cfg, day):
        errors.append(text.ERR_DATE.format(day=day, market=cfg["market"]))
    elif day > clock.date():
        errors.append(text.ERR_FUTURE.format(day=day, today=clock.date()))
    return errors


def resolve_price(ctx, fields: dict) -> tuple[float | None, list[str]]:
    """The trade price: the stored bar's open/close, or the manual price checked against the bar's low-high."""
    basis, price = fields["price_basis"], fields.get("price")
    if basis != BASIS_MANUAL and price is not None:
        return None, [text.ERR_PRICE_GIVEN]
    if basis == BASIS_MANUAL and not (isinstance(price, (int, float)) and price > 0):
        return None, [text.ERR_PRICE_MISSING]
    bar = reads.bar_on(ctx.con, ctx.cfg, ctx.clock, fields["ticker"], fields["trade_date"])
    if bar is None:
        return None, [text.ERR_NO_BAR.format(ticker=fields["ticker"], day=fields["trade_date"],
                                             clock=ctx.clock.isoformat())]
    if basis != BASIS_MANUAL:
        return float(bar[basis]), []
    slack = ctx.settings["trades"]["manual_price_tolerance"]
    low, high = float(bar["low"]) * (1 - slack), float(bar["high"]) * (1 + slack)
    if not low <= price <= high:
        return None, [text.ERR_PRICE_RANGE.format(price=price, ticker=fields["ticker"], low=bar["low"],
                                                  high=bar["high"], day=fields["trade_date"])]
    return float(price), []


def check_supersedes(trades: pd.DataFrame, target: str | None, ticker: str | None, market: str) -> list[str]:
    """A correction or cancellation must name an existing, still active trade (and keep its ticker)."""
    if target is None:
        return []
    known = trades[trades["id"] == target] if not trades.empty else trades
    if known.empty or known.iloc[0]["side"] == SIDE_CANCEL:
        return [text.ERR_SUPERSEDES_UNKNOWN.format(target=target, market=market)]
    done = reads.superseded_by(trades)
    if target in done:
        return [text.ERR_SUPERSEDES_DONE.format(target=target, by=done[target])]
    if ticker is not None and known.iloc[0]["ticker"] != ticker:
        return [text.ERR_SUPERSEDES_TICKER.format(ticker=known.iloc[0]["ticker"])]
    return []


def check_no_short(ctx, trades: pd.DataFrame, row: dict | None, target: str | None) -> list[str]:
    """The active trades after the change (`row` added, `target` removed) never sell more than is held
    (unless trades.allow_short)."""
    if ctx.settings["trades"]["allow_short"]:
        return []
    after = reads.active_trades(trades)
    if target is not None and not after.empty:
        after = after[after["id"] != target]
    if row is not None:
        new = pd.DataFrame([{**row, "trade_date": pd.Timestamp(row["trade_date"]).date(),
                             "entered_at": pd.Timestamp(row["entered_at"])}])
        after = pd.concat([after, new], ignore_index=True) if not after.empty else new
    if after.empty:
        return []
    book = ledger.run_book(after, reads.adjustments(ctx.con, ctx.clock), ctx.market, ctx.costs)
    return [text.ERR_SHORT.format(quantity=v["quantity"], ticker=v["ticker"], day=v["trade_date"], left=v["left"])
            for v in book.violations]


def store(rows: list[dict], kind: str, market: str, stamp: datetime) -> str:
    """Append rows to the day file of `stamp` via a temp file in work/ (never overwriting); returns the path."""
    work = paths.ROOT / text.DIR_WORK_PORTFOLIO
    work.mkdir(parents=True, exist_ok=True)
    temp = work / f"{kind}-{rows[0]['id']}.jsonl"
    temp.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows))
    target = day_file(market, kind, stamp.date())
    with temp.open() as handle:
        append_jsonl(target, [json.loads(line) for line in handle if line.strip()])
    temp.unlink()
    return target.relative_to(paths.ROOT).as_posix()


def stored_row(fields: dict, price: float | None, key: str, clock: datetime) -> dict:
    """The row as stored (column order of the schema)."""
    return {"id": f"{TRADE_ID_PREFIX}-{fields['market']}-{digest(fields['market'], key)}", "market": fields["market"],
            "ticker": fields["ticker"], "side": fields["side"], "quantity": fields["quantity"], "price": price,
            "price_basis": fields["price_basis"], "trade_date": fields["trade_date"].isoformat(),
            "source": fields["source"], "idempotency_key": key, "entered_at": clock.replace(microsecond=0).isoformat(),
            "note": fields.get("note"), "supersedes": fields.get("supersedes")}
