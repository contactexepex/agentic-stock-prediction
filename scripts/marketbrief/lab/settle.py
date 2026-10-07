"""F1.1-F1.9 settlement of one paper trade from stored bars (deterministic: the same stored bars give the same
row). Entry at D's raw open, exit at the raw close of the exit session (the next stored close when it is
missing: flag exit_delayed); a split or bonus with D < ex-date <= the exit multiplies the quantity by 1/factor for
the exit (flag split_in_window); the price-reached measures use the window's bars put on D's basis.
A trade is settled only once the planned exit session's bar is final (its close + BAR_SETTLE_MINUTES)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.constants.calendar import BAR_SETTLE_MINUTES
from marketbrief.constants.kinds import KIND_PAPER_TRADES_SETTLED
from marketbrief.core.calendar import is_session, session_close_utc
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.constants import (ENGINE_VERSION, FLAG_EXIT_DELAYED, FLAG_SPLIT, MONEY_DIGITS, PCT_DIGITS,
                                       PERCENT, REASON_NOTE_SKIPPED, STATUS_NO_ENTRY, STATUS_SETTLED, STATUS_SKIPPED,
                                       VIEW_ACCURACY)
from marketbrief.lab.market_data import MarketData
from marketbrief.lab.reasons import automatic_reason
from marketbrief.lab.sizing import quantity as buy_quantity
from marketbrief.utils.timefmt import as_utc_timestamp

COPIED = ("strategy_id", "family", "market", "ticker", "horizon_days", "made_at", "amount", "currency", "prob_up",
          "target_price", "lo80", "hi80", "regime")


def as_date(value) -> date:
    """A date from a date or ISO text."""
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def trade_id(prediction_id: str, view: str, pick_rule: str | None) -> str:
    """acc:<prediction> or h2h:<pick rule>:<prediction>."""
    return f"acc:{prediction_id}" if view == VIEW_ACCURACY else f"h2h:{pick_rule}:{prediction_id}"


def row_id(trade: str, settled_at: datetime) -> str:
    """<trade_id>@<settled_at as YYYYMMDDTHHMMSSZ>."""
    return f"{trade}@{as_utc_timestamp(settled_at):%Y%m%dT%H%M%SZ}"


def is_due(cfg: dict, exit_date: date, now: datetime) -> bool:
    """The planned exit session's bar is final at `now`."""
    return session_close_utc(cfg, exit_date) + timedelta(minutes=BAR_SETTLE_MINUTES) <= now


def exit_bar(data: MarketData, ticker: str, planned: date) -> tuple[date, dict] | None:
    """(the exit session used, its bar): the planned one, else the first later session with a stored close
    whose bar is final by now."""
    stored = data.bars.get(ticker) or {}
    for day in sorted(d for d in stored if d >= planned):
        bar = stored[day]
        if bar.get("close") is not None and is_session(data.cfg, day) and is_due(data.cfg, day, data.now):
            return day, bar
    return None


def window_measures(data: MarketData, pred: dict, entry: date, exit_: date, entry_price: float) -> dict:
    """F1.9 target_reached, its first session (1 = D) and the best high / worst low vs the entry, on D's basis."""
    days = sorted(d for d in data.bars.get(pred["ticker"], {}) if entry <= d <= exit_ and is_session(data.cfg, d))
    highs, lows = [], []
    for day in days:
        bar = data.bars[pred["ticker"]][day]
        factor, _ = data.split_factor(pred["ticker"], entry, day)
        if bar.get("high") is not None:
            highs.append((day, float(bar["high"]) / factor))
        if bar.get("low") is not None:
            lows.append(float(bar["low"]) / factor)
    target = pred.get("target_price")
    reached = [n for n, (_, high) in enumerate(highs, 1) if target is not None and high >= float(target)]
    return {"target_reached": None if target is None else bool(reached),
            "target_reached_session": reached[0] if reached else None,
            "max_favourable_pct": round((max(h for _, h in highs) / entry_price - 1) * PERCENT, PCT_DIGITS)
            if highs else None,
            "max_adverse_pct": round((min(lows) / entry_price - 1) * PERCENT, PCT_DIGITS) if lows else None}


