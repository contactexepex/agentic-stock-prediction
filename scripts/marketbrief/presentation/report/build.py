"""The report skeleton, the Slack draft and the link to the HTML report."""

from __future__ import annotations

from datetime import timedelta
import pandas as pd
from marketbrief.core import calendar
from marketbrief.pipeline.score_predictions import is_late
from marketbrief.analytics.scoring import percent
from view_data import fmt_call
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.utils.markdown import markdown_table
from marketbrief.utils.money import format_money
from marketbrief.constants.report import DISCLAIMER
from marketbrief.presentation.report.formatting import data_stamp, mark, md_link, pct, review_line
from marketbrief.presentation.report.gather import report_url


def build(cfg: dict, day: dict, settings: dict) -> tuple[str, str, str]:
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

    median = [
        f"# Market brief: {cfg['name']}, {session}",
        "",
        DISCLAIMER,
        data_stamp(day),
        "",
        f"Easy-to-read version with charts and filters: [{session}.html]({session}.html)",
        "",
        "## Headline",
        "<!-- AGENT:headline -->",
        "",
        "## Top 3 today",
        "<!-- AGENT:top3 -->",
        "",
        "## Yesterday",
        "<!-- AGENT:yesterday -->",
        "",
        *([market_line, ""] if market_line else []),
        f"### Ranges scored (target date {day['last_target'] or '–'})",
        "",
        (
            f"Next-day ranges: **80% hit {h80}/{one_day_count}** (naive {nh80}/{one_day_count}) · 50% hit "
            f"{h50}/{one_day_count}"
            if one_day_count
            else "No ranges have matured yet."
        ),
        "",
        markdown_table(["Ticker", "80% range", "50% range", "Actual", "80%", "50%", "Naive 80%"], scored_rows),
        line5,
        "",
        "### Calls scored",
        "",
        markdown_table(["Ticker", "H", "Call", "Conf.", "Move", "Hit"], call_rows),
        f"## Today ({session})",
        "",
        regime_line,
        "",
        *([release_line, ""] if release_line else []),
        *img("ranges.png", "Price ranges for every company"),
        markdown_table(
            ["Ticker", "Sector", "Close", "Next day 80%", "Next day 50%", "5 days 80%", "Call", "Cue", "Notes"],
            today_rows,
        ),
        *(
            [
                f"{n_late} stock(s) have ranges made after the first session they cover had opened (a "
                "mid-session or late run): they are shown for the record, are not forecasts and are never "
                "scored.",
                "",
            ]
            if n_late
            else []
        ),
        *day.get("evidence_status", []),
        "<!-- AGENT:calls -->",
        "",
        "### Overnight cues and global factors",
        "",
        markdown_table(["Symbol", "Name", "Last", "Change"], cue_rows),
        *(
            [
                "### ADRs (US-listed shares, previous US session)",
                "",
                markdown_table(["Ticker", "ADR", "Last", "Change"], adr_rows),
            ]
            if adr_rows
            else []
        ),
        "## Tomorrow and this week",
        "",
        markdown_table(
            ["Date", "Event", "Type"],
            [[str(event_day), event_name, event_type] for event_day, event_name, event_type in upcoming],
        ),
        "<!-- AGENT:outlook -->",
        "",
        "## By sector",
        "",
        *img("sectors.png", "Sector moves"),
    ]
    for sector in cfg.get("sectors") or {}:
        median += [f"### {sector}", "", f"<!-- AGENT:sector:{sector} -->", ""]
    median += [
        "## Track record",
        "",
        *img("track_record.png", "Track record: promised vs actual"),
        "Ranges (targets 50% / 80%; width, score and centre error in % of price, lower is better; "
        "naive = last close ± recent typical move, no-change = last close as the centre):",
        "",
        markdown_table(
            [
                "H",
                "Window",
                "n",
                "50% cover",
                "80% cover",
                "Naive 80%",
                "Width",
                "Naive width",
                "Score",
                "Naive score",
                "Centre err",
                "No-change err",
            ],
            sc_rows,
        ),
        "Ranges by regime (since start):",
        "",
        markdown_table(["H", "Regime", "n", "50% cover", "80% cover", "Naive 80%"], regime_rows),
        "Up/down calls vs the always-up baseline:",
        "",
        markdown_table(["H", "Window", "n", "Hit rate", "Always-up"], dir_rows),
        "Calls by confidence band (a band should hit about as often as its confidence):",
        "",
        markdown_table(["Band", "n", "Avg confidence", "Hit rate"], band_rows),
        *(
            [review_line(day["review"], md_link(day["review"]["report"].rsplit("/", 1)[-1])), ""]
            if day.get("review")
            else []
        ),
        "## Data quality",
        "",
        f"- Indicators: {len(feats) - len(partial) - len(blocked)} OK, partial: {', '.join(partial) or 'none'}, "
        f"blocked: {', '.join(blocked) or 'none'}",
        f"- Regime notes: "
        f"{'; '.join(reg['notes']) if reg is not None and reg['notes'] is not None and len(reg['notes']) else 'none'}",
        "",
        markdown_table(["H", "Calibration", "History n", "Live n", "q10 / q90"], cal_rows),
        "<!-- AGENT:data_quality -->",
        "",
    ]
    report = "\n".join(median)

    url = report_url(settings, market, session)
    # calls on late ranges are not forecasts (the HTML and the table label them late)
    calls = [
        (ticker_symbol, item)
        for (ticker_symbol, horizon), item in sorted(range_by_ticker_horizon.items())
        if item.direction in ("up", "down")
        and not is_late(cfg, getattr(item, "as_of_date", None), getattr(item, "made_at", None))
    ]
    # The thread's first message is a short summary (at most 12 lines): regime, the top 3 points,
    # the number of calls (named when there are at most 3), yesterday's score and the report link.
    # Charts and the HTML file follow as replies in the thread (notify_slack.py).
    head = f"*Market brief · {cfg['name']} · {session}*"
    if reg is not None:
        head += f" · market mood: {str(reg['regime']).replace('_', ' ').lower()}"
        if reg["vol_level"] is not None and not pd.isna(reg["vol_level"]):
            head += f" ({vol_name} {reg['vol_level']:.1f})"
    if released:
        head += " · calls made before " + ", ".join(f"{event['name']} ({event['release']})" for event in released)
    by_horizon = lambda item: "next day" if item.horizon_days == 1 else f"{item.horizon_days} days"  # noqa: E731
    if not calls:
        call_line = f"Calls today: none. Price ranges for all {len(cfg['tickers'])} stocks are in the report."
    elif len(calls) <= 3:
        call_line = f"Calls today: {len(calls)} · " + " · ".join(
            f"{ticker_symbol} {fmt_call(item.direction, item.confidence)} ({by_horizon(item)}, 80% range "
            f"{format_money(cur, item.lo80)}–{format_money(cur, item.hi80)})"
            for ticker_symbol, item in calls
        )
    else:
        call_line = (
            f"Calls today: {len(calls)} · "
            + ", ".join(
                f"{ticker_symbol} {fmt_call(item.direction, item.confidence)}" for ticker_symbol, item in calls[:3]
            )
            + f" and {len(calls) - 3} more in the report"
        )
    slack = [
        head,
        "Top 3 today:",
        '<!-- AGENT:top3 (three lines, each starting with "• ": the report\'s Top 3 points, one line each) -->',
        call_line,
        (
            f"Yesterday: next-day 80% ranges hit {h80}/{one_day_count} (naive {nh80}/{one_day_count}) · 50% hit "
            f"{h50}/{one_day_count}" + (f" · calls {calls_hit}/{len(scored_calls)}" if len(scored_calls) else "")
        )
        if one_day_count
        else "Yesterday: no ranges matured yet.",
        "<!-- AGENT:failures (only if a collector failed; otherwise delete this line) -->",
        f"Full report (charts, filters, reasons): {url}",
    ]
    if day.get("review") and day["review"]["fresh"]:  # weekly review written in this run: one line
        slack.insert(
            -1,
            review_line(day["review"], f"{settings['repo_url']}/blob/{settings['branch']}/{day['review']['report']}"),
        )
    return report, "\n".join(slack) + "\n", url
