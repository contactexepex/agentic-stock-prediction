"""The Paper portfolio page's trades by hold and by sell day (UX3, docs/ux/paper_portfolio_redesign.md v3; owner
approval 2026-10-12), from all_trades.every_trade as of the cut-off. Research only: a paper trade is a record, never an
order.

- `open:<k>`: every open accuracy-view trade of hold k (bought at the open of D, sold at the close of the k-th session
  after D), whatever its entry session; index `open_holds` (all_trades block) with the hold's split and the split per
  family (going with / against the prediction / no price yet, flagged, profit and loss so far, before costs).
- `finished:<D>`: the accuracy view's closed and not-entered trades that exited on session D, the last
  all_trades.WINDOW_SESSIONS sessions; index `finished_sessions` with the counts per family (not entered never counted).
- `learning`: trade_why.learning (what the system learns, as stored).
Going with or against is read on the price since the buy; a "down" prediction flips it (owner, 2026-10-12)."""

from __future__ import annotations

from marketbrief.warehouse import rm_common, trade_why
from marketbrief.warehouse.all_trades import (
    FAMILY_ALL, MONEY_DIGITS, PERIOD_TO_DATE, SCOPE_ALL, STATE_NOT_ENTERED, STATE_OPEN, STRATEGY_FAMILIES,
    WINDOW_SESSIONS, every_trade, ordered, summary_row,
)  # fmt: skip
from marketbrief.warehouse.rm_company import sessions_back
from marketbrief.warehouse.rm_registry import BuildContext

OPEN_KEY_PREFIX, FINISHED_KEY_PREFIX = "open:", "finished:"
GOING_WITH, GOING_AGAINST, GOING_PENDING = "with", "against", "pending"
DIRECTION_DOWN = "down"


def going(trade: dict) -> str:
    """An open trade against its prediction, on the price since the buy: with (moved the predicted way), against (did
    not), pending (no price yet). A "down" prediction flips the test (owner, 2026-10-12)."""
    entry, last = trade["entry_price"], trade["exit_or_last_price"]
    if trade["price_pending"] or entry is None or last is None:
        return GOING_PENDING
    moved = last - entry
    return GOING_WITH if (moved < 0 if trade.get("direction") == DIRECTION_DOWN else moved > 0) else GOING_AGAINST


def money_sum(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values), MONEY_DIGITS) if values else None


def open_split(trades: list[dict]) -> dict:
    """Counts and money of open trades: going with / against / pending, flagged, profit and loss so far."""
    ways = [going(t) for t in trades]
    pnl = [t["unrealised_pnl"] for t in trades if t["unrealised_pnl"] is not None]
    return {
        "open": len(trades),
        "going_with": ways.count(GOING_WITH),
        "going_against": ways.count(GOING_AGAINST),
        "pending": ways.count(GOING_PENDING),
        "flagged": sum(1 for t in trades if (t["check"] or {}).get("flagged")),
        "profit": money_sum(v for v in pnl if v > 0),
        "loss": money_sum(v for v in pnl if v < 0),
        "unrealised_pnl": money_sum(pnl),
    }


def open_by_hold(trades: list[dict]) -> dict[int, list[dict]]:
    """The accuracy view's open trades per hold, shortest first, each ordered by its planned exit then id."""
    out: dict[int, list[dict]] = {}
    for trade in trades:
        if trade["scope"] == SCOPE_ALL and trade["state"] == STATE_OPEN and trade["horizon_days"]:
            out.setdefault(trade["horizon_days"], []).append(trade)
    return {k: sorted(out[k], key=lambda t: (t["exit_date"] or "", t["id"])) for k in sorted(out)}


def hold_entry(k: int, trades: list[dict]) -> dict:
    """One line of the open_holds index: the hold's split, its planned exits and the split per family."""
    return {
        "horizon_days": k,
        **open_split(trades),
        "exit_dates": sorted({t["exit_date"] for t in trades if t["exit_date"]}),
        "by_family": [{"family": f, **open_split([t for t in trades if t["family"] == f])} for f in STRATEGY_FAMILIES],
    }


def finished_window(ctx: BuildContext) -> list[str]:
    """The last WINDOW_SESSIONS sessions to the newest of the session being traded and the as-of date."""
    last = max(filter(None, (rm_common.status_block(ctx)["session"]["session_date"], ctx.as_of)), default=None)
    return sessions_back(ctx.cfg, last, WINDOW_SESSIONS)


def finished_by_session(ctx: BuildContext, trades: list[dict]) -> dict[str, list[dict]]:
    """The accuracy view's closed and not-entered trades per exit session of the window, newest session first."""
    days = set(finished_window(ctx))
    out: dict[str, list[dict]] = {}
    for trade in trades:
        if trade["scope"] == SCOPE_ALL and trade["state"] != STATE_OPEN and trade["exit_date"] in days:
            out.setdefault(trade["exit_date"], []).append(trade)
    return {day: ordered(out[day]) for day in sorted(out, reverse=True)}


def finished_entry(day: str, trades: list[dict]) -> dict:
    """One line of the finished_sessions index: the session's counts and money per family (market and your cost)."""

    def split(rows: list[dict]) -> dict:
        row = summary_row(SCOPE_ALL, FAMILY_ALL, PERIOD_TO_DATE, rows, None)
        return {key: row[key] for key in ("closed", "wins", "losses", "flat", "net_pnl_market", "net_pnl_your")}

    return {
        "session_date": day,
        "not_entered": sum(1 for t in trades if t["state"] == STATE_NOT_ENTERED),
        **split(trades),
        "by_family": [{"family": f, **split([t for t in trades if t["family"] == f])} for f in STRATEGY_FAMILIES],
    }


def open_pages(ctx: BuildContext, context) -> dict[str, dict]:
    """rm.portfolio `open:<k>`: every open accuracy-view trade of hold k (GET /markets/{m}/portfolios/open/{k}; no page
    for a hold without open trades: 404)."""
    return {
        f"{OPEN_KEY_PREFIX}{k}": {
            "market": ctx.market,
            "as_of": ctx.as_of,
            "horizon_days": k,
            "summary": hold_entry(k, rows),
            "trades": rows,
            "paper": True,
        }  # fmt: skip
        for k, rows in open_by_hold(every_trade(ctx, context)).items()
    }


def finished_pages(ctx: BuildContext, context) -> dict[str, dict]:
    """rm.portfolio `finished:<D>`: every accuracy-view trade that exited on session D (closed or not entered), the
    last WINDOW_SESSIONS sessions (GET /markets/{m}/portfolios/finished/{date}; others 404)."""
    return {
        f"{FINISHED_KEY_PREFIX}{day}": {
            "market": ctx.market,
            "as_of": ctx.as_of,
            "session_date": day,
            "summary": finished_entry(day, rows),
            "trades": rows,
            "paper": True,
        }  # fmt: skip
        for day, rows in finished_by_session(ctx, every_trade(ctx, context)).items()
    }


def indexes(ctx: BuildContext, context) -> dict:
    """The all_trades block's UX3 keys: open_holds, finished_sessions and learning."""
    trades = every_trade(ctx, context)
    return {
        "open_holds": [hold_entry(k, rows) for k, rows in open_by_hold(trades).items()],
        "finished_sessions": [finished_entry(day, rows) for day, rows in finished_by_session(ctx, trades).items()],
        "learning": trade_why.learning(ctx),
    }
