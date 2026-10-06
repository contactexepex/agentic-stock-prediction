"""The rule replay's SVG charts: calibration, coverage by regime and coverage over time."""

from __future__ import annotations

import math
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.constants.replay import MIN_MONTH_DAYS
from marketbrief.replay.html_parts import esc, scaled_text


def svg_calibration(summary: dict) -> str:
    width, height, left, right, top, bottom = 640, 360, 48, 16, 16, 40
    plot_width, plot_height = width - left - right, height - top - bottom
    scale_x = lambda tick: left + tick * plot_width  # noqa: E731
    scale_y = lambda tick: top + (1 - tick) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Stated vs actual coverage">']
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1):
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(tick):.1f}" y2="{scale_y(tick):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(tick) + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
        out.append(
            f'<text x="{scale_x(tick):.1f}" y="{height - bottom + 16}" text-anchor="middle">{int(tick * 100)}%</text>'
        )
    out.append(
        f'<text x="{left + plot_width / 2}" y="{height - 4}" text-anchor="middle">stated coverage (what the range '
        f"promises)</text>"
    )
    out.append(
        f'<line x1="{scale_x(0)}" y1="{scale_y(0)}" x2="{scale_x(1)}" y2="{scale_y(1)}" stroke="var(--muted)" '
        f'stroke-dasharray="4 4"/>'
    )
    for horizon, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        pts = summary["horizons"].get(horizon, {}).get("calibration") or []
        if not pts:
            continue
        path = " ".join(
            f"{'M' if index == 0 else 'L'}{scale_x(point['stated']):.1f},{scale_y(point['actual']):.1f}"
            for index, point in enumerate(pts)
        )
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for point in pts:
            radius = 6 if point["published"] else 4
            tipx = (
                f"{horizon}-day {'published ' if point['published'] else ''}{int(point['stated'] * 100)}% "
                f"range: "
                f"actual {scaled_text(point['actual'])}"
            )
            out.append(
                f'<circle class="mark" cx="{scale_x(point["stated"]):.1f}" '
                f'cy="{scale_y(point["actual"]):.1f}" r="{radius}" fill="{color}" '
                f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>'
            )
    out.append("</svg>")
    return "".join(out)


def svg_regime(summary: dict) -> str:
    regs = REGIME_ORDER
    width, height, left, right, top, bottom = 640, 300, 48, 16, 16, 44
    plot_width, plot_height = width - left - right, height - top - bottom
    scale_y = lambda tick: top + (1 - tick) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="80% coverage by regime">']
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1):
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(tick):.1f}" y2="{scale_y(tick):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(tick) + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
    slot = plot_width / len(regs)
    bar_width = min(24, slot / 3)
    for index, name in enumerate(regs):
        center_x = left + slot * (index + 0.5)
        days = summary.get("regime_days", {}).get(name, 0)
        out.append(f'<text x="{center_x:.1f}" y="{height - bottom + 16}" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{center_x:.1f}" y="{height - bottom + 30}" text-anchor="middle">{days} days</text>')
        for inner_index, (horizon, color) in enumerate((("1", "var(--s1)"), ("5", "var(--s2)"))):
            regime_stats = summary["horizons"].get(horizon, {}).get("by_regime", {}).get(name)
            if not regime_stats or not regime_stats.get("n"):
                continue
            tick = regime_stats["cover80"]
            bar_left = center_x + (inner_index - 1) * (bar_width + 2) + 1
            bottom_y, top_y = scale_y(0), scale_y(tick)
            bar_height = max(bottom_y - top_y, 0.5)
            corner_radius = min(4, bar_height)
            bar_path = (
                f"M{bar_left:.1f},{bottom_y:.1f} L{bar_left:.1f},{top_y + corner_radius:.1f} "
                f"Q{bar_left:.1f},{top_y:.1f} "
                f"{bar_left + corner_radius:.1f},{top_y:.1f} "
                f"L{bar_left + bar_width - corner_radius:.1f},{top_y:.1f} Q{bar_left + bar_width:.1f},{top_y:.1f} "
                f"{bar_left + bar_width:.1f},{top_y + corner_radius:.1f} L{bar_left + bar_width:.1f},{bottom_y:.1f} Z"
            )
            tipx = (f"{name}, {horizon}-day: 80% coverage {scaled_text(tick)} over {regime_stats['n']:,} ranges "
                    f"({regime_stats['days']} days)")
            out.append(f'<path class="mark" d="{bar_path}" fill="{color}" data-tip="{esc(tipx)}"/>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0.8):.1f}" y2="{scale_y(0.8):.1f}" '
        f'stroke="var(--ink2)" stroke-dasharray="4 4"/>'
    )
    out.append(f'<text x="{left + 4}" y="{scale_y(0.8) - 5:.1f}" text-anchor="start">promise 80%</text>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0):.1f}" y2="{scale_y(0):.1f}" stroke="var(--axis)"/>'
    )
    out.append("</svg>")
    return "".join(out)


def svg_time(summary: dict) -> str:
    months = sorted(
        {
            month
            for horizon in ("1", "5")
            for month, value in summary["horizons"].get(horizon, {}).get("by_month", {}).items()
            if value.get("days", 0) >= MIN_MONTH_DAYS
        }
    )
    if not months:
        return ""
    width, height, left, right, top, bottom = 640, 300, 48, 30, 16, 36
    plot_width, plot_height = width - left - right, height - top - bottom
    vals = [
        value["cover80"]
        for horizon in ("1", "5")
        for value in summary["horizons"].get(horizon, {}).get("by_month", {}).values()
        if value.get("days", 0) >= MIN_MONTH_DAYS
    ]
    lower = max(0.0, math.floor(min(vals + [0.6]) * 10) / 10)
    scale_x = lambda index: left + (index + 0.5) * plot_width / len(months)  # noqa: E731
    scale_y = lambda value: top + (1 - (value - lower) / (1 - lower)) * plot_height  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="80% coverage by month">']
    value = lower
    while value <= 1.0001:
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{scale_y(value):.1f}" y2="{scale_y(value):.1f}" '
            f'stroke="var(--grid)"/>'
        )
        out.append(f'<text x="{left - 6}" y="{scale_y(value) + 4:.1f}" text-anchor="end">{round(value * 100)}%</text>')
        value += 0.1
    step = max(1, len(months) // 8)
    for index, month in enumerate(months):
        if index % step == 0:
            out.append(f'<text x="{scale_x(index):.1f}" y="{height - bottom + 16}" text-anchor="middle">{month}</text>')
    out.append(
        f'<line x1="{left}" x2="{width - right}" y1="{scale_y(0.8):.1f}" y2="{scale_y(0.8):.1f}" '
        f'stroke="var(--ink2)" stroke-dasharray="4 4"/>'
    )
    for horizon, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        by_month = summary["horizons"].get(horizon, {}).get("by_month", {})
        pts = [
            (index, by_month[month])
            for index, month in enumerate(months)
            if by_month.get(month, {}).get("days", 0) >= MIN_MONTH_DAYS
        ]
        if not pts:
            continue
        path = " ".join(
            f"{'M' if point_index == 0 else 'L'}{scale_x(index):.1f},{scale_y(stats['cover80']):.1f}"
            for point_index, (index, stats) in enumerate(pts)
        )
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for index, stats in pts:
            tipx = (
                f"{months[index]}, {horizon}-day: 80% coverage {scaled_text(stats['cover80'])} ({stats['n']:,} ranges)"
            )
            out.append(
                f'<circle class="mark" cx="{scale_x(index):.1f}" cy="{scale_y(stats["cover80"]):.1f}" r="4" '
                f'fill="{color}" '
                f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>'
            )
    out.append("</svg>")
    return "".join(out)
