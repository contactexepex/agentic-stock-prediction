"""The Slack summary draft and the link to the HTML report."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics.call_basis import label as basis_label
from marketbrief.analytics.scoring import basis_key
from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.constants.report import MSG_RANGES_LATE
from marketbrief.pipeline.score_predictions import is_late
from marketbrief.presentation.report.formatting import review_line
from marketbrief.presentation.report.gather import report_url
from marketbrief.presentation.report.report_parts import ReportParts
from marketbrief.utils.money import format_money
from view_data import fmt_call


def calls_by_basis(scored_calls: pd.DataFrame) -> str:
    """Scored calls per scoring basis key, never pooled: '2/3 close→close, 1/1 open→close' (old D+4 open-to-close
    calls, horizon_label legacy_5d_d4, apart: scoring.basis_key)."""
    labels = scored_calls["horizon_label"] if "horizon_label" in scored_calls else [None] * len(scored_calls)
    keys = [basis_key(basis, label) for basis, label in zip(scored_calls["label_basis"], labels, strict=True)]
    return ", ".join(f"{int(group['hit'].sum())}/{len(group)} {basis_label(key)}"
                     for key, group in scored_calls.groupby(pd.Series(keys, index=scored_calls.index), sort=True))


def call_horizon(item) -> str:
    """A call's horizon in the Slack line: 'N+k' for an N+k range, the old 'next day' / '<h> days' otherwise."""
    if getattr(item, "horizon_label", None) == LABEL_N_PLUS_K:
        return f"N+{item.horizon_days}"
    return "next day" if item.horizon_days == 1 else f"{item.horizon_days} days"


def render_slack(cfg: dict, day: dict, settings: dict, parts: ReportParts) -> tuple[str, str]:
    """The Slack summary draft and the link to the HTML report."""
    session, market = parts.session, parts.market
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
    if not calls:  # issue #21: the line says when the ranges are late (made after the first session's open)
        call_line = f"Calls today: none. Price ranges for all {len(cfg['tickers'])} stocks are in the report" + (
            MSG_RANGES_LATE if parts.n_late else "."
        )
    elif len(calls) <= 3:
        call_line = f"Calls today: {len(calls)} · " + " · ".join(
            f"{ticker_symbol} {fmt_call(item.direction, item.confidence)} ({call_horizon(item)}, 80% range "
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
            f"Yesterday: {parts.one_day_name} 80% ranges hit {h80}/{one_day_count} (naive {nh80}/{one_day_count})"
            f" · 50% hit {h50}/{one_day_count}"
            + (f" · calls {calls_by_basis(scored_calls)}" if len(scored_calls) else "")
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
