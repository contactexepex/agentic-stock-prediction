"""All paper trades in one place (B13, owner request of 2026-10-12; docs/ws/b13.md): rm.portfolio's `all_trades`
block, as of the cut-off. Research only: a paper trade is a record, never an order.

- Strategy trades, each view apart (never pooled: the two views are of the same predictions): scope `all` = the
  accuracy view (every strategy's qualifying predictions), scope `head_to_head` = the head-to-head view. Open: B4's
  Open-trade records (rm_common.open_trades, entered from D's open, priced from the daily bar or the intraday check).
  Closed: the newest settlement of each trade (rm_common.settled_trades, with its your-cost view); win / loss / flat
  on the net P&L after market cost (the scoreboard's basis), the your-cost figures beside it. A settlement that never
  entered (no_entry, skipped_price_above_amount) is listed as not_entered (with that reason) and left out of every
  count. A closed row's exit_date is the actual exit; an open row's the planned one.
- The owner's own trades (scope and family `mine`; WS4's FIFO ledger of the active trades): an open row is a buy with
  an open quantity (side buy, its open quantity), a closed row is a sell with its realised net after your cost over
  the FIFO lots it closes (side sell, entry_date null; pnl_market null; win / loss on pnl_your). Strategy fields null.
- Open rows carry unrealised_pnl / unrealised_pct before costs (pnl_* null, outcome null); closed rows pnl_* after
  costs. The summary sums closed rows only.
- Page `_` (all_trades): the summary of every trade (per scope and family, to date and in the last WINDOW_SESSIONS
  sessions to the as-of date), the listed trades (every open one, and the closed or not-entered ones whose exit is in
  that window; the accuracy view only while LIST_ACCURACY_ON_MARKET_PAGE, step 1 of the size fix) and the index of
  the accuracy-view session pages. The accuracy view (about 200 trades
  a session) is listed per entry session D on its own page `trades:<D>` (the last SESSION_PAGES sessions), so the
  market's page does not grow with the trade count (owner's size concern, 2026-10-12)."""

from __future__ import annotations

from marketbrief.portfolio import service as portfolio_service
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import rm_common, rm_company
from marketbrief.warehouse.rm_company import first_of, sessions_back
from marketbrief.warehouse.rm_entities import iso_day
from marketbrief.warehouse.rm_registry import BuildContext

WINDOW_SESSIONS = 10
SESSION_PAGES = 60  # accuracy-view trades: one page per entry session, the last 60 (owner's size concern, 2026-10-12)
SESSION_KEY_PREFIX = "trades:"
# Step 2 of the size fix (docs/ws/b13.md): the accuracy-view rows are listed on the session pages only, now that the
# deployed Paper portfolios page reads them there (True was step 1, while the deployed card listed them from `_`).
LIST_ACCURACY_ON_MARKET_PAGE = False
SESSION_COUNT_KEYS = (
    "open", "closed", "wins", "losses", "flat", "win_rate", "net_pnl_market", "net_pnl_your", "unrealised_pnl",
    "flagged_open",
)  # fmt: skip
RANGE_KEYS = ("lo80", "lo50", "hi50", "hi80", "target_price", "to_target_pct")  # an open strategy trade's own range
CHECK_KEYS = ("check_at", "band", "flags", "flagged", "ret_since_entry_pct")  # its latest intraday check
SCOPE_ALL, SCOPE_HEAD_TO_HEAD, SCOPE_MINE = "all", "head_to_head", "mine"
SCOPE_OF_VIEW = {"accuracy": SCOPE_ALL, "head_to_head": SCOPE_HEAD_TO_HEAD}
FAMILY_ALL, FAMILY_MINE = "all", "mine"
STRATEGY_FAMILIES = ("rule", "ai", "baseline")
STATE_OPEN, STATE_CLOSED, STATE_NOT_ENTERED = "open", "closed", "not_entered"
OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_FLAT = "win", "loss", "flat"
PERIOD_TO_DATE, PERIOD_WINDOW = "to_date", "window"
SOURCE_DAILY_BAR, SOURCE_DAILY_CLOSE = "daily_bar", "daily_close"  # B4's entry_price_source / last_price_source
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
        "id", "scope", "view", "strategy_id", "family", "pick_rule", "side", "ticker", "horizon_days", "entry_date",
        "exit_date", "state", "not_entered_reason", "outcome", "entry_price", "entry_price_source",
        "exit_or_last_price", "last_price_source", "last_price_date", "last_price_time", "price_pending", "quantity",
        "amount", "currency", "unrealised_pnl", "unrealised_pct", "pnl_market", "pnl_your", "return_pct_market",
        "return_pct_your", "settled_at", *RANGE_KEYS, "check",
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
                not_entered_reason=None if entered else row["status"],
                outcome=outcome(pnl),
                entry_price=json_safe_float(row.get("entry_price")),
                entry_price_source=SOURCE_DAILY_BAR if entered else None,
                exit_or_last_price=json_safe_float(row.get("exit_price")),
                last_price_source=SOURCE_DAILY_CLOSE if entered else None,
                last_price_date=iso_day(row.get("exit_date_actual")) if entered else None,
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


