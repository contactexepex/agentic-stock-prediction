"""All paper trades in one place (B13, owner request of 2026-10-12; docs/ws/b13.md): rm.portfolio's `all_trades`
block, as of the cut-off. Research only: a paper trade is a record, never an order.

- Strategy trades, each view apart (never pooled: the two views are of the same predictions): scope `all` = the
  accuracy view (every strategy's qualifying predictions), scope `head_to_head` = the head-to-head view. Open: B4's
  Open-trade records (rm_common.open_trades, entered from D's open, priced from the daily bar or the intraday check).
  Closed: the newest settlement of each trade (rm_common.settled_trades, with its your-cost view); win / loss / flat
  on the net P&L after market cost (the scoreboard's basis), the your-cost figures beside it. A settlement that never
  entered (no_entry, skipped_price_above_amount) is listed as not_entered and left out of every count.
- The owner's own trades (scope and family `mine`; WS4's FIFO ledger, on your cost only): each buy with an open
  quantity is an open trade, each sell a closed one with its realised net after your cost (pnl_market null; win /
  loss on pnl_your).
- Listed: every open trade, and the closed trades whose exit is in the last WINDOW_SESSIONS sessions to the as-of
  date. Summary: per scope and family, to date and in that window."""

from __future__ import annotations

from marketbrief.portfolio import service as portfolio_service
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_company import first_of, sessions_back
from marketbrief.warehouse.rm_entities import iso_day
from marketbrief.warehouse.rm_registry import BuildContext

WINDOW_SESSIONS = 10
SCOPE_ALL, SCOPE_HEAD_TO_HEAD, SCOPE_MINE = "all", "head_to_head", "mine"
SCOPE_OF_VIEW = {"accuracy": SCOPE_ALL, "head_to_head": SCOPE_HEAD_TO_HEAD}
FAMILY_ALL, FAMILY_MINE = "all", "mine"
STRATEGY_FAMILIES = ("rule", "ai", "baseline")
STATE_OPEN, STATE_CLOSED, STATE_NOT_ENTERED = "open", "closed", "not_entered"
OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_FLAT = "win", "loss", "flat"
PERIOD_TO_DATE, PERIOD_WINDOW = "to_date", "window"
SOURCE_DAILY_BAR = "daily_bar"
STATUS_SETTLED = "settled"
SIDE_BUY, SIDE_SELL = "buy", "sell"
MONEY_DIGITS, PCT_DIGITS = 2, 1


def outcome(pnl: float | None) -> str | None:
    if pnl is None:
        return None
    return OUTCOME_WIN if pnl > 0 else OUTCOME_LOSS if pnl < 0 else OUTCOME_FLAT


def money(value) -> float | None:
    value = json_safe_float(value)
    return None if value is None else round(value, MONEY_DIGITS)


def trade_row(**fields) -> dict:
    """One listed trade in the block's fields (every key present; null when it does not apply)."""
    keys = (
        "id", "scope", "view", "strategy_id", "family", "pick_rule", "ticker", "horizon_days", "entry_date",
        "exit_date", "state", "outcome", "entry_price", "entry_source", "exit_or_last_price", "last_source",
        "last_price_date", "price_pending", "quantity", "amount", "currency", "pnl_market", "pnl_your",
        "return_pct_market", "return_pct_your", "settled_at",
    )  # fmt: skip
    return {**{key: fields.get(key) for key in keys}, "paper": True}


