"""The paper portfolio's importable functions (the CLI and a governed tool, WS7, call these): add_trade,
cancel_trade, request_company, positions_report, pnl_report and list_report. Each takes a Context (market config,
DuckDB connection, run clock, settings, costs) and returns a JSON-ready dict; writes return {"ok": False,
"errors": [...]} and store nothing when a check fails. Everything reads only data stored by the clock."""
from __future__ import annotations

from dataclasses import asdict

from marketbrief.constants.kinds import KIND_PORTFOLIO_TRADES, KIND_WATCHLIST_REQUESTS
from marketbrief.core.database import connect
from marketbrief.portfolio import constants as text
from marketbrief.portfolio import ledger, reads, trades
from marketbrief.portfolio.constants import REQUEST_ID_PREFIX, SIDE_CANCEL, STATUS_REQUESTED
from marketbrief.portfolio.context import Context, TradeInput, context

__all__ = ["Context", "TradeInput", "add_trade", "cancel_trade", "context", "list_report", "pnl_report",
           "positions_report", "request_company"]


def refreshed(ctx: Context, result: dict) -> dict:
    """After a stored write, reconnect so the next read in this context sees the new file (a kind with no file
    at connect time is an empty table, not a view over the files)."""
    ctx.con = connect(ctx.market)
    return result


def add_trade(ctx: Context, entry: TradeInput) -> dict:
    """Validate and store one paper trade (or a correction of entry.supersedes)."""
    fields = {"market": ctx.market, **asdict(entry)}
    errors = trades.check_fields(ctx.cfg, ctx.settings, fields, ctx.clock)
    if errors:
        return {"ok": False, "errors": errors}
    resolved, errors = trades.resolve_price(ctx, fields)
    key = entry.idempotency_key or trades.default_key(ctx.market, fields)
    existing = trades.used_keys(ctx.con, ctx.clock).get(key)
    if existing:
        errors.append(text.ERR_DUPLICATE.format(key=key, existing=existing))
    stored = reads.trade_rows(ctx.con, ctx.clock)
    errors += trades.check_supersedes(stored, entry.supersedes, entry.ticker, ctx.market)
    if errors:
        return {"ok": False, "errors": errors}
    row = trades.stored_row(fields, resolved, key, ctx.clock)
    errors = trades.check_no_short(ctx, stored, row, entry.supersedes)
    if errors:
        return {"ok": False, "errors": errors}
    path = trades.store([row], KIND_PORTFOLIO_TRADES, ctx.market, ctx.clock)
    return refreshed(ctx, {"ok": True, "trade": row, "path": path})


def cancel_trade(ctx: Context, target: str, source: str, note: str | None = None,
                 idempotency_key: str | None = None) -> dict:
    """Store a row that cancels `target` (side cancel, quantity 0); the cancelled row stays as it was."""
    stored = reads.trade_rows(ctx.con, ctx.clock)
    errors = trades.check_supersedes(stored, target, None, ctx.market)
    if source not in ctx.settings["trades"]["sources"]:
        errors.append(text.ERR_SOURCE.format(allowed=", ".join(ctx.settings["trades"]["sources"])))
    key = idempotency_key or trades.digest(ctx.market, SIDE_CANCEL, target)
    existing = trades.used_keys(ctx.con, ctx.clock).get(key)
    if existing:
        errors.append(text.ERR_DUPLICATE.format(key=key, existing=existing))
    if errors:
        return {"ok": False, "errors": errors}
    errors = trades.check_no_short(ctx, stored, None, target)
    if errors:
        return {"ok": False, "errors": errors}
    old = stored[stored["id"] == target].iloc[0]
    fields = {"market": ctx.market, "ticker": old["ticker"], "side": SIDE_CANCEL, "quantity": 0,
              "trade_date": old["trade_date"], "price_basis": old["price_basis"], "source": source, "note": note,
              "supersedes": target}
    row = trades.stored_row(fields, None, key, ctx.clock)
    return refreshed(ctx, {"ok": True, "trade": row,
                           "path": trades.store([row], KIND_PORTFOLIO_TRADES, ctx.market, ctx.clock)})