def latest_checks(ctx: BuildContext) -> dict[str, dict]:
    """trade_id -> its row of the market's latest intraday trade check by the cut-off (B12's market_trade_checks), in
    CHECK_KEYS."""
    return {row["trade_id"]: {key: row.get(key) for key in CHECK_KEYS} for row in rm_company.market_trade_checks(ctx)}


def open_strategy_trades(ctx: BuildContext, settled_ids: set[str]) -> list[dict]:
    """B4's Open-trade records (from D's open) without a settlement stored by the cut-off, with their own range and
    their latest intraday check (null when the latest check has no row for the trade)."""
    checks = latest_checks(ctx)
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
                entry_price_source=trade.get("entry_price_source", SOURCE_DAILY_BAR),
                exit_or_last_price=trade.get("last_price"),
                last_price_source=trade.get("last_price_source", SOURCE_DAILY_CLOSE),
                last_price_date=trade.get("last_price_date"),
                last_price_time=trade.get("last_price_time"),
                price_pending=bool(trade.get("price_pending", False)),
                quantity=trade.get("quantity"),
                amount=trade.get("amount"),
                currency=trade.get("currency"),
                unrealised_pnl=money(trade.get("unrealised_pnl")),
                unrealised_pct=trade.get("unrealised_pct"),
                **{key: json_safe_float(trade.get(key)) for key in RANGE_KEYS},
                check=checks.get(trade["trade_id"]),
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
            gross = json_safe_float(row.get("unrealised_gross"))
            basis = row["price"] * row["open_quantity"]
            out.append(
                trade_row(
                    **common,
                    side=SIDE_BUY,
                    entry_date=row["trade_date"],
                    state=STATE_OPEN,
                    entry_price=row["price"],
                    exit_or_last_price=row.get("mark"),
                    last_price_source=SOURCE_DAILY_CLOSE if row.get("mark") is not None else None,
                    last_price_date=row.get("mark_date"),
                    quantity=row["open_quantity"],
                    unrealised_pnl=money(gross),
                    unrealised_pct=None if gross is None or not basis else round(gross / basis * 100, PCT_DIGITS + 1),
                )  # fmt: skip
            )
        elif row["side"] == SIDE_SELL:
            pnl = money(row.get("realised_net"))
            out.append(
                trade_row(
                    **common,
                    side=SIDE_SELL,
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
    unrealised = [t["unrealised_pnl"] for t in trades if t["state"] == STATE_OPEN and t["unrealised_pnl"] is not None]
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
        "unrealised_pnl": round(sum(unrealised), MONEY_DIGITS) if unrealised else None,
        "flagged_open": sum(1 for t in trades if t["state"] == STATE_OPEN and (t["check"] or {}).get("flagged")),
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


def ordered(trades: list[dict]) -> list[dict]:
    """Open first, then by exit (else entry) date newest first, then by id."""
    out = sorted(trades, key=lambda t: t["id"])
    out.sort(key=lambda t: t["exit_date"] or t["entry_date"] or "", reverse=True)
    out.sort(key=lambda t: t["state"] != STATE_OPEN)
    return out


def every_trade(ctx: BuildContext, context) -> list[dict]:
    """Every trade row of the market as of the cut-off: strategy trades of both views and the owner's (memoised)."""

    def compute() -> list[dict]:
        closed = closed_strategy_trades(ctx)
        strategy = closed + open_strategy_trades(ctx, {t["id"] for t in closed})
        return [t for t in strategy if t["scope"] is not None] + owner_trades(ctx, context)

    return ctx.shared("b13_every_trade", compute)


def accuracy_sessions(ctx: BuildContext, trades: list[dict]) -> dict[str, list[dict]]:
    """The accuracy-view trades by entry session D, for the last SESSION_PAGES sessions to the newest of the session
    being traded and the as-of date (older entry sessions have no page), newest session first."""
    rows = [t for t in trades if t["scope"] == SCOPE_ALL]
    last = max(filter(None, (rm_common.status_block(ctx)["session"]["session_date"], ctx.as_of)), default=None)
    days = set(sessions_back(ctx.cfg, last, SESSION_PAGES))
    out: dict[str, list[dict]] = {}
    for trade in rows:
        if trade["entry_date"] in days:
            out.setdefault(trade["entry_date"], []).append(trade)
    return {day: ordered(out[day]) for day in sorted(out, reverse=True)}


def session_entry(day: str, trades: list[dict]) -> dict:
    """One line of the per-session index: what the session's page holds, counted as the summary counts."""
    row = summary_row(SCOPE_ALL, FAMILY_ALL, PERIOD_TO_DATE, trades, None)
    return {
        "session_date": day,
        "entered": len(trades),
        "not_entered": sum(1 for t in trades if t["state"] == STATE_NOT_ENTERED),
        **{key: row[key] for key in SESSION_COUNT_KEYS},
    }


def all_trades(ctx: BuildContext, context) -> dict:
    """rm.portfolio's `all_trades` block (page `_`): the window, the summary of every trade, the listed trades (open,
    and closed or not entered with the exit in the window; the accuracy view only while LIST_ACCURACY_ON_MARKET_PAGE)
    and the index of the accuracy-view session pages (`session_pages`)."""
    trades = every_trade(ctx, context)
    window_from = first_of(sessions_back(ctx.cfg, ctx.as_of, WINDOW_SESSIONS))
    listed = [
        t for t in trades if listed_in(t, window_from) and (LIST_ACCURACY_ON_MARKET_PAGE or t["scope"] != SCOPE_ALL)
    ]
    return {
        "window": {"sessions": WINDOW_SESSIONS, "from": window_from, "to": ctx.as_of},
        "summary": summary(trades, window_from, ctx.cfg.get("currency")),
        "trades": ordered(listed),
        "sessions": [session_entry(day, rows) for day, rows in accuracy_sessions(ctx, trades).items()],
    }


def session_key(day: str) -> str:
    return f"{SESSION_KEY_PREFIX}{day}"


def session_pages(ctx: BuildContext, context) -> dict[str, dict]:
    """rm.portfolio `trades:<D>`: every accuracy-view trade entered on session D (open, closed or not entered), one
    page per session of the index (GET /markets/{m}/portfolios/sessions/{date}; no page: 404)."""
    pages = {}
    for day, rows in accuracy_sessions(ctx, every_trade(ctx, context)).items():
        pages[session_key(day)] = {
            "market": ctx.market,
            "as_of": ctx.as_of,
            "session_date": day,
            "summary": session_entry(day, rows),
            "trades": rows,
            "paper": True,
        }
    return pages
