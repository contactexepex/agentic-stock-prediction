"""The blocks every page payload shares (docs/ws/b4.md "Shared blocks"; fields as in docs/DATA_CATALOGUE.md and the
mockups' notes.md), computed once per build through BuildContext.shared so every page shows the same values:

  header(ctx)        market, name, currency, as_of                    (Market status `market`, `name`, ...)
  horizons(ctx)      horizons (config/strategies.yaml), default_horizon N+1 (decision 39)
  status_block(ctx)  the Market status record without its serve-time freshness (schema StatusBlock)
  strategies(ctx)    the 15 registry entries keyed by id, with live and settled_trades (schema StrategyEntry)
  go_live(ctx)       proven, months_forward, trades_needed, beats_best_baseline of the reference strategy's
                     accuracy row, all horizons, forward basis (schema GoLive)
  lab_summary(ctx)   B2's scoreboard, comparisons and heatmap data of the settled trades stored by the cut-off

Every read is as of ctx.cutoff (each row's own storage time); times are ISO UTC with a Z."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from marketbrief.constants.warehouse import (
    DEFAULT_HORIZON,
    GO_LIVE_FIELDS,
    POST_CLOSE_LOCAL,
    REFERENCE_STRATEGY,
    STRATEGY_FIELDS,
)
from marketbrief.core import calendar
from marketbrief.lab import reads as lab_reads
from marketbrief.lab import registry
from marketbrief.lab.constants import GO_LIVE_TRADES, STATUS_SETTLED, VIEW_ACCURACY
from marketbrief.lab import compare, heatmaps, scoreboard
from marketbrief.lab.scoreboard import latest_settlements
from marketbrief.pipeline.market_status import status as market_session
from marketbrief.warehouse.rm_registry import BuildContext

ALL_HORIZONS = "all"
BASIS_FORWARD = "forward"
SCOPE_STRATEGY = "strategy"
RUN_OK = "ok"
RUN_MARKET_CLOSED = "market_closed"
FEATURES_RUN_SQL = "SELECT max(computed_at) FROM features WHERE computed_at <= ?::TIMESTAMPTZ"
INTRADAY_RUNS_SQL = """SELECT check_at, status FROM intraday_runs WHERE computed_at <= ?::TIMESTAMPTZ
AND session_date = ?::DATE AND status <> ? ORDER BY check_at, id"""
POST_CLOSE_SQL = """SELECT max(done_at) FROM (
  SELECT max(created_at) AS done_at FROM eod_analyses WHERE created_at <= ?::TIMESTAMPTZ
  UNION ALL SELECT max(settled_at) FROM paper_trades_settled WHERE settled_at <= ?::TIMESTAMPTZ)"""
NEWS_RUN_SQL = """SELECT ran_at, ok, new_items FROM news_runs WHERE ran_at <= ?::TIMESTAMPTZ
ORDER BY ran_at DESC, id DESC LIMIT 1"""
SESSION_FIELDS = (
    "local_time",
    "trading_day",
    "session_date",
    "previous_session",
    "calendar_covered",
    "session_open_utc",
    "session_close_utc",
    "in_session",
    "late_run",
)
FIVE_SESSIONS = 5
LOOKAHEAD_DAYS = 15  # a post-close run is found within this many days (longest exchange closure is far shorter)


def iso_z(value) -> str | None:
    """An aware time as ISO UTC with a Z (`2026-10-07T02:10:00Z`), or None."""
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def header(ctx: BuildContext) -> dict:
    """The page header: market, name, currency, as_of."""
    data = ctx.dashboard
    return {"market": ctx.market, "name": data["name"], "currency": data["currency"], "as_of": data["as_of"]}


def horizons(_ctx: BuildContext) -> dict:
    """The horizon list (config/strategies.yaml) and the one a page opens on; takes the context like every block."""
    return {"horizons": list(registry.horizons()), "default_horizon": DEFAULT_HORIZON}


def level_block(tile: dict | None) -> dict | None:
    """A market-level symbol (benchmark or vol index) from the dashboard's tile: last close, its date, the change
    from the previous close and from the close 5 sessions earlier, in percent (2 decimals)."""
    if not tile or not tile.get("last"):
        return None
    last, closes = tile["last"], [close for _day, close in tile.get("spark") or []]
    five = (
        closes[-1] / closes[-1 - FIVE_SESSIONS] - 1
        if len(closes) > FIVE_SESSIONS and closes[-1 - FIVE_SESSIONS]
        else None
    )
    return {
        "symbol": tile["key"],
        "name": tile["name"],
        "close": last["close"],
        "close_date": last["date"],
        "change_pct": None if last["change"] is None else round(last["change"] * 100, 2),
        "change_5d_pct": None if five is None else round(five * 100, 2),
    }


def next_post_close(cfg: dict, cutoff_time: datetime) -> str | None:
    """The next scheduled post-close run after the cut-off: the market's local start time on a session day."""
    zone = ZoneInfo(cfg["timezone"])
    hour, minute = (int(part) for part in POST_CLOSE_LOCAL[cfg["market"]].split(":"))
    day = cutoff_time.astimezone(zone).date()
    for _ in range(LOOKAHEAD_DAYS):
        start = datetime.combine(day, time(hour, minute), zone)
        if start > cutoff_time and calendar.is_session(cfg, day):
            return iso_z(start)
        day += timedelta(days=1)
    return None


