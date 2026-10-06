"""The report skeleton, the Slack draft and the link to the HTML report of one day."""

from __future__ import annotations

from marketbrief.presentation.report.report_parts import prepare_parts
from marketbrief.presentation.report.report_text import render_report
from marketbrief.presentation.report.slack_text import render_slack
def build(cfg: dict, day: dict, settings: dict) -> tuple[str, str, str]:
    """The report skeleton, the Slack draft and the report link of one day."""
    parts = prepare_parts(cfg, day)
    report = render_report(cfg, day, parts)
    slack, url = render_slack(cfg, day, settings, parts)
    return report, slack, url
