"""The report skeleton markdown: tables, headings and the AGENT markers the agents fill."""

from __future__ import annotations

from marketbrief.constants.report import DISCLAIMER
from marketbrief.core.horizons import horizons
from marketbrief.lifecycle.loader import active_sectors
from marketbrief.presentation.report.formatting import data_stamp, md_link, review_line
from marketbrief.presentation.report.report_parts import ReportParts
from marketbrief.utils.markdown import markdown_table


def render_report(cfg: dict, day: dict, parts: ReportParts) -> str:
    """The report skeleton: data, tables and the AGENT markers the agents fill."""
    adr_rows = parts.adr_rows
    band_rows = parts.band_rows
    blocked = parts.blocked
    cal_rows = parts.cal_rows
    call_rows = parts.call_rows
    cue_rows = parts.cue_rows
    dir_rows = parts.dir_rows
    feats = parts.feats
    h50 = parts.h50
    h80 = parts.h80
    img = parts.img
    line5 = parts.line5
    market_line = parts.market_line
    n_late = parts.n_late
    nh80 = parts.nh80
    one_day_count = parts.one_day_count
    listed = horizons()
    first, last = listed[0], listed[-1]   # the Today table's columns (N+k, B10)
    partial = parts.partial
    reg = parts.reg
    regime_line = parts.regime_line
    regime_rows = parts.regime_rows
    release_line = parts.release_line
    sc_rows = parts.sc_rows
    scored_rows = parts.scored_rows
    session = parts.session
    today_rows = parts.today_rows
    upcoming = parts.upcoming
    report_lines = [
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
            f"{parts.one_day_name} ranges: **80% hit {h80}/{one_day_count}** (naive {nh80}/{one_day_count}) · 50% hit "
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
            ["Ticker", "Sector", "Close", f"N+{first} 80%", f"N+{first} 50%", f"N+{last} 80%", "Call", "Cue",
             "Notes"],
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
    for sector in active_sectors(cfg):
        report_lines += [f"### {sector}", "", f"<!-- AGENT:sector:{sector} -->", ""]
    report_lines += [
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
    report = "\n".join(report_lines)

    return report