def closed_strategy_trades(ctx: BuildContext) -> list[dict]:
    """The newest settlement of every live strategy trade stored by the cut-off (collected companies)."""
    out = []
    for row in rm_common.settled_trades(ctx):
        entered = row["status"] == STATUS_SETTLED
        pnl = money(row.get("net_pnl")) if entered else None
        out.append(
            trade_row(
                id=row["trade_id"],
                scope=SCOPE_OF_VIEW.get(row["view"]),
                view=row["view"],
                strategy_id=row["strategy_id"],
                family=row["family"],
                pick_rule=row.get("pick_rule"),
                ticker=row["ticker"],
                horizon_days=row["horizon_days"],
                entry_date=iso_day(row["entry_date"]),
                exit_date=iso_day(row.get("exit_date_actual") or row["exit_date"]),
                state=STATE_CLOSED if entered else STATE_NOT_ENTERED,
                outcome=outcome(pnl),
                entry_price=json_safe_float(row.get("entry_price")),
                entry_source=SOURCE_DAILY_BAR if entered else None,
                exit_or_last_price=json_safe_float(row.get("exit_price")),
                last_source=SOURCE_DAILY_BAR if entered else None,
                price_pending=False,
                quantity=json_safe_float(row.get("quantity")),
                amount=json_safe_float(row.get("amount")),
                currency=row.get("currency"),
                pnl_market=pnl,
                pnl_your=money(row.get("net_pnl_your")) if entered else None,
                return_pct_market=json_safe_float(row.get("return_pct")) if entered else None,
                return_pct_your=json_safe_float(row.get("return_pct_your")) if entered else None,
                settled_at=rm_common.iso_z(row["settled_at"]),
            )  # fmt: skip
        )
    return out


def open_strategy_trades(ctx: BuildContext, settled_ids: set[str]) -> list[dict]:
    """B4's Open-trade records (from D's open) without a settlement stored by the cut-off."""
    out = []
    for trade in rm_common.open_trades(ctx):
        if trade["trade_id"] in settled_ids:
            continue
        out.append(
            trade_row(
                id=trade["trade_id"],
                scope=SCOPE_OF_VIEW.get(trade["view"]),
                view=trade["view"],
                strategy_id=trade["strategy_id"],
                family=trade["family"],
                pick_rule=trade.get("pick_rule"),
                ticker=trade["ticker"],
                horizon_days=trade["horizon_days"],
                entry_date=trade["entry_date"],
                exit_date=trade["exit_date"],
                state=STATE_OPEN,
                entry_price=trade.get("entry_price"),
                entry_source=trade.get("entry_source", SOURCE_DAILY_BAR),
                exit_or_last_price=trade.get("last_price"),
                last_source=trade.get("last_source", SOURCE_DAILY_BAR),
                last_price_date=trade.get("last_price_date"),
                price_pending=bool(trade.get("price_pending", False)),
                quantity=trade.get("quantity"),
                amount=trade.get("amount"),
                currency=trade.get("currency"),
                pnl_market=money(trade.get("unrealised_pnl")),
                return_pct_market=trade.get("unrealised_pct"),
            )  # fmt: skip
        )
    return out


def owner_trades(ctx: BuildContext, context) -> list[dict]:
    """The owner's paper trades from WS4's ledger as of the cut-off (collected companies): open buys, closed sells."""
    report = portfolio_service.pnl_report(context)
    currency = ctx.cfg.get("currency")
    out = []
    for row in report["trades"]:
        if row["ticker"] not in ctx.collected:
            continue
        common = {"id": row["id"], "scope": SCOPE_MINE, "family": FAMILY_MINE, "ticker": row["ticker"],
                  "currency": currency, "price_pending": False}  # fmt: skip
        if row["side"] == SIDE_BUY and (row.get("open_quantity") or 0) > 0:
            out.append(
                trade_row(
                    **common,
                    entry_date=row["trade_date"],
                    state=STATE_OPEN,
                    entry_price=row["price"],
                    exit_or_last_price=row.get("mark"),
                    last_source=SOURCE_DAILY_BAR if row.get("mark") is not None else None,
                    last_price_date=row.get("mark_date"),
                    quantity=row["open_quantity"],
                    pnl_your=money(row.get("unrealised_net")),
                )  # fmt: skip
            )
        elif row["side"] == SIDE_SELL:
            pnl = money(row.get("realised_net"))
            out.append(
                trade_row(
                    **common,
                    exit_date=row["trade_date"],
                    state=STATE_CLOSED,
                    outcome=outcome(pnl),
                    exit_or_last_price=row["price"],
                    quantity=row["quantity"],
                    pnl_your=pnl,
                )  # fmt: skip
            )
    return out


