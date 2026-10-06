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


def build(cfg: dict, d: dict, settings: dict) -> tuple[str, str, str]:
    cur, market, session = cfg.get("currency", ""), cfg["market"], d["session"]
    charts = f"charts/{session}"
    have = d.get("charts") or set()   # single-purpose PNGs charts.py wrote (file names)
    img = lambda f, alt: [f"![{alt}]({charts}/{f})", ""] if f in have else []  # noqa: E731
    reg = d["regime"].iloc[0] if not d["regime"].empty else None
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
    r = d["ranges"]
    by = {(row.ticker, int(row.horizon_days)): row for row in r.itertuples()}
    feats = d["features"].set_index("ticker") if not d["features"].empty else pd.DataFrame()

    # yesterday: the market and the watchlist on the latest bar, then ranges scored on the latest target date
    names = {k: v.get("name", k) for k, v in cfg["symbols"].items()}
    mk = {x.ticker: x for x in d["market"].itertuples()} if "market" in d else {}
    market_parts = []
    for key in (benchmark_key(cfg), vol_index_key(cfg)):
        if key in mk:
            market_parts.append(f"{names.get(key, key)} {mk[key].close:,.2f} ({pct(mk[key].ret_1d)})")
    moves = feats["ret_1d"].dropna().sort_values() if len(feats) and "ret_1d" in feats else pd.Series(dtype=float)
    if len(moves):
        market_parts.append(f"watchlist {int((moves > 0).sum())} up / {int((moves < 0).sum())} down")
        market_parts.append(f"best {moves.index[-1]} {pct(moves.iloc[-1])}, worst {moves.index[0]} {pct(moves.iloc[0])}")
    market_line = f"Market on {d['as_of']}: " + " · ".join(market_parts) if market_parts else ""
    sc = d["scored"]
    s1 = sc[sc["horizon_days"] == 1] if not sc.empty else sc
    n1 = len(s1)
    h80, h50 = (int(s1["hit80"].sum()), int(s1["hit50"].sum())) if n1 else (0, 0)
    nh80 = int(s1["naive_hit80"].fillna(False).sum()) if n1 else 0
    scored_rows = [[x.ticker, f"{format_money(cur, x.lo80)}–{format_money(cur, x.hi80)}",
                    f"{format_money(cur, x.lo50)}–{format_money(cur, x.hi50)}", format_money(cur, x.actual_close),
                    mark(x.hit80), mark(x.hit50), mark(x.naive_hit80)] for x in s1.itertuples()]
    s5 = sc[sc["horizon_days"] == 5] if not sc.empty else sc
    line5 = (f"5-day ranges that matured on the same date: 80% hit {int(s5['hit80'].sum())}/{len(s5)}, "
             f"50% hit {int(s5['hit50'].sum())}/{len(s5)}." if len(s5) else "")
    cs = d["calls_scored"]
    calls_hit = int(cs["hit"].sum()) if not cs.empty else 0
    call_rows = [[x.ticker, f"{x.horizon_days}d", x.direction, percent(x.confidence), pct(x.actual_return, 2),
                  mark(x.hit)] for x in cs.itertuples()]

    # today: ranges by sector
    today_rows, n_late = [], 0
    for sector, members in (cfg.get("sectors") or {"": list(cfg["tickers"])}).items():
        for t in members:
            a, b = by.get((t, 1)), by.get((t, 5))
            if a is None and b is None:
                q = feats.loc[t]["quality"] if t in feats.index else "no data"
                today_rows.append([t, sector, "–", "–", "–", "–", f"no range ({q})", "", ""])
                continue
            base = (a or b).base_close
            made = [(h, x) for h, x in ((1, a), (5, b)) if x is not None and x.direction in ("up", "down")]
            call = " · ".join(f"{h}d {fmt_call(x.direction, x.confidence)}" for h, x in made) or "no call"
            # made at/after the first target session's open: shown for the record, never scored
            late = any(is_late(cfg, getattr(x, "as_of_date", None), getattr(x, "made_at", None))
                       for x in (a, b) if x is not None)
            n_late += late
            if late:
                call = "late: not a forecast, never scored"
            notes = "; ".join(sorted({n for x in (a, b) if x is not None for n in (list(x.notes) if x.notes is not None else [])}))
            today_rows.append([
                t, sector, format_money(cur, base),
                f"{format_money(cur, a.lo80)}–{format_money(cur, a.hi80)}" if a else "–",
                f"{format_money(cur, a.lo50)}–{format_money(cur, a.hi50)}" if a else "–",
                f"{format_money(cur, b.lo80)}–{format_money(cur, b.hi80)}" if b else "–",
                call, "–" if late else pct(feats.loc[t]["cue_change_pct"], 2) if t in feats.index else "–", notes])

    cue_rows = [[x.symbol, cfg["symbols"].get(x.symbol, {}).get("name", x.symbol), f"{x.price:,.2f}",
    pct(x.change_pct, 2)]
                for x in d["quotes"].itertuples() if x.symbol in cfg["symbols"]]
    adr_rows = [[x.symbol.replace(":ADR", ""), cfg["tickers"].get(x.symbol.replace(":ADR", ""), {}).get("adr", ""),
                 f"{x.price:,.2f}",
                 pct(x.change_pct, 2)] for x in d["quotes"].itertuples() if x.symbol.endswith(":ADR")]

    mevents = calendar.market_events(cfg, d["as_of"] + timedelta(days=1), d["as_of"] + timedelta(days=21))
    upcoming = [(e["date"], e["name"], "major" if e["major"] else "") for e in mevents]
    # data published before the open on the session day (US CPI, jobs at 08:30 ET)
    released = [e for e in mevents if e["date"] == session and e.get("release")]
    release_line = ("Calls made before release: " + ", ".join(f"{e['name']} at {e['release']}" for e in released) + "."
                    if released else "")
    upcoming += [(pd.Timestamp(x.date).date(), x.name, "company") for x in d["company_events"].itertuples()]
    upcoming.sort()

    share = lambda v: "–" if v is None or pd.isna(v) else percent(v)  # noqa: E731
    num = lambda v, f=".2f": "–" if v is None or pd.isna(v) else format(v, f)  # noqa: E731
    sc_rows = [[f"{x.h}d", x.win, x.n, share(x.c50), share(x.c80), share(x.nc80), num(x.w), num(x.nw),
                num(x.s, ".3f"), num(x.ns, ".3f"), num(x.ce), num(x.nce)] for x in d["scorecard"].itertuples()]
    regime_rows = [[f"{x.h}d", x.regime, x.n, share(x.c50), share(x.c80), share(x.nc80)]
                   for x in d["by_regime"].itertuples()]
    dir_rows = [[f"{x.h}d", x.win, x.n, share(x.hit), share(x.up)] for x in d["direction"].itertuples()]
    band_rows = [[x.band, x.n, share(x.conf), share(x.hit)] for x in d["conf_bands"].itertuples()]
    cal_rows = [[f"{x.horizon_days}d", x.source, x.n_history, x.n_live, f"{x.q10:.2f} / {x.q90:.2f}"]
                for x in d["calibration"].itertuples()]
    partial = sorted(feats.index[feats["quality"] == "PARTIAL"]) if len(feats) else []
    blocked = sorted(feats.index[feats["quality"] == "BLOCKED"]) if len(feats) else []

    md = [f"# Market brief: {cfg['name']}, {session}", "", DISCLAIMER, data_stamp(d), "",
          f"Easy-to-read version with charts and filters: [{session}.html]({session}.html)", "",
          "## Headline", "<!-- AGENT:headline -->", "",
          "## Top 3 today", "<!-- AGENT:top3 -->", "",
          "## Yesterday", "<!-- AGENT:yesterday -->", "",
          *([market_line, ""] if market_line else []),
          f"### Ranges scored (target date {d['last_target'] or '–'})", "",
          (f"Next-day ranges: **80% hit {h80}/{n1}** (naive {nh80}/{n1}) · 50% hit {h50}/{n1}" if n1 else
           "No ranges have matured yet."), "",
          markdown_table(["Ticker", "80% range", "50% range", "Actual", "80%", "50%", "Naive 80%"], scored_rows),
          line5, "",
          "### Calls scored", "", markdown_table(["Ticker", "H", "Call", "Conf.", "Move", "Hit"], call_rows),
          f"## Today ({session})", "", regime_line, "",
          *([release_line, ""] if release_line else []),
          *img("ranges.png", "Price ranges for every company"),
          markdown_table(["Ticker", "Sector", "Close", "Next day 80%", "Next day 50%", "5 days 80%", "Call", "Cue",
          "Notes"], today_rows),
          *([f"{n_late} stock(s) have ranges made after the first session they cover had opened (a "
             "mid-session or late run): they are shown for the record, are not forecasts and are never "
             "scored.", ""] if n_late else []),
          *d.get("evidence_status", []), "<!-- AGENT:calls -->", "",
          "### Overnight cues and global factors", "", markdown_table(["Symbol", "Name", "Last", "Change"], cue_rows),
          *(["### ADRs (US-listed shares, previous US session)", "",
          markdown_table(["Ticker", "ADR", "Last", "Change"], adr_rows)]
            if adr_rows else []),
          "## Tomorrow and this week", "",
          markdown_table(["Date", "Event", "Type"], [[str(a), b, c] for a, b, c in upcoming]),
          "<!-- AGENT:outlook -->", "",
          "## By sector", "", *img("sectors.png", "Sector moves")]
    for sector in (cfg.get("sectors") or {}):
        md += [f"### {sector}", "", f"<!-- AGENT:sector:{sector} -->", ""]
    md += ["## Track record", "", *img("track_record.png", "Track record: promised vs actual"),
           "Ranges (targets 50% / 80%; width, score and centre error in % of price, lower is better; "
           "naive = last close ± recent typical move, no-change = last close as the centre):", "",
           markdown_table(["H", "Window", "n", "50% cover", "80% cover", "Naive 80%", "Width", "Naive width", "Score",
                  "Naive score", "Centre err", "No-change err"], sc_rows),
           "Ranges by regime (since start):", "",
           markdown_table(["H", "Regime", "n", "50% cover", "80% cover", "Naive 80%"], regime_rows),
           "Up/down calls vs the always-up baseline:", "",
           markdown_table(["H", "Window", "n", "Hit rate", "Always-up"], dir_rows),
           "Calls by confidence band (a band should hit about as often as its confidence):", "",
           markdown_table(["Band", "n", "Avg confidence", "Hit rate"], band_rows),
           *([review_line(d["review"], md_link(d["review"]["report"].rsplit("/", 1)[-1])), ""] if d.get("review") else []),
           "## Data quality", "",
           f"- Indicators: {len(feats) - len(partial) - len(blocked)} OK, partial: {', '.join(partial) or 'none'}, "
           f"blocked: {', '.join(blocked) or 'none'}",
           f"- Regime notes: {'; '.join(reg['notes']) if reg is not None and reg['notes'] is not None and len(reg['notes']) else 'none'}", "",
           markdown_table(["H", "Calibration", "History n", "Live n", "q10 / q90"], cal_rows),
           "<!-- AGENT:data_quality -->", ""]
    report = "\n".join(md)

    url = report_url(settings, market, session)
    # calls on late ranges are not forecasts (the HTML and the table label them late)
    calls = [(t, x) for (t, h), x in sorted(by.items()) if x.direction in ("up", "down")
             and not is_late(cfg, getattr(x, "as_of_date", None), getattr(x, "made_at", None))]
    # The thread's first message is a short summary (at most 12 lines): regime, the top 3 points,
    # the number of calls (named when there are at most 3), yesterday's score and the report link.
    # Charts and the HTML file follow as replies in the thread (notify_slack.py).
    head = f"*Market brief · {cfg['name']} · {session}*"
    if reg is not None:
        head += f" · market mood: {str(reg['regime']).replace('_', ' ').lower()}"
        if reg["vol_level"] is not None and not pd.isna(reg["vol_level"]):
            head += f" ({vol_name} {reg['vol_level']:.1f})"
    if released:
        head += " · calls made before " + ", ".join(f"{e['name']} ({e['release']})" for e in released)
    hz = lambda x: "next day" if x.horizon_days == 1 else f"{x.horizon_days} days"  # noqa: E731
    if not calls:
        call_line = f"Calls today: none. Price ranges for all {len(cfg['tickers'])} stocks are in the report."
    elif len(calls) <= 3:
        call_line = f"Calls today: {len(calls)} · " + " · ".join(
            f"{t} {fmt_call(x.direction, x.confidence)} ({hz(x)}, 80% range {format_money(cur, x.lo80)}–{format_money(cur, x.hi80)})"
            for t, x in calls)
    else:
        call_line = (f"Calls today: {len(calls)} · " + ", ".join(f"{t} {fmt_call(x.direction, x.confidence)}"
                                                                  for t, x in calls[:3]) + f" and {len(calls) - 3} more in the report")
    slack = [head,
             "Top 3 today:",
             "<!-- AGENT:top3 (three lines, each starting with \"• \": the report's Top 3 points, one line each) -->",
             call_line,
             (f"Yesterday: next-day 80% ranges hit {h80}/{n1} (naive {nh80}/{n1}) · 50% hit {h50}/{n1}"
              + (f" · calls {calls_hit}/{len(cs)}" if len(cs) else "")) if n1 else "Yesterday: no ranges matured yet.",
             "<!-- AGENT:failures (only if a collector failed; otherwise delete this line) -->",
             f"Full report (charts, filters, reasons): {url}"]
    if d.get("review") and d["review"]["fresh"]:  # weekly review written in this run: one line
        slack.insert(-1, review_line(d["review"], f"{settings['repo_url']}/blob/{settings['branch']}/{d['review']['report']}"))
    return report, "\n".join(slack) + "\n", url
