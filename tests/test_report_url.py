"""Report links in the Slack draft: the hosted pages_url when configured, else the repo file."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.presentation.report.gather import report_url  # noqa: E402

REPO_SETTINGS = {"repo_url": "https://github.com/owner/repo", "branch": "main"}


def test_hosted_link_with_and_without_trailing_slash():
    for host in ("https://reports.example.app", "https://reports.example.app/"):
        settings = {**REPO_SETTINGS, "pages_url": host}
        assert report_url(settings, "india", date(2026, 10, 7)) == "https://reports.example.app/india/2026-10-07.html"


def test_repo_link_without_pages_url():
    assert report_url(REPO_SETTINGS, "us", "2026-10-07") == (
        "https://github.com/owner/repo/blob/main/reports/us/2026-10-07.html")
