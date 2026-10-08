"""The 1.0 pages (WS1, docs/ws/ws1.md): rm.overview, rm.watchlist and rm.track_record, sliced from the dashboard's
data as of the cut-off (warehouse/read_models.page_payloads) and served verbatim. Their payload schemas are the 1.0
components of api/openapi.yaml (Overview, Watchlist, TrackRecord). rm.stock and rm.bars are the company page's in
2.0 (B12, warehouse/rm_company.py)."""

from __future__ import annotations

from marketbrief.constants.warehouse import (
    RM_OVERVIEW,
    RM_TRACK_RECORD,
    RM_WATCHLIST,
    SERVE_VERBATIM,
)
from marketbrief.warehouse.read_models import page_payloads
from marketbrief.warehouse.rm_registry import BuildContext, PageBuilder

SCHEMAS = {
    RM_OVERVIEW: "Overview",
    RM_WATCHLIST: "Watchlist",
    RM_TRACK_RECORD: "TrackRecord",
}


def dashboard_pages(ctx: BuildContext) -> dict[str, dict[str, dict]]:
    """table -> page_key -> payload of the 1.0 pages (computed once per build)."""

    def compute() -> dict[str, dict[str, dict]]:
        return page_payloads(ctx.dashboard)

    return ctx.shared("dashboard_pages", compute)


def table_builder(table: str):
    """The build function of one 1.0 table."""
    return lambda ctx: dashboard_pages(ctx)[table]


BUILDERS = tuple(
    PageBuilder(table, schema, table_builder(table), owner="WS1", serve=SERVE_VERBATIM)
    for table, schema in SCHEMAS.items()
)
