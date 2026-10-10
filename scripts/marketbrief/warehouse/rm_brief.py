"""The public brief (C2 batch 2; owner decision 2026-10-10): rm.brief, page_key = the session date, payload = the
finished reader page of html_report (reports/<market>/<session>.html, the same file as the Slack attachment) and the
SHA-256 of its link token (presentation/reader/links.py). Served read-only by web/app/brief/[market]/[slug] through
the gateway; never by /api/v1. Without BRIEF_LINK_SECRET no page is built (no link exists). Kept: the newest
BRIEF_SESSIONS report days whose session is on or before the session being predicted as of the cut-off, built by the
reader layer (older pages are left out)."""
from __future__ import annotations

import re

from marketbrief.constants import reader as text
from marketbrief.constants.warehouse import SERVE_VERBATIM
from marketbrief.core import paths
from marketbrief.presentation.reader.links import brief_token, has_secret, token_sha256
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext, PageBuilder

PAGE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")


def brief_pages(ctx: BuildContext) -> dict[str, dict]:
    """{session: {session, token_sha256, html}} of the market's newest reader pages; {} without the secret."""
    if not has_secret():
        return {}
    latest = rm_common.status_block(ctx)["session"]["session_date"]
    folder = paths.ROOT / "reports" / ctx.market
    names = sorted((p.name for p in folder.glob("*.html") if PAGE_NAME.match(p.name)), reverse=True) \
        if folder.exists() else []
    out: dict[str, dict] = {}
    for name in names:
        session = name[:-len(".html")]
        if latest is not None and session > latest:
            continue
        page = (folder / name).read_text()
        if text.BRIEF_MARKER not in page:
            continue
        out[session] = {"session": session, "token_sha256": token_sha256(brief_token(ctx.market, session)),
                        "html": page}
        if len(out) == text.BRIEF_SESSIONS:
            break
    return out


BUILDERS = (PageBuilder(text.RM_BRIEF, "BriefPayload", brief_pages, owner="C2", serve=SERVE_VERBATIM),)
