"""The 1.0 pages (WS1, docs/ws/ws1.md): rm.overview, rm.stock, rm.bars and rm.track_record, sliced from the
dashboard's data as of the cut-off (warehouse/read_models.page_payloads) and served verbatim (rm.watchlist is B11's
2.0 page, warehouse/rm_watchlist.py). Their payload schemas are the 1.0 components of api/openapi.yaml (Overview,
StockDetail, Bars, TrackRecord)."""

from __future__ import annotations

from marketbrief.constants.warehouse import (
    RM_BARS,
    RM_OVERVIEW,
    RM_STOCK,
    RM_TRACK_RECORD,
    SERVE_VERBATIM,
)
from marketbrief.warehouse.read_models import page_payloads, upcoming_events
from marketbrief.warehouse.rm_registry import BuildContext, PageBuilder

SCHEMAS = {
    RM_OVERVIEW: "Overview",
    RM_STOCK: "StockDetail",
    RM_BARS: "Bars",
    RM_TRACK_RECORD: "TrackRecord",
}


def dashboard_pages(ctx: BuildContext) -> dict[str, dict[str, dict]]:
    """table -> page_key -> payload of the 1.0 pages (computed once per build)."""

    def compute() -> dict[str, dict[str, dict]]:
        data = ctx.dashboard
        events = upcoming_events(ctx.con, data["as_of"], ctx.cutoff) if data["as_of"] else {}
        return page_payloads(data, events)

    return ctx.shared("dashboard_pages", compute)


def table_builder(table: str):
    """The build function of one 1.0 table."""
    return lambda ctx: dashboard_pages(ctx)[table]


BUILDERS = tuple(
    PageBuilder(table, schema, table_builder(table), owner="WS1", serve=SERVE_VERBATIM)
    for table, schema in SCHEMAS.items()
)
