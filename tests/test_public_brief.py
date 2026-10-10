"""The public brief (C2 batch 2): the per-page link token (presentation/reader/links.py) and rm.brief
(warehouse/rm_brief.py). Without BRIEF_LINK_SECRET nothing fails: no link, no rm.brief row."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.constants import reader as text  # noqa: E402
from marketbrief.presentation.reader import links  # noqa: E402
from marketbrief.warehouse import openapi_spec, rm_brief, schema_check  # noqa: E402

SECRET = {"BRIEF_LINK_SECRET": "test-secret"}


def test_token_is_a_deterministic_128_bit_hmac_and_absent_without_the_secret():
    token = links.brief_token("india", "2026-10-12", SECRET)
    assert re.fullmatch(r"[0-9a-f]{32}", token) and token == links.brief_token("india", "2026-10-12", SECRET)
    assert token != links.brief_token("us", "2026-10-12", SECRET) != links.brief_token("india", "2026-10-13", SECRET)
    assert token != links.brief_token("india", "2026-10-12", {"BRIEF_LINK_SECRET": "other"})
    for env in ({}, {"BRIEF_LINK_SECRET": ""}, {"BRIEF_LINK_SECRET": "  "}):
        assert links.brief_token("india", "2026-10-12", env) is None and links.brief_path("india", "2026-10-12", env) is None
        assert links.has_secret(env) is False
    assert links.brief_path("us", "2026-10-12", SECRET) == f"/brief/us/2026-10-12-{links.brief_token('us', '2026-10-12', SECRET)}"
    assert links.token_sha256(token) == hashlib.sha256(token.encode()).hexdigest()


def reader_page(session: str) -> str:
    return f'<!doctype html><title>{session}</title><script type="application/json">{{"reader":{{}}}}</script>'


def setup_reports(root: Path) -> Path:
    folder = root / "reports" / "india"
    folder.mkdir(parents=True)
    for day in range(1, 13):
        (folder / f"2026-10-{day:02d}.html").write_text(reader_page(f"2026-10-{day:02d}"))
    (folder / "2026-10-13.html").write_text(reader_page("2026-10-13"))          # after the session being predicted
    (folder / "2026-09-30.html").write_text("<html>old page without the reader block</html>")
    (folder / "index.html").write_text("index")
    (folder / "review-2026-W40.md").write_text("x")
    return folder


def test_rm_brief_keeps_the_newest_reader_pages_and_only_the_token_hash(tmp_path, monkeypatch):
    setup_reports(tmp_path)
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setenv("BRIEF_LINK_SECRET", "test-secret")
    monkeypatch.setattr(rm_brief.rm_common, "status_block", lambda ctx: {"session": {"session_date": "2026-10-12"}})
    monkeypatch.setattr(text, "BRIEF_SESSIONS", 5)
    pages = rm_brief.brief_pages(SimpleNamespace(market="india"))
    assert list(pages) == ["2026-10-12", "2026-10-11", "2026-10-10", "2026-10-09", "2026-10-08"]
    page = pages["2026-10-12"]
    token = links.brief_token("india", "2026-10-12", SECRET)
    assert page == {"session": "2026-10-12", "token_sha256": links.token_sha256(token), "html": reader_page("2026-10-12")}
    assert all(token not in str(p) for p in pages.values())                       # the token itself is never stored
    document = openapi_spec.spec()
    assert schema_check.errors(page, {"$ref": "#/components/schemas/BriefPayload"}, document) == []
    monkeypatch.setattr(text, "BRIEF_SESSIONS", 30)
    assert "2026-09-30" not in rm_brief.brief_pages(SimpleNamespace(market="india"))   # an old page is not served


def test_rm_brief_without_the_secret_builds_nothing(tmp_path, monkeypatch):
    setup_reports(tmp_path)
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.delenv("BRIEF_LINK_SECRET", raising=False)

    def never(ctx):
        raise AssertionError("no read without the secret")
    monkeypatch.setattr(rm_brief.rm_common, "status_block", never)
    assert rm_brief.brief_pages(SimpleNamespace(market="india")) == {}


def test_app_link_reads_the_warehouse_config(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CONFIG", tmp_path)
    assert links.app_link("us") is None
    (tmp_path / "warehouse.yaml").write_text("app_url: https://app.example/\n")
    assert links.app_link("us") == "https://app.example/us"
