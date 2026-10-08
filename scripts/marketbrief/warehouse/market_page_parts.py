"""Parts the market pages (B11: Home, Watchlist, News, Companies; docs/ws/b11.md) share: the page shell every
payload starts with (rm_common's header, horizons, status block and go-live bar), the News window as of the cut-off
(computed once per build, so every page that shows it shows the same items) and field projections, so each page
carries exactly the keys its mockup's notes.md lists."""

from __future__ import annotations

from marketbrief.constants.market_pages import NEWS_MAX_ITEMS, NEWS_WINDOW_DAYS
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.news_items import news_window
from marketbrief.warehouse.rm_registry import BuildContext


def pick(record: dict, fields: tuple[str, ...]) -> dict:
    """The record with only `fields` (a dotted `name.{a,b}` field is written as ("name", (a, b)))."""
    out = {}
    for field in fields:
        if isinstance(field, tuple):
            name, inner = field
            out[name] = None if record.get(name) is None else {key: record[name].get(key) for key in inner}
        else:
            out[field] = record.get(field)
    return out


def shell(ctx: BuildContext) -> dict:
    """The keys every market page starts with: header, horizons, the status block and the go-live bar."""
    return {
        **rm_common.header(ctx),
        **rm_common.horizons(ctx),
        "status": rm_common.status_block(ctx),
        "go_live": rm_common.go_live(ctx),
    }


def session_date(ctx: BuildContext) -> str:
    """The session being predicted (D), as the status block gives it."""
    return rm_common.status_block(ctx)["session"]["session_date"]


def news_selection(ctx: BuildContext) -> tuple[list[dict], dict]:
    """(items, window) of the News window as of the cut-off (news_items.news_window), computed once per build."""
    return ctx.shared(
        "b11_news_window",
        lambda: news_window(ctx.cfg, ctx.con, ctx.cutoff_time, NEWS_WINDOW_DAYS, NEWS_MAX_ITEMS),
    )


def companies(ctx: BuildContext, fields: tuple) -> list[dict]:
    """B4's Company records (rm_common.companies: active and inactive, with agreement_n1 and open_trades) with
    `fields`."""
    return [pick(company, fields) for company in rm_common.companies(ctx)]



def market_mockup(mockup: dict, market: str, _page_key: str) -> dict:
    """A market page's payload in its mockup's data.json (the contract cases' `mockup_payload`)."""
    return mockup["markets"][market]
