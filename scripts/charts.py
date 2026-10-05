#!/usr/bin/env python3
"""Draw the day's single-purpose chart images (PNG) for the report and the Slack thread.

Each image answers one question, sized to read on a phone:
- ranges.png: where each company's price may be at one horizon (80% and 50% range, % from the
  last close, one scale for all companies); late ranges in grey, labelled "late".
- sectors.png: how each sector moved on the latest trading day (average one-day change).
- track_record.png: promised vs actual hit rate (ranges and calls); only once something was scored.
The numbers come from view_data.py, the same view the HTML report embeds. Writes
reports/<market>/charts/<session_date>/<name>.png (small, palette-quantized PNGs). The old
per-ticker charts and the overview collage are no longer drawn: the HTML report shows a price
chart per company."""
from __future__ import annotations

import io
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from PIL import Image  # noqa: E402

from common import ROOT, connect, market_arg, require_market  # noqa: E402
from view_data import CURRENCY, gather_view, primary_horizon  # noqa: E402

# Reference palette (dataviz skill): light surface, blue ramp for ranges, blue/red diverging
# pair for up/down moves, neutral grey for late ranges; text always in ink tokens.
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#6f6d68", "#e1e0d9", "#c3c2b7"
BAND80, BAND50, CENTER = "#cde2fb", "#86b6ef", "#1c5cab"
UP, DOWN, CALLS = "#2a78d6", "#e34948", "#eb6834"
LATE80, LATE50 = "#e6e5e1", "#c3c2b7"
DPI = 150

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": INK, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
})


def save_png(fig, path) -> None:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    Image.open(buf).convert("RGB").quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


def _title(fig, title: str, sub: str) -> None:
    fig.text(0.03, 0.975, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.03, 0.975 - 0.34 / fig.get_figheight(), sub, fontsize=9.5, color=INK2, va="top")


