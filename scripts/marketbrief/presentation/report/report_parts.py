"""The values a day's report skeleton and Slack draft are both built from."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import pandas as pd
from marketbrief.core import calendar
from marketbrief.pipeline.score_predictions import is_late
from marketbrief.analytics.scoring import percent
from view_data import fmt_call
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.utils.money import format_money
from marketbrief.presentation.report.formatting import mark, pct


@dataclass
class ReportParts:
    """The values the report skeleton and the Slack draft are both built from."""

    adr_rows: object
    band_rows: object
    blocked: object
    cal_rows: object
    call_rows: object
    calls_hit: object
    cue_rows: object
    cur: object
    dir_rows: object
    feats: object
    h50: object
    h80: object
    img: object
    line5: object
    market: object
    market_line: object
    n_late: object
    nh80: object
    one_day_count: object
    partial: object
    range_by_ticker_horizon: object
    reg: object
    regime_line: object
    regime_rows: object
    release_line: object
    released: object
    sc_rows: object
    scored_calls: object
    scored_rows: object
    session: object
    today_rows: object
    upcoming: object
    vol_name: object


def report_basics(cfg, day):
    """The market labels, the regime line, the chart helper and the stored ranges and features of the day."""
    cur, market, session = cfg.get("currency", ""), cfg["market"], day["session"]
    charts = f"charts/{session}"
    have = day.get("charts") or set()  # single-purpose PNGs charts.py wrote (file names)
    img = lambda frame, alt: [f"![{alt}]({charts}/{frame})", ""] if frame in have else []  # noqa: E731
    reg = day["regime"].iloc[0] if not day["regime"].empty else None
    vol_name = cfg["symbols"].get(vol_index_key(cfg) or "", {}).get("name", "vol index")
    regime_line = "Regime: unknown"
    if reg is not None:
        parts = [f"**Regime: {reg['regime']}**" + (" · STRESS" if reg["stress"] else "")]
        if reg["vol_level"] is not None and not pd.isna(reg["vol_level"]):
            parts.append(f"{vol_name} {reg['vol_level']:.2f} ({pct(reg['vol_change_1d'])})")
        parts.append(f"benchmark 5d {pct(reg['bench_ret_5d'])}")
        if reg["bench_vol_10d"] is not None and not pd.isna(reg["bench_vol_10d"]):
            parts.append(f"benchmark 10d vol {reg['bench_vol_10d'] * 100:.1f}%")
        if reg["major_event"]:
            parts.append(f"major events: {', '.join(reg['major_event_names'])}")
        regime_line = " · ".join(parts)
    ranges = day["ranges"]
    range_by_ticker_horizon = {(row.ticker, int(row.horizon_days)): row for row in ranges.itertuples()}
    feats = day["features"].set_index("ticker") if not day["features"].empty else pd.DataFrame()

    return cur, feats, img, market, range_by_ticker_horizon, reg, regime_line, session, vol_name


def yesterday_tables(cfg, cur, day, feats):
    """Yesterday: the market line, the ranges scored on the latest target date and the calls scored."""
    # yesterday: the market and the watchlist on the latest bar, then ranges scored on the latest target date
    names = {symbol: value.get("name", symbol) for symbol, value in cfg["symbols"].items()}
    market_by_ticker = {item.ticker: item for item in day["market"].itertuples()} if "market" in day else {}
    market_parts = []
    for key in (benchmark_key(cfg), vol_index_key(cfg)):
        if key in market_by_ticker:
            market_parts.append(
                f"{names.get(key, key)} {market_by_ticker[key].close:,.2f} ({pct(market_by_ticker[key].ret_1d)})"
            )
    moves = feats["ret_1d"].dropna().sort_values() if len(feats) and "ret_1d" in feats else pd.Series(dtype=float)
    if len(moves):
        market_parts.append(f"watchlist {int((moves > 0).sum())} up / {int((moves < 0).sum())} down")
        market_parts.append(
            f"best {moves.index[-1]} {pct(moves.iloc[-1])}, worst {moves.index[0]} {pct(moves.iloc[0])}"
        )
    market_line = f"Market on {day['as_of']}: " + " · ".join(market_parts) if market_parts else ""
    scored = day["scored"]
    scored_one_day = scored[scored["horizon_days"] == 1] if not scored.empty else scored
    one_day_count = len(scored_one_day)
    h80, h50 = (int(scored_one_day["hit80"].sum()), int(scored_one_day["hit50"].sum())) if one_day_count else (0, 0)
    nh80 = int(scored_one_day["naive_hit80"].fillna(False).sum()) if one_day_count else 0
    scored_rows = [
        [
            item.ticker,
            f"{format_money(cur, item.lo80)}–{format_money(cur, item.hi80)}",
            f"{format_money(cur, item.lo50)}–{format_money(cur, item.hi50)}",
            format_money(cur, item.actual_close),
            mark(item.hit80),
            mark(item.hit50),
            mark(item.naive_hit80),
        ]
        for item in scored_one_day.itertuples()
    ]
    scored_five_day = scored[scored["horizon_days"] == 5] if not scored.empty else scored
    line5 = (
        f"5-day ranges that matured on the same date: 80% hit "
        f"{int(scored_five_day['hit80'].sum())}/{len(scored_five_day)}, "
        f"50% hit {int(scored_five_day['hit50'].sum())}/{len(scored_five_day)}."
        if len(scored_five_day)
        else ""
    )
    scored_calls = day["calls_scored"]
    calls_hit = int(scored_calls["hit"].sum()) if not scored_calls.empty else 0
    call_rows = [
        [
            item.ticker,
            f"{item.horizon_days}d",
            item.direction,
            percent(item.confidence),
            pct(item.actual_return, 2),
            mark(item.hit),
        ]
        for item in scored_calls.itertuples()
    ]

    return call_rows, calls_hit, h50, h80, line5, market_line, nh80, one_day_count, scored_calls, scored_rows


def today_rows_by_sector(cfg, cur, feats, range_by_ticker_horizon):
    """Today's ranges and calls by sector, and the number of late (never scored) stocks."""
    # today: ranges by sector
    today_rows, n_late = [], 0
    for sector, members in (cfg.get("sectors") or {"": list(cfg["tickers"])}).items():
        for ticker_symbol in members:
            one_day_range, five_day_range = (
                range_by_ticker_horizon.get((ticker_symbol, 1)),
                range_by_ticker_horizon.get((ticker_symbol, 5)),
            )
            if one_day_range is None and five_day_range is None:
                quality = feats.loc[ticker_symbol]["quality"] if ticker_symbol in feats.index else "no data"
                today_rows.append([ticker_symbol, sector, "–", "–", "–", "–", f"no range ({quality})", "", ""])
                continue
            base = (one_day_range or five_day_range).base_close
            made = [
                (horizon, item)
                for horizon, item in ((1, one_day_range), (5, five_day_range))
                if item is not None and item.direction in ("up", "down")
            ]
            call = (
                " · ".join(f"{horizon}d {fmt_call(item.direction, item.confidence)}" for horizon, item in made)
                or "no call"
            )
            # made at/after the first target session's open: shown for the record, never scored
            late = any(
                is_late(cfg, getattr(item, "as_of_date", None), getattr(item, "made_at", None))
                for item in (one_day_range, five_day_range)
                if item is not None
            )
            n_late += late
            if late:
                call = "late: not a forecast, never scored"
            notes = "; ".join(
                sorted(
                    {
                        note
                        for item in (one_day_range, five_day_range)
                        if item is not None
                        for note in (list(item.notes) if item.notes is not None else [])
                    }
                )
            )
            today_rows.append(
                [
                    ticker_symbol,
                    sector,
                    format_money(cur, base),
                    f"{format_money(cur, one_day_range.lo80)}–{format_money(cur, one_day_range.hi80)}"
                    if one_day_range
                    else "–",
                    f"{format_money(cur, one_day_range.lo50)}–{format_money(cur, one_day_range.hi50)}"
                    if one_day_range
                    else "–",
                    f"{format_money(cur, five_day_range.lo80)}–{format_money(cur, five_day_range.hi80)}"
                    if five_day_range
                    else "–",
                    call,
                    "–"
                    if late
                    else pct(feats.loc[ticker_symbol]["cue_change_pct"], 2)
                    if ticker_symbol in feats.index
                    else "–",
                    notes,
                ]
            )

    return n_late, today_rows


