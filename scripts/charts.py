#!/usr/bin/env python3
"""Draw one chart per ticker plus an overview grid for the latest published ranges.

Per ticker: last 60 trading days of closes; past 1-day 80% ranges against the actual close
(hit = filled circle, miss = cross); today's 1-day and 5-day ranges as a cone (80% light,
50% darker) with the call and confidence. The x axis counts trading days, so weekends and
holidays leave no gaps. Writes reports/<market>/charts/<session_date>/<ticker>.png and
overview.png (small, palette-quantized PNGs to keep the repo light)."""
from __future__ import annotations

import io
import json
import math
import re
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from PIL import Image  # noqa: E402

from common import ROOT, connect, market_arg, require_market  # noqa: E402
from features import load_bars  # noqa: E402

# Reference palette (dataviz skill): light surface, one sequential hue, reserved status colors.
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
LINE = "#2a78d6"                       # close price (categorical slot 1)
BAND80, BAND50, CENTER = "#cde2fb", "#86b6ef", "#1c5cab"   # blue ramp 100 / 250 / 550
PAST = "#b4b3ad"                       # past ranges: neutral
GOOD, CRITICAL = "#0ca30c", "#d03b3b"  # status: hit / miss (always paired with a marker shape)
WINDOW = 60
CURRENCY = {"INR": "₹", "USD": "$"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.spines.top": False, "axes.spines.right": False,
})


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name)


def save_png(fig, path) -> None:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    Image.open(buf).convert("RGB").quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


def money(cur: str, v: float) -> str:
    return f"{CURRENCY.get(cur, '')}{v:,.2f}"


def fmt_call(direction, confidence) -> str:
    if direction not in ("up", "down") or confidence is None or pd.isna(confidence):
        return "no call"
    return f"{'▲ up' if direction == 'up' else '▼ down'} {confidence:.0%}"


def load(con, market: str):
    ranges = con.execute("SELECT * FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)").df()
    if ranges.empty:
        raise SystemExit("no published ranges; run ranges.py first")
    past = con.execute("SELECT ticker, target_date, lo80, hi80, actual_close, hit80 FROM range_record "
                       "WHERE horizon_days = 1").df()
    # label with the regime the ranges were built under (a later features.py run may have moved on)
    regime = ranges["regime"].dropna()
    return ranges, past, (str(regime.iloc[0]) if len(regime) else "?")


