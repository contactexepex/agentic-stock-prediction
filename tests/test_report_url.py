"""Slack draft links: the market's page in the app (config/settings.yaml slack_link_url) when configured, else the
report file in the repo. The static reports site (pages_url) is retired from Slack links (owner, 2026-10-10)."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.core import paths  # noqa: E402
from marketbrief.core.settings import load_settings, slack_link_url  # noqa: E402
from marketbrief.presentation.report.gather import report_url  # noqa: E402

REPO_SETTINGS = {"repo_url": "https://github.com/owner/repo", "branch": "main"}


def test_app_link_with_and_without_trailing_slash():
    for app in ("https://app.example", "https://app.example/"):
        assert report_url(REPO_SETTINGS, "india", date(2026, 10, 7), app) == "https://app.example/india"


def test_repo_link_without_slack_link_url():
    assert report_url(REPO_SETTINGS, "us", "2026-10-07") == (
        "https://github.com/owner/repo/blob/main/reports/us/2026-10-07.html")


def test_live_config_links_to_the_app_not_the_static_site():
    assert slack_link_url() == "https://omenix.vercel.app"
    assert "pages_url" not in load_settings()


def test_slack_link_url_is_none_when_not_configured(tmp_path, monkeypatch):
    (tmp_path / "settings.yaml").write_text("repo_url: https://github.com/owner/repo\n")
    monkeypatch.setattr(paths, "CONFIG", tmp_path)
    assert slack_link_url() is None


def test_brief_link_with_the_secret_and_the_setting(monkeypatch):
    """C2's public brief: <brief_link_url>/brief/<market>/<session>-<token>, the token from links.brief_path."""
    from marketbrief.presentation.reader.links import brief_path
    from marketbrief.presentation.report.gather import brief_url

    settings = {**REPO_SETTINGS, "brief_link_url": "https://gw.example/"}
    assert brief_url(settings, "us", date(2026, 10, 12)) is None             # no secret: keep the other link
    monkeypatch.setenv("BRIEF_LINK_SECRET", "test-secret")
    path = brief_path("us", "2026-10-12")
    assert path.startswith("/brief/us/2026-10-12-") and len(path.rsplit("-", 1)[1]) == 32
    assert brief_url(settings, "us", date(2026, 10, 12)) == "https://gw.example" + path
    assert brief_url(REPO_SETTINGS, "us", date(2026, 10, 12)) is None          # no brief_link_url: no brief link
    assert load_settings()["brief_link_url"] == "https://omenix-gateway.vercel.app"