def request_company(ctx: Context, source: str, reason: str, ticker: str | None = None, name: str | None = None,
                    idempotency_key: str | None = None) -> dict:
    """Store a request to add a company to the watchlist (config changes stay a human or reviewed change)."""
    ticker = ticker.strip().upper() if ticker else None
    errors = [] if (ticker or name) else [text.ERR_REQUEST_NAME]
    if ticker and ticker in ctx.cfg["tickers"]:
        errors.append(text.ERR_REQUEST_LISTED.format(ticker=ticker, market=ctx.market))
    if source not in ctx.settings["trades"]["sources"]:
        errors.append(text.ERR_SOURCE.format(allowed=", ".join(ctx.settings["trades"]["sources"])))
    key = idempotency_key or trades.digest(ctx.market, (ticker or "").upper(), (name or "").strip().lower())
    existing = trades.used_keys(ctx.con, ctx.clock).get(key)
    if existing:
        errors.append(text.ERR_DUPLICATE.format(key=key, existing=existing))
    if errors:
        return {"ok": False, "errors": errors}
    row = {"id": f"{REQUEST_ID_PREFIX}-{ctx.market}-{trades.digest(ctx.market, key)}", "market": ctx.market,
           "ticker": ticker, "name": name, "reason": reason,
           "requested_at": ctx.clock.replace(microsecond=0).isoformat(), "source": source,
           "status": STATUS_REQUESTED, "idempotency_key": key}
    return refreshed(ctx, {"ok": True, "request": row,
                           "path": trades.store([row], KIND_WATCHLIST_REQUESTS, ctx.market, ctx.clock)})


def marks(ctx: Context, tickers: list[str], adjust) -> dict[str, tuple[str, float]]:
    """{ticker: (date, close on today's basis)} of the latest stored bar by the clock."""
    bars = reads.stored_bars(ctx.con, ctx.cfg, ctx.clock, tickers)
    out = {}
    for ticker, rows in bars.groupby("ticker"):
        last = rows.iloc[-1]
        out[ticker] = (str(last["date"]), float(last["close"]) * reads.factor_after(adjust, ticker, last["date"]))
    return out


def book_now(ctx: Context):
    """(book with the open lots marked, marks, active trades) as of the clock."""
    active = reads.active_trades(reads.trade_rows(ctx.con, ctx.clock))
    adjust = reads.adjustments(ctx.con, ctx.clock)
    book = ledger.run_book(active, adjust, ctx.market, ctx.costs)
    prices = marks(ctx, sorted(book.lots), adjust)
    ledger.mark_lots(book, prices, ctx.market, ctx.costs)
    return book, prices


def header(ctx: Context) -> dict:
    """The fields every report starts with."""
    return {"market": ctx.market, "currency": ctx.cfg.get("currency"), "as_of": ctx.clock.isoformat(),
            "paper_only": True, "label": text.LABEL_PAPER_ONLY}


def positions_report(ctx: Context) -> dict:
    """Open positions per ticker, marked to the latest stored close."""
    book, prices = book_now(ctx)
    return {**header(ctx), "positions": ledger.positions(book, prices)}


def pnl_report(ctx: Context) -> dict:
    """Realised and unrealised P&L per trade and in total, before and after costs (config/costs.yaml)."""
    book, prices = book_now(ctx)
    rows = list(book.results.values())
    return {**header(ctx), "trades": [ledger.rounded(row) for row in rows], "totals": ledger.totals(rows),
            "positions": ledger.positions(book, prices)}


def list_report(ctx: Context) -> dict:
    """Every stored trade row (with its state: active, cancelled or corrected) and every watchlist request."""
    stored = reads.trade_rows(ctx.con, ctx.clock)
    done = reads.superseded_by(stored)
    rows = []
    for record in stored.to_dict("records"):
        state = "superseded" if record["id"] in done else ("cancel" if record["side"] == SIDE_CANCEL else "active")
        rows.append({**{k: (None if v != v else v) for k, v in record.items()}, "state": state,
                     "superseded_by": done.get(record["id"])})
    requests = reads.request_rows(ctx.con, ctx.clock).to_dict("records")
    return {**header(ctx), "trades": rows, "requests": requests}