def ticker_chart(cfg, t, closes, today, past, regime, path) -> None:
    meta, cur = cfg["tickers"][t], cfg.get("currency", "")
    s = closes.iloc[-WINDOW:]
    pos = {d.date(): i for i, d in enumerate(s.index)}
    last = len(s) - 1
    r1 = today[today["horizon_days"] == 1].iloc[0] if (today["horizon_days"] == 1).any() else None
    r5 = today[today["horizon_days"] == 5].iloc[0] if (today["horizon_days"] == 5).any() else None
    fig, ax = plt.subplots(figsize=(8, 3.9))
    fig.subplots_adjust(left=0.08, right=0.97, top=0.82, bottom=0.25)

    # today's cone (80% then 50%), anchored at the last close
    pts = [(last, None)] + [(last + h, r) for h, r in ((1, r1), (5, r5)) if r is not None]
    if len(pts) > 1:
        base = float(s.iloc[-1])
        xs = [p[0] for p in pts]
        for lo, hi, color in (("lo80", "hi80", BAND80), ("lo50", "hi50", BAND50)):
            ax.fill_between(xs, [base] + [p[1][lo] for p in pts[1:]], [base] + [p[1][hi] for p in pts[1:]],
                            color=color, linewidth=0, zorder=1)
        ax.plot(xs, [base] + [p[1]["base_close"] * math.exp(p[1]["center"]) for p in pts[1:]],
                color=CENTER, linewidth=1, linestyle=(0, (3, 2)), zorder=2)
        x, r = pts[-1]  # selective direct labels: the 80% bounds at the far end of the cone
        for key, va in (("hi80", "bottom"), ("lo80", "top")):
            ax.annotate(money(cur, r[key]), (x, r[key]), xytext=(4, 0), textcoords="offset points",
                        fontsize=7, color=INK2, va="center")

    # past 1-day 80% ranges vs the actual close
    p = past[past["ticker"] == t]
    hits = misses = 0
    for row in p.itertuples():
        x = pos.get(pd.Timestamp(row.target_date).date())
        if x is None:
            continue
        ax.vlines(x, row.lo80, row.hi80, color=PAST, linewidth=2, zorder=2)
        if row.hit80:
            hits += 1
            ax.plot(x, row.actual_close, "o", ms=4, color=GOOD, mec=SURFACE, mew=1, zorder=4)
        else:
            misses += 1
            ax.plot(x, row.actual_close, "x", ms=6, mew=2, color=CRITICAL, zorder=4)

    ax.plot(range(len(s)), s.values, color=LINE, linewidth=2, zorder=3)
    ticks = list(range(0, len(s), 15)) + [last]
    labels = [s.index[i].strftime("%d %b") for i in ticks]
    if r5 is not None:
        ticks.append(last + 5)
        labels.append(pd.Timestamp(r5["target_date"]).strftime("%d %b"))
    ax.set_xticks(ticks, labels)
    ax.set_xlim(-1, last + 11)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    made = [(h, r) for h, r in ((1, r1), (5, r5)) if r is not None and r["direction"] in ("up", "down")]
    call = ", ".join(f"{h}d {fmt_call(r['direction'], r['confidence'])}" for h, r in made) or "no call"
    fig.text(0.08, 0.93, f"{t} · {meta['name']}", fontsize=11, fontweight="bold", color=INK)
    sub = f"Close {money(cur, float(s.iloc[-1]))} · {meta.get('sector') or ''} · regime {regime} · call: {call}"
    if r1 is not None:
        sub += f" · next day 80%: {money(cur, r1['lo80'])}–{money(cur, r1['hi80'])}"
    fig.text(0.08, 0.86, sub, fontsize=8, color=INK2)
    scored = hits + misses
    fig.text(0.08, 0.03, f"Past next-day 80% ranges shown: {hits}/{scored} hit" if scored else
             "No scored ranges yet", fontsize=7, color=MUTED)
    ax.legend(handles=[
        Line2D([], [], color=LINE, linewidth=2, label="Close"),
        Patch(color=BAND80, label="80% range"), Patch(color=BAND50, label="50% range"),
        Line2D([], [], color=PAST, linewidth=2, label="Past 1-day 80%"),
        Line2D([], [], marker="o", color=GOOD, linestyle="", label="Hit"),
        Line2D([], [], marker="x", color=CRITICAL, mew=2, linestyle="", label="Miss"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.11), ncol=6, frameon=False, fontsize=7, labelcolor=INK2)
    save_png(fig, path)


def overview(cfg, bars, ranges, past, regime, as_of, path) -> None:
    sectors = cfg.get("sectors") or {"": list(cfg["tickers"])}
    order = [t for ts in sectors.values() for t in ts]
    cols = 4
    rows = -(-len(order) // cols)
    height = 2.0 * rows + 0.9
    fig, axes = plt.subplots(rows, cols, figsize=(11, height), squeeze=False)
    fig.subplots_adjust(left=0.03, right=0.98, top=1 - 0.95 / height, bottom=0.03,
                        hspace=0.75, wspace=0.18)
    fig.text(0.03, 1 - 0.35 / height, f"{cfg['name']} · ranges for the session after {as_of} · "
             f"regime {regime} · bar = next-day 80% range, shade = 80% out to 5 days", fontsize=10, fontweight="bold", color=INK)
    for ax, t in zip(axes.flat, order):
        ax.set_yticks([])
        ax.set_xticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        if t not in bars:
            ax.set_title(f"{t}: no data", fontsize=8, color=MUTED, loc="left")
            continue
        s = bars[t]["close"].loc[:pd.Timestamp(as_of)].iloc[-WINDOW:]
        last = len(s) - 1
        mine = ranges[ranges["ticker"] == t].set_index("horizon_days")
        call = "no range"
        if 1 in mine.index:
            r = mine.loc[1]
            xs, lo, hi = [last, last + 1], [s.iloc[-1], r["lo80"]], [s.iloc[-1], r["hi80"]]
            if 5 in mine.index:
                xs, lo, hi = xs + [last + 5], lo + [mine.loc[5]["lo80"]], hi + [mine.loc[5]["hi80"]]
            ax.fill_between(xs, lo, hi, color=BAND80, linewidth=0)
            ax.vlines(last + 1, r["lo80"], r["hi80"], color=BAND50, linewidth=4)
            made = [(h, mine.loc[h]) for h in (1, 5) if h in mine.index and mine.loc[h]["direction"] in ("up", "down")]
            call = " ".join(f"{h}d {fmt_call(x['direction'], x['confidence'])}" for h, x in made) or "no call"
        ax.plot(range(len(s)), s.values, color=LINE, linewidth=1.5)
        ax.set_xlim(-1, last + 6)
        p = past[(past["ticker"] == t)].sort_values("target_date")
        mark = ""
        if not p.empty:
            mark = " · yday ✓" if bool(p.iloc[-1]["hit80"]) else " · yday ✗"
        chg = s.iloc[-1] / s.iloc[-2] - 1 if len(s) > 1 else 0
        sector = cfg["tickers"][t].get("sector") or ""
        ax.set_title(f"{t}  {chg:+.1%}  {call}{mark}\n{sector}", fontsize=8, color=INK, loc="left")
    for ax in list(axes.flat)[len(order):]:
        ax.set_visible(False)
    save_png(fig, path)


def run(cfg: dict) -> dict:
    con = connect(cfg["market"])
    ranges, past, regime = load(con, cfg["market"])
    bars = load_bars(con)
    as_of = pd.Timestamp(ranges["as_of_date"].iloc[0]).date()
    session = str(ranges["session_date"].iloc[0])[:10]
    out = ROOT / "reports" / cfg["market"] / "charts" / session
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for t in cfg["tickers"]:
        today = ranges[ranges["ticker"] == t]
        if t not in bars or today.empty:
            continue
        closes = bars[t]["close"].loc[:pd.Timestamp(as_of)]
        path = out / f"{safe(t)}.png"
        ticker_chart(cfg, t, closes, today, past, regime, path)
        files[t] = str(path.relative_to(ROOT))
    ov = out / "overview.png"
    overview(cfg, bars, ranges, past, regime, as_of, ov)
    return {"step": "charts", "market": cfg["market"], "session_date": session,
            "overview": str(ov.relative_to(ROOT)), "tickers": files}


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps(run(cfg), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
