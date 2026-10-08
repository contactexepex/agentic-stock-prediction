"""The read-model framework (docs/ws/b4.md "Framework"): every rm.<table> page type is a PageBuilder, declared in a
module of this package named rm_<page>.py as `BUILDERS = (PageBuilder(...), ...)`. The sync finds the builders by
that name (no list to edit), builds every page of a market from one BuildContext (the run's clock, MB_NOW-aware),
checks each payload against its schema in api/openapi.yaml and upserts it by hash (rm_writer.py).

A builder's `build(ctx)` returns {page_key: payload}: `_` for a market-level page, the ticker (or another key the
contract names) otherwise. A page key it stops returning is deleted from rm at the next sync.

Rules every builder keeps (docs/ARCHITECTURE.md 4.3):
- read only rows stored at or before ctx.cutoff (their own storage time) and bars up to ctx.as_of;
- keep only the market's collected companies (ctx.collected: B1's watchlist(market, cutoff, "collected"); a deleted
  company is never shown) and predict or display active ones only where the page says so (ctx.active);
- put no time of the build into the payload (no cut-off, no built_at, no freshness): the envelope carries those, and
  the route adds them to the served payload (`serve`), so a rebuild of the same data gives the same hash;
- reuse the shared blocks of rm_common.py (status, strategies, go-live, horizons, header) through ctx.shared, so every
  page shows the same values.

A contract case (`CONTRACT_CASES` in the same module) ties a table to its endpoint and its approved mockup; the
contract test (tests/test_api_contract.py) and scripts/api_contract.py check every case."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property

import pandas as pd

from marketbrief.constants.warehouse import (
    MSG_DUPLICATE_TABLE,
    RM_MODULE_PREFIX,
    SERVE_PAGE,
    SERVE_STATUS,
    SERVE_VERBATIM,
)
from marketbrief.contracts.watchlist import watchlist

SERVE_MODES = (SERVE_VERBATIM, SERVE_PAGE, SERVE_STATUS)


@dataclass(frozen=True)
class PageBuilder:
    """One rm table: its payload schema (a components.schemas name), the function that builds its pages, how the
    route serves a row (`serve`: verbatim | page | status, see warehouse/contract.serve) and the owning session."""

    table: str
    schema: str
    build: Callable[[BuildContext], dict[str, dict]]
    owner: str
    serve: str = SERVE_PAGE

    def __post_init__(self):
        if self.serve not in SERVE_MODES:
            raise ValueError(f"{self.table}: serve must be one of {SERVE_MODES}")


@dataclass(frozen=True)
class ContractCase:
    """One endpoint checked against its approved mockup (design/mockups/<page>/data.json).
    path: the OpenAPI path; table: the rm table it reads; page_keys: which built pages to check (None = all);
    mockup: the data.json path from the repo root; mockup_payload: function (mockup json, market, page_key) -> the
    mockup's payload of that page; map_paths: the payload paths whose objects are maps with data keys (e.g.
    `agreement`, `strategies`), written like `$.strategies`; their values are compared, not their keys;
    extra_keys: top-level payload keys the endpoint serves beyond its mockup (named, never silent)."""

    path: str
    table: str
    mockup: str
    mockup_payload: Callable[[dict, str, str], dict]
    map_paths: tuple[str, ...] = ()
    page_keys: Callable[[str], bool] | None = None
    extra_keys: tuple[str, ...] = ()


@dataclass
class BuildContext:
    """Everything a builder may read, as of one cut-off. Lazily computed parts are shared by every builder of a
    sync, so a page never recomputes what another already has (and they agree)."""

    cfg: dict
    con: object
    cutoff_time: datetime
    memo: dict = field(default_factory=dict)

    @property
    def market(self) -> str:
        return self.cfg["market"]

    @cached_property
    def cutoff(self) -> str:
        """The cut-off as ISO text (the form the as-of SQL of dashboard/reads.py takes)."""
        return pd.Timestamp(self.cutoff_time).isoformat()

    @cached_property
    def dashboard(self) -> dict:
        """The dashboard's data of the market as of the cut-off (presentation/dashboard/assemble.gather_dashboard)."""
        from marketbrief.presentation.dashboard.assemble import gather_dashboard

        return gather_dashboard(self.cfg, self.con, self.cutoff_time)

    @property
    def as_of(self) -> str | None:
        """The newest indicator snapshot date stored by the cut-off (ISO date), or None."""
        return self.dashboard["as_of"]

    @cached_property
    def companies(self) -> list[dict]:
        """The collected companies (active and inactive) as of the cut-off (B1's accessor; deleted ones never)."""
        return watchlist(self.market, self.cutoff_time, "collected")

    @cached_property
    def collected(self) -> frozenset[str]:
        """Tickers of the collected companies: filter every stored row on these."""
        return frozenset(company["ticker"] for company in self.companies)

    @cached_property
    def active(self) -> frozenset[str]:
        """Tickers of the active companies: the ones predicted, traded and shown outside the Companies page."""
        return frozenset(company["ticker"] for company in self.companies if company["state"] == "active")

    def shared(self, name: str, compute: Callable[[], object]):
        """A value computed once per build under `name` (rm_common's blocks use it)."""
        if name not in self.memo:
            self.memo[name] = compute()
        return self.memo[name]


def module_names() -> list[str]:
    """The rm_<page> modules of this package, sorted."""
    from marketbrief import warehouse

    return sorted(
        f"{warehouse.__name__}.{info.name}"
        for info in pkgutil.iter_modules(warehouse.__path__)
        if info.name.startswith(RM_MODULE_PREFIX)
    )


def discover() -> tuple[list[PageBuilder], list[ContractCase]]:
    """Every builder and contract case declared by the rm_* modules; a table built twice is an error."""
    builders, cases = [], []
    for name in module_names():
        module = importlib.import_module(name)
        builders += list(getattr(module, "BUILDERS", ()))
        cases += list(getattr(module, "CONTRACT_CASES", ()))
    seen: dict[str, str] = {}
    for builder in builders:
        if builder.table in seen:
            raise ValueError(
                MSG_DUPLICATE_TABLE.format(table=builder.table, owners=(seen[builder.table], builder.owner))
            )
        seen[builder.table] = builder.owner
    return sorted(builders, key=lambda b: b.table), cases


def builders() -> list[PageBuilder]:
    """The registered builders, sorted by table."""
    return discover()[0]


def tables() -> tuple[str, ...]:
    """The rm tables the registered builders write."""
    return tuple(builder.table for builder in builders())


def contract_cases() -> list[ContractCase]:
    """The registered contract cases."""
    return discover()[1]