def ranges_chart(view: dict, path) -> bool:
    h = primary_horizon(view)
    rows = [(c, r) for c in view["companies"] for r in c["ranges"] if r["h"] == h and c["close"]]
    if not rows:
        return False
    sym = CURRENCY.get(view["currency"], "")
    pct = lambda c, v: (v / c["close"] - 1) * 100  # noqa: E731
    height = 1.3 + 0.32 * len(rows)
    fig, ax = plt.subplots(figsize=(7.2, height))
    fig.subplots_adjust(left=0.16, right=0.70, top=1 - 0.95 / height, bottom=0.55 / height)
    target = rows[0][1]["target_label"]
    when = "after the next trading day" if h == 1 else f"in {h} trading days"
    _title(fig, f"Where each price may be {when} (by {target})",
           "Light bar: 80% range · dark: 50% range · dot: centre · % from the last close")
    for i, (c, r) in enumerate(rows):
        y = len(rows) - 1 - i
        late = r["late"]
        ax.barh(y, pct(c, r["hi80"]) - pct(c, r["lo80"]), left=pct(c, r["lo80"]), height=0.5,
                color=LATE80 if late else BAND80, linewidth=0)
        ax.barh(y, pct(c, r["hi50"]) - pct(c, r["lo50"]), left=pct(c, r["lo50"]), height=0.5,
                color=LATE50 if late else BAND50, linewidth=0)
        ax.plot(pct(c, r["center_price"]), y, "o", ms=5, color=MUTED if late else CENTER, mec=SURFACE, mew=1.5)
        dp = 0 if r["hi80"] >= 100 else 2
        label = f"{sym}{r['lo80']:,.{dp}f}–{r['hi80']:,.{dp}f}"
        if late:
            label += "  late, not a forecast"
        elif r["direction"]:
            label += f"  {'▲ up' if r['direction'] == 'up' else '▼ down'} {r['confidence']:.0%}"
        ax.text(1.02, y, label, transform=ax.get_yaxis_transform(), va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(len(rows)), [c["ticker"] for c, _ in reversed(rows)], fontsize=9.5)
    ax.tick_params(axis="y", length=0)
    ax.axvline(0, color=AXIS, linewidth=1, zorder=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    m = max(max(abs(pct(c, r["lo80"])), abs(pct(c, r["hi80"]))) for c, r in rows)
    ax.set_xlim(-m * 1.08, m * 1.08)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%" if v else "0%"))
    save_png(fig, path)
    return True


def sectors_chart(view: dict, path) -> bool:
    rows = sorted([s for s in view["sectors"] if s["move_1d"] is not None], key=lambda s: s["move_1d"])
    if not rows:
        return False
    height = 1.2 + 0.36 * len(rows)
    fig, ax = plt.subplots(figsize=(7.2, height))
    fig.subplots_adjust(left=0.22, right=0.86, top=1 - 0.95 / height, bottom=0.5 / height)
    _title(fig, f"How each sector moved on {view['as_of_label']}",
           "Average one-day price change of the sector's companies (blue up, red down)")
    vals = [s["move_1d"] * 100 for s in rows]
    ax.barh(range(len(rows)), vals, height=0.6, color=[UP if v >= 0 else DOWN for v in vals], linewidth=0)
    for i, v in enumerate(vals):
        ax.text(1.02, i, f"{v:+.1f}%", transform=ax.get_yaxis_transform(), va="center", fontsize=9.5, color=INK2)
    ax.set_yticks(range(len(rows)), [s["sector"] for s in rows])
    ax.tick_params(axis="y", length=0)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    m = max(abs(v) for v in vals) or 1
    ax.set_xlim(-m * 1.1, m * 1.1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%" if v else "0%"))
    save_png(fig, path)
    return True


def track_record_chart(view: dict, path) -> bool:
    pts = [p for p in view["calibration"] if p["actual"] is not None and p["n"] > 0]
    if not pts:
        return False
    fig, ax = plt.subplots(figsize=(6.0, 6.2))
    fig.subplots_adjust(left=0.14, right=0.95, top=0.84, bottom=0.17)
    small = all(p["n"] < view["min_sample"] for p in pts)
    _title(fig, "Track record: promised vs actual",
           "On the diagonal = right as often as promised" + (f"\nNot enough history yet (under {view['min_sample']} cases per mark)" if small else ""))
    ax.plot([0, 100], [0, 100], color=AXIS, linewidth=1, zorder=1)
    for p in pts:
        kw = dict(marker="o", color=UP) if p["kind"] == "range" else dict(marker="s", color=CALLS)
        ax.plot(p["stated"] * 100, p["actual"] * 100, linestyle="", ms=9, mec=SURFACE, mew=1.5, zorder=3, **kw)
        ax.annotate(f"n={p['n']}", (p["stated"] * 100, p["actual"] * 100), xytext=(7, -3),
                    textcoords="offset points", fontsize=8, color=INK2)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("promised (stated chance or confidence)")
    ax.set_ylabel("actual hit rate")
    ax.spines["left"].set_visible(True)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.legend(handles=[Line2D([], [], marker="o", color=UP, linestyle="", label="Price ranges (50% and 80%)"),
                       Line2D([], [], marker="s", color=CALLS, linestyle="", label="Up/down calls by confidence")],
              loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=1, frameon=False, fontsize=9, labelcolor=INK2)
    save_png(fig, path)
    return True


CHARTS = (("ranges.png", ranges_chart), ("sectors.png", sectors_chart), ("track_record.png", track_record_chart))


def run(cfg: dict, view: dict | None = None) -> dict:
    view = view or gather_view(cfg, connect(cfg["market"]))
    out = ROOT / "reports" / cfg["market"] / "charts" / view["session"]
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for name, draw in CHARTS:
        if draw(view, out / name):
            files.append(str((out / name).relative_to(ROOT)))
    return {"step": "charts", "market": cfg["market"], "session_date": view["session"], "charts": files}


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps(run(cfg), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