def listed_in(trade: dict, window_from: str | None) -> bool:
    """Open, or closed / not entered with its exit in the window."""
    return trade["state"] == STATE_OPEN or (window_from is not None and (trade["exit_date"] or "") >= window_from)


def counted(trade: dict) -> float | None:
    """The P&L a trade's win / loss is read on: after market cost for strategy trades, after your cost for mine."""
    return trade["pnl_your"] if trade["scope"] == SCOPE_MINE else trade["pnl_market"]


def summary_row(scope: str, family: str, period: str, trades: list[dict], currency: str | None) -> dict:
    open_count = sum(1 for t in trades if t["state"] == STATE_OPEN)
    closed = [t for t in trades if t["state"] == STATE_CLOSED]
    outcomes = [outcome(counted(t)) for t in closed]
    wins, losses, flat = (outcomes.count(name) for name in (OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_FLAT))
    decided = wins + losses + flat
    market = [t["pnl_market"] for t in closed if t["pnl_market"] is not None]
    your = [t["pnl_your"] for t in closed if t["pnl_your"] is not None]
    return {
        "scope": scope,
        "family": family,
        "period": period,
        "open": open_count,
        "closed": len(closed),
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate": round(wins / decided * 100, PCT_DIGITS) if decided else None,
        "net_pnl_market": round(sum(market), MONEY_DIGITS) if market else None,
        "net_pnl_your": round(sum(your), MONEY_DIGITS) if your else None,
        "pnl_your_missing": sum(1 for t in closed if t["pnl_your"] is None),
        "currency": currency,
    }


def summary(trades: list[dict], window_from: str | None, currency: str | None) -> list[dict]:
    """Per scope and family, to date and in the window (open trades in both; closed ones by their exit date)."""
    in_window = [t for t in trades if listed_in(t, window_from)]
    groups = [(SCOPE_ALL, family) for family in (FAMILY_ALL, *STRATEGY_FAMILIES)]
    groups += [(SCOPE_HEAD_TO_HEAD, family) for family in (FAMILY_ALL, *STRATEGY_FAMILIES)]
    groups.append((SCOPE_MINE, FAMILY_MINE))
    out = []
    for period, rows in ((PERIOD_TO_DATE, trades), (PERIOD_WINDOW, in_window)):
        for scope, family in groups:
            members = [t for t in rows if t["scope"] == scope and family in (FAMILY_ALL, t["family"])]
            out.append(summary_row(scope, family, period, members, currency))
    return out


def all_trades(ctx: BuildContext, context) -> dict:
    """rm.portfolio's `all_trades` block: the window, the summary and the listed trades (open first, then by exit
    date newest first, then by id)."""
    closed = closed_strategy_trades(ctx)
    strategy = closed + open_strategy_trades(ctx, {t["id"] for t in closed})
    trades = [t for t in strategy if t["scope"] is not None] + owner_trades(ctx, context)
    days = sessions_back(ctx.cfg, ctx.as_of, WINDOW_SESSIONS)
    window_from = first_of(days)
    listed = [t for t in trades if listed_in(t, window_from)]
    listed.sort(key=lambda t: t["id"])
    listed.sort(key=lambda t: t["exit_date"] or t["entry_date"] or "", reverse=True)
    listed.sort(key=lambda t: t["state"] != STATE_OPEN)
    return {
        "window": {"sessions": WINDOW_SESSIONS, "from": window_from, "to": ctx.as_of},
        "summary": summary(trades, window_from, ctx.cfg.get("currency")),
        "trades": listed,
    }