def runs(ctx: BuildContext, session_date: str) -> dict:
    """The newest runs stored by the cut-off: pre-open (the newest features snapshot), the intraday checks of the
    session being predicted, post-close (the newest settlement or end-of-day analysis) and news (news_runs)."""
    con, cutoff = ctx.con, ctx.cutoff
    pre_open = con.execute(FEATURES_RUN_SQL, [cutoff]).fetchone()[0]
    intraday = con.execute(INTRADAY_RUNS_SQL, [cutoff, session_date, RUN_MARKET_CLOSED]).fetchall()
    post_close = con.execute(POST_CLOSE_SQL, [cutoff, cutoff]).fetchone()[0]
    news = con.execute(NEWS_RUN_SQL, [cutoff]).fetchone()
    return {
        "pre_open": {"at": iso_z(pre_open), "ok": True if pre_open is not None else None},
        "intraday": [{"at": iso_z(at), "ok": status == RUN_OK} for at, status in intraday],
        "post_close": {
            "at": iso_z(post_close),
            "ok": True if post_close is not None else None,
            "next_at": next_post_close(ctx.cfg, ctx.cutoff_time),
        },
        "news": {
            "at": iso_z(news[0]) if news else None,
            "ok": bool(news[1]) if news and news[1] is not None else None,
            "new_items": int(news[2]) if news and news[2] is not None else None,
        },
    }


def status_block(ctx: BuildContext) -> dict:
    """The Market status record (schema StatusBlock) as of the cut-off. `freshness` is added when served."""

    def compute() -> dict:
        data = ctx.dashboard
        session = market_session(ctx.cfg, ctx.cutoff_time)
        overview = data.get("overview") or {}
        regime = overview.get("regime") or {}
        return {
            **header(ctx),
            "session": {key: session[key] for key in SESSION_FIELDS},
            "regime": regime.get("code"),
            "benchmark": level_block(overview.get("benchmark")),
            "vol_index": level_block(overview.get("vol_index")),
            "runs": runs(ctx, session["session_date"]),
            "paper_label": data["skill"]["label"],
        }

    return ctx.shared("status_block", compute)


def lab_summary(ctx: BuildContext) -> dict:
    """B2's lab summary ({scoreboard, comparisons, heatmaps}, lab/reports.lab_summary) of the forward settled trades
    stored by the cut-off, of the collected companies only (a deleted company's trades are never shown)."""

    def compute() -> dict:
        settled = settled_trades(ctx)
        return {  # no cut-off inside (lab/reports.lab_summary adds one): the envelope carries it
            "basis": BASIS_FORWARD,
            # as_of = the as-of date, as the catalogue's rows (a cut-off would rewrite every page each sync)
            "scoreboard": scoreboard.scoreboard(settled, BASIS_FORWARD, ctx.as_of),
            "comparisons": compare.comparisons(settled, registry.strategies()),
            "heatmaps": heatmaps.heatmap_data(settled, BASIS_FORWARD),
        }

    return ctx.shared("lab_summary", compute)


def settled_trades(ctx: BuildContext) -> list[dict]:
    """The newest settlement of every trade stored by the cut-off (with its your-cost view), collected companies
    only."""

    def compute() -> list[dict]:
        rows = latest_settlements(lab_reads.settlements(ctx.con, ctx.cutoff_time))
        return [row for row in rows if row["ticker"] in ctx.collected]

    return ctx.shared("settled_trades", compute)


def strategies(ctx: BuildContext, fields: tuple[str, ...] = STRATEGY_FIELDS) -> dict[str, dict]:
    """The registry's strategies keyed by id with `fields`: `live` = live_from set and on or before the session
    being predicted; `settled_trades` = its settled accuracy-view trades stored by the cut-off."""

    def compute() -> dict[str, dict]:
        session_date = status_block(ctx)["session"]["session_date"]
        counts: dict[str, int] = {}
        for trade in settled_trades(ctx):
            if trade["view"] == VIEW_ACCURACY and trade["status"] == STATUS_SETTLED:
                counts[trade["strategy_id"]] = counts.get(trade["strategy_id"], 0) + 1
        out = {}
        for spec in registry.strategies():
            live_from = None if spec.get("live_from") is None else str(spec["live_from"])
            out[spec["id"]] = {
                **{key: spec.get(key) for key in STRATEGY_FIELDS if key not in ("live", "settled_trades")},
                "live_from": live_from,
                "live": live_from is not None and live_from <= session_date,
                "settled_trades": counts.get(spec["id"], 0),
            }
        return out

    return {key: {name: entry[name] for name in fields} for key, entry in ctx.shared("strategies", compute).items()}


def go_live(ctx: BuildContext) -> dict:
    """The reference strategy's position against the go-live bar (accuracy view, all horizons, forward basis); with
    no settled trade yet: not proven, 0 months, every trade still needed, baseline comparison unknown."""

    def compute() -> dict:
        for row in lab_summary(ctx)["scoreboard"]:
            if (
                row["scope"] == SCOPE_STRATEGY
                and row["strategy_id"] == REFERENCE_STRATEGY
                and row["view"] == VIEW_ACCURACY
                and row["basis"] == BASIS_FORWARD
                and str(row["horizon_days"]) == ALL_HORIZONS
                and row.get("go_live")
            ):
                return {key: row["go_live"][key] for key in GO_LIVE_FIELDS}
        return {"proven": False, "months_forward": 0.0, "trades_needed": GO_LIVE_TRADES, "beats_best_baseline": None}

    return ctx.shared("go_live", compute)


# The shared derived records (Company, Agreement, Open trade) live in rm_entities.py; re-exported here so every page
# finds every shared block in one place.
from marketbrief.warehouse.rm_entities import agreement, companies, open_trades  # noqa: E402

__all__ = ["agreement", "companies", "open_trades"]