def base_row(pred: dict, view: str, pick: dict | None, settled_at: datetime) -> dict:
    """The columns every outcome shares."""
    row = dict.fromkeys(SCHEMAS[KIND_PAPER_TRADES_SETTLED][1])
    pick_rule = pick["pick_rule"] if pick else None
    trade = trade_id(pred["id"], view, pick_rule)
    row.update({key: pred.get(key) for key in COPIED})
    row.update(id=row_id(trade, settled_at), trade_id=trade, prediction_id=pred["id"], view=view,
               pick_rule=pick_rule, pick_id=pick["id"] if pick else None, entry_date=str(as_date(pred["session_date"])),
               exit_date=str(as_date(pred["exit_date"])), flags=[], adjustment_ids=[], news_ids=[], reason_codes=[],
               settled_at=as_utc_timestamp(settled_at).isoformat(), method_version=ENGINE_VERSION)
    return row


def settle(pred: dict, view: str, pick: dict | None, data: MarketData, settled_at: datetime) -> dict | None:
    """One paper_trades_settled row, or None while the trade is not due yet (exit bar not final or not stored)."""
    entry, planned = as_date(pred["session_date"]), as_date(pred["exit_date"])
    if not is_due(data.cfg, planned, data.now):
        return None
    row = base_row(pred, view, pick, settled_at)
    bar = data.bar(pred["ticker"], entry)
    if not bar or bar.get("open") is None:
        row.update(status=STATUS_NO_ENTRY, reason_detail={"note": "no stored open price on D"})
        return row
    entry_price, amount = float(bar["open"]), float(pred["amount"])
    shares = buy_quantity(data.market, amount, entry_price)
    if shares <= 0:
        row.update(status=STATUS_SKIPPED, entry_price=entry_price, quantity=0.0,
                   reason_detail={"note": REASON_NOTE_SKIPPED.format(price=entry_price, amount=amount)})
        return row
    found = exit_bar(data, pred["ticker"], planned)
    if found is None:
        return None
    exit_day, last = found
    factor, adjustment_ids = data.split_factor(pred["ticker"], entry, exit_day)
    exit_quantity = round(shares / factor, 6)
    entry_value, exit_value = shares * entry_price, exit_quantity * float(last["close"])
    eurusd = (data.eurusd_on(entry), data.eurusd_on(exit_day)) if data.market == "us" else (None, None)
    cost = lab_costs.round_trip_costs(data.market, data.rates, entry_value, exit_value, shares, eurusd)
    gross = exit_value - entry_value
    net = gross - cost["total"]
    flags = ([FLAG_EXIT_DELAYED] if exit_day != planned else []) + ([FLAG_SPLIT] if adjustment_ids else [])
    target, lo80, hi80 = pred.get("target_price"), pred.get("lo80"), pred.get("hi80")
    exit_price = float(last["close"])
    range_hit = None if lo80 is None or hi80 is None else bool(float(lo80) <= exit_price / factor <= float(hi80))
    measures = window_measures(data, pred, entry, exit_day, entry_price)
    move = (exit_value / entry_value - 1) * PERCENT
    row.update(status=STATUS_SETTLED, exit_date_actual=str(exit_day), flags=flags, entry_price=entry_price,
               exit_price=exit_price, quantity=shares, exit_quantity=exit_quantity, adjustment_ids=adjustment_ids,
               entry_value=round(entry_value, MONEY_DIGITS), exit_value=round(exit_value, MONEY_DIGITS),
               gross_pnl=round(gross, MONEY_DIGITS), costs=cost["total"], cost_lines=cost["lines"],
               net_pnl=round(net, MONEY_DIGITS), return_pct=round(net / amount * PERCENT, PCT_DIGITS),
               target_error_pct=None if target is None else round((exit_price / factor / float(target) - 1) * PERCENT,
                                                                  PCT_DIGITS),
               range_hit=range_hit, **measures)
    row.update(automatic_reason(data, pred["ticker"], (entry, exit_day), move, (measures["target_reached"],
                                                                                 range_hit)))
    return row