def cue_tables(cfg, day):
    """Overnight cues and global factors, and the ADR rows."""
    cue_rows = [
        [
            item.symbol,
            cfg["symbols"].get(item.symbol, {}).get("name", item.symbol),
            f"{item.price:,.2f}",
            pct(item.change_pct, 2),
        ]
        for item in day["quotes"].itertuples()
        if item.symbol in cfg["symbols"]
    ]
    adr_rows = [
        [
            item.symbol.replace(":ADR", ""),
            cfg["tickers"].get(item.symbol.replace(":ADR", ""), {}).get("adr", ""),
            f"{item.price:,.2f}",
            pct(item.change_pct, 2),
        ]
        for item in day["quotes"].itertuples()
        if item.symbol.endswith(":ADR")
    ]

    return adr_rows, cue_rows


def calendar_lines(cfg, day, session):
    """Upcoming market and company events, and the data released before the open."""
    mevents = calendar.market_events(cfg, day["as_of"] + timedelta(days=1), day["as_of"] + timedelta(days=21))
    upcoming = [(event["date"], event["name"], "major" if event["major"] else "") for event in mevents]
    # data published before the open on the session day (US CPI, jobs at 08:30 ET)
    released = [event for event in mevents if event["date"] == session and event.get("release")]
    release_line = (
        "Calls made before release: " + ", ".join(f"{event['name']} at {event['release']}" for event in released) + "."
        if released
        else ""
    )
    upcoming += [(pd.Timestamp(item.date).date(), item.name, "company") for item in day["company_events"].itertuples()]
    upcoming.sort()

    return release_line, released, upcoming


