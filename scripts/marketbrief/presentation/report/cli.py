"""Build the daily report skeleton and the Slack draft for one market.

Every number and table is written here from stored data; the agent only fills the
`<!-- AGENT:... -->` markers with narrative (and must not change numbers). Writes
reports/<market>/<session_date>.md and work/slack_<market>.md, and prints their paths.
The filled report is the agent-editable source; once the report gate (validate.py) has passed it, html_report.py
builds reports/<market>/<session_date>.html (the reader's view, linked from Slack) from it.
A report that was already filled in (no markers left) is kept unless --force, but only while
its `report-data` line (as_of, regime and the forecast outcome: the as-of date's call ids and this run's gate
failures, outcome_stamp.py, issue #50) matches the data; otherwise it is rebuilt and the old
copy is saved to work/report_<market>_<session>.previous.md.
Run after charts.py (the report embeds the single-purpose charts it wrote)."""

from __future__ import annotations

import json

from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.database import connect
from marketbrief.core.settings import load_settings
from marketbrief.presentation.report.build import build
from marketbrief.presentation.report.formatting import data_stamp
from marketbrief.presentation.report.gather import gather
from marketbrief.presentation.report.outcome_stamp import forecast_outcome


def main() -> int:
    """Write the report skeleton and the Slack draft and print their paths."""
    parser = market_arg(__doc__)
    parser.add_argument(
        "--force", action="store_true", help="rebuild the report even if today's report was already filled in"
    )
    args = parser.parse_args()
    cfg = require_market(args)
    settings = load_settings()
    con = connect(cfg["market"])
    report_data = gather(cfg, con)
    report_data["outcome"] = forecast_outcome(con, cfg["market"], report_data["as_of"])
    report, slack, url = build(cfg, report_data, settings)
    rpath = paths.ROOT / "reports" / cfg["market"] / f"{report_data['session']}.md"
    rpath.parent.mkdir(parents=True, exist_ok=True)
    # A report without AGENT markers was already filled by an earlier run. Keep its narrative
    # only while it still describes the same data (as_of, regime and forecast outcome in its report-data line), so
    # the report and the new Slack draft agree. A stale filled report is rebuilt, and the old
    # one is saved to work/ so its narrative can be reused where it still holds.
    old = rpath.read_text() if rpath.exists() else None
    filled = old is not None and "<!-- AGENT:" not in old
    kept = filled and not args.force and data_stamp(report_data) in old
    out = {"step": "report", "market": cfg["market"], "report": str(rpath.relative_to(paths.ROOT)), "report_kept": kept}
    if filled and not kept:
        backup = paths.ROOT / "work" / f"report_{cfg['market']}_{report_data['session']}.previous.md"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(old)
        out["previous_report"] = str(backup.relative_to(paths.ROOT))
        if not args.force:
            why = (
                "was built from other data (as_of, regime or the forecast outcome changed)"
                if "<!-- report-data:" in old
                else "has no report-data line (written before that check existed), so it cannot be shown current"
            )
            out["warning"] = (
                f"the filled report {why}: rebuilt it; refill the markers, reusing the "
                "previous narrative only where it still holds"
            )
    if not kept:
        rpath.write_text(report)
    spath = paths.ROOT / "work" / f"slack_{cfg['market']}.md"
    spath.parent.mkdir(parents=True, exist_ok=True)
    spath.write_text(slack)
    # The script-written skeletons: validate.py --stage report tells agent lines from script lines
    # by them (a kept report's skeleton is rebuilt from the same data, so it is still current).
    (paths.ROOT / "work" / f"report_{cfg['market']}_{report_data['session']}.skeleton.md").write_text(report)
    (paths.ROOT / "work" / f"slack_{cfg['market']}.skeleton.md").write_text(slack)
    print(
        json.dumps(
            {
                **out,
                "slack_draft": str(spath.relative_to(paths.ROOT)),
                "url": url,
                "agent_markers": 0 if kept else report.count("<!-- AGENT:"),
            },
            indent=2,
        )
    )
    return 0
