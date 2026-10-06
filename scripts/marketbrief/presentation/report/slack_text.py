"""The Slack summary draft and the link to the HTML report."""

from __future__ import annotations

from marketbrief.presentation.report.report_parts import ReportParts
import pandas as pd
from marketbrief.pipeline.score_predictions import is_late
from view_data import fmt_call
from marketbrief.utils.money import format_money
from marketbrief.presentation.report.formatting import review_line
from marketbrief.presentation.report.gather import report_url


def render_slack(cfg: dict, day: dict, settings: dict, parts: ReportParts) -> tuple[str, str]:
    """The Slack summary draft and the link to the HTML report."""
    session, market = parts.session, parts.market
    calls_hit = parts.calls_hit
    cur = parts.cur
    h50 = parts.h50
    h80 = parts.h80
    nh80 = parts.nh80
    one_day_count = parts.one_day_count
    range_by_ticker_horizon = parts.range_by_ticker_horizon
    reg = parts.reg
    released = parts.released
    scored_calls = parts.scored_calls
    vol_name = parts.vol_name
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
    return "\n".join(slack) + "\n", url
