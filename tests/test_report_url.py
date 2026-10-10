"""Slack draft links: the market's page in the app (config/warehouse.yaml app_url) when configured, else the report
file in the repo. The static reports site (pages_url) was deleted by the owner on 2026-10-10."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.core import paths  # noqa: E402
from marketbrief.core.settings import app_url, load_settings  # noqa: E402
from marketbrief.presentation.report.gather import report_url  # noqa: E402

REPO_SETTINGS = {"repo_url": "https://github.com/owner/repo", "branch": "main"}


def test_app_link_with_and_without_trailing_slash():
    for app in ("https://app.example", "https://app.example/"):
        assert report_url(REPO_SETTINGS, "india", date(2026, 10, 7), app) == "https://app.example/india"


def test_repo_link_without_app_url():
    assert report_url(REPO_SETTINGS, "us", "2026-10-07") == (
        "https://github.com/owner/repo/blob/main/reports/us/2026-10-07.html")


def test_live_config_links_to_the_app_and_never_to_the_deleted_site():
    assert app_url() == "https://omenix.vercel.app"
    assert "pages_url" not in load_settings()


def test_app_url_is_none_without_warehouse_config(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG", tmp_path)
    assert app_url() is None