def track_record_rows(day, feats):
    """Track-record tables (scorecard, regimes, direction, bands, calibration) and data-quality lists."""
    share = lambda value: "–" if value is None or pd.isna(value) else percent(value)  # noqa: E731
    num = lambda value, frame=".2f": "–" if value is None or pd.isna(value) else format(value, frame)  # noqa: E731
    sc_rows = [
        [
            f"{item.h}d",
            item.win,
            item.n,
            share(item.c50),
            share(item.c80),
            share(item.nc80),
            num(item.w),
            num(item.nw),
            num(item.s, ".3f"),
            num(item.ns, ".3f"),
            num(item.ce),
            num(item.nce),
        ]
        for item in day["scorecard"].itertuples()
    ]
    regime_rows = [
        [f"{item.h}d", item.regime, item.n, share(item.c50), share(item.c80), share(item.nc80)]
        for item in day["by_regime"].itertuples()
    ]
    dir_rows = [
        [f"{item.h}d", item.win, item.n, share(item.hit), share(item.up)] for item in day["direction"].itertuples()
    ]
    band_rows = [[item.band, item.n, share(item.conf), share(item.hit)] for item in day["conf_bands"].itertuples()]
    cal_rows = [
        [f"{item.horizon_days}d", item.source, item.n_history, item.n_live, f"{item.q10:.2f} / {item.q90:.2f}"]
        for item in day["calibration"].itertuples()
    ]
    partial = sorted(feats.index[feats["quality"] == "PARTIAL"]) if len(feats) else []
    blocked = sorted(feats.index[feats["quality"] == "BLOCKED"]) if len(feats) else []

    return band_rows, blocked, cal_rows, dir_rows, partial, regime_rows, sc_rows


def prepare_parts(cfg: dict, day: dict) -> ReportParts:
    """Compute the tables, lines and counts of one report from the gathered day data."""
    cur, feats, img, market, range_by_ticker_horizon, reg, regime_line, session, vol_name = report_basics(cfg, day)
    (call_rows, calls_hit, h50, h80, line5, market_line, nh80, one_day_count, scored_calls, scored_rows) = (
        yesterday_tables(cfg, cur, day, feats)
    )
    n_late, today_rows = today_rows_by_sector(cfg, cur, feats, range_by_ticker_horizon)
    adr_rows, cue_rows = cue_tables(cfg, day)
    release_line, released, upcoming = calendar_lines(cfg, day, session)
    band_rows, blocked, cal_rows, dir_rows, partial, regime_rows, sc_rows = track_record_rows(day, feats)
    return ReportParts(
        adr_rows=adr_rows,
        band_rows=band_rows,
        blocked=blocked,
        cal_rows=cal_rows,
        call_rows=call_rows,
        calls_hit=calls_hit,
        cue_rows=cue_rows,
        cur=cur,
        dir_rows=dir_rows,
        feats=feats,
        h50=h50,
        h80=h80,
        img=img,
        line5=line5,
        market=market,
        market_line=market_line,
        n_late=n_late,
        nh80=nh80,
        one_day_count=one_day_count,
        partial=partial,
        range_by_ticker_horizon=range_by_ticker_horizon,
        reg=reg,
        regime_line=regime_line,
        regime_rows=regime_rows,
        release_line=release_line,
        released=released,
        sc_rows=sc_rows,
        scored_calls=scored_calls,
        scored_rows=scored_rows,
        session=session,
        today_rows=today_rows,
        upcoming=upcoming,
        vol_name=vol_name,
    )
