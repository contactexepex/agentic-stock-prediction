"""The loader switch (F8.2): the market config's company lists rebuilt from the watchlist events as of the run's
clock (MB_NOW-aware).

- cfg["tickers"]: every collected company (active and inactive; never deleted). A company with an entry under the
  config's `company_meta:` (or the legacy `tickers:`) keeps that entry (news names, aliases, ADR ...); a company
  added through onboarding gets its identity from its add event (name, yahoo, exchange, nse, cik). The
  `company_meta:` key itself is replaced by cfg["tickers"] at the same place; a config with both keys is refused.
- cfg["sectors"]: membership rebuilt from the companies' sectors (set on the add event; the config's `sectors:`
  for config tickers without a stored add). The config's sector order and member order are kept; new sectors and
  members follow in watchlist order; a config sector left without a collected member is dropped.
- cfg["active_tickers"]: the active companies, in cfg["tickers"] order. Code that predicts or displays reads it
  (or `active_sectors`); code that collects keeps reading cfg["tickers"].
- Market symbols of role `adr` whose `adr_of` company is deleted are dropped (no collection of a deleted company).

With no stored event the result equals the config's company list (events.implicit_adds; config_companies).
During onboarding the environment variable MB_LIFECYCLE_CANDIDATE (lifecycle/constants.py) names a JSON file with
one candidate company: the config then holds only that company and no market-level symbols, so collectors backfill
it alone."""
from __future__ import annotations

import json
import os
from pathlib import Path

from marketbrief.constants.config_keys import CFG_SECTORS, CFG_SYMBOLS, CFG_TICKERS, META_ADR
from marketbrief.core.clock import clock
from marketbrief.lifecycle.constants import CFG_COMPANY_META, ENV_CANDIDATE, ERR_BOTH_COMPANY_KEYS, STATE_ACTIVE
from marketbrief.lifecycle.events import fold, implicit_adds, not_deleted, stored_events
from marketbrief.lifecycle.identity import meta_from_identity

CFG_ACTIVE_TICKERS = "active_tickers"
ROLE_ADR, META_ADR_OF = "adr", "adr_of"


def config_companies(market: str, config: dict) -> tuple[dict, bool]:
    """(per-company metadata, meta_only) of a market config: its `company_meta:` (meta_only: an entry seeds only a
    market without any stored event) or the legacy `tickers:`; a config with both is refused."""
    meta, legacy = config.get(CFG_COMPANY_META), config.get(CFG_TICKERS)
    if meta is not None and legacy is not None:
        raise ValueError(ERR_BOTH_COMPANY_KEYS.format(market=market))
    return (meta or {}, True) if meta is not None else (legacy or {}, False)


def companies_as_of(market: str, config: dict, as_of=None) -> dict[str, dict]:
    """{ticker: company} of every company ever added (deleted included) as of `as_of` (default: the clock); `config`
    is the market config (its company metadata and `sectors:` give the implicit seed)."""
    stored = stored_events(market)
    config_tickers, meta_only = config_companies(market, config)
    rows = implicit_adds(market, config_tickers, config.get(CFG_SECTORS) or {}, stored, meta_only) + stored
    return fold(rows, as_of or clock())


def with_tickers(cfg: dict, tickers: dict) -> dict:
    """cfg with cfg["tickers"] set at the place of its `company_meta:` key (or of `tickers:`), in place."""
    if CFG_COMPANY_META not in cfg:
        cfg[CFG_TICKERS] = tickers
        return cfg
    rebuilt = {(CFG_TICKERS if key == CFG_COMPANY_META else key): (tickers if key == CFG_COMPANY_META else value)
               for key, value in cfg.items()}
    cfg.clear()
    cfg.update(rebuilt)
    return cfg


def rebuilt_sectors(config_sectors: dict, sector_of: dict[str, str | None]) -> dict[str, list[str]]:
    """Sector -> members: config order first, then new sectors and members in watchlist order."""
    config_sectors = config_sectors or {}
    sectors: dict[str, list[str]] = {}
    for sector, members in config_sectors.items():
        sectors[sector] = [ticker for ticker in members or [] if sector_of.get(ticker) == sector]
    for ticker, sector in sector_of.items():
        if sector is None:
            continue
        members = sectors.setdefault(sector, [])
        if ticker not in members:
            members.append(ticker)
    return {sector: members for sector, members in sectors.items()
            if members or not (config_sectors.get(sector) or [])}


def apply_watchlist(cfg: dict, market: str) -> dict:
    """Replace cfg's company lists by the watchlist as of the clock (see the module docstring); returns cfg."""
    candidate = os.environ.get(ENV_CANDIDATE)
    if candidate:
        return apply_candidate(cfg, json.loads(Path(candidate).read_text()))
    config_tickers, config_sectors = config_companies(market, cfg)[0], cfg.get(CFG_SECTORS) or {}
    companies = not_deleted(companies_as_of(market, cfg))
    tickers = {}
    for ticker, company in companies.items():
        tickers[ticker] = config_tickers[ticker] if ticker in config_tickers else meta_from_identity(company)
    with_tickers(cfg, tickers)
    cfg[CFG_SECTORS] = rebuilt_sectors(config_sectors, {ticker: company.get("sector")
                                                        for ticker, company in companies.items()})
    cfg[CFG_ACTIVE_TICKERS] = [ticker for ticker, company in companies.items() if company["state"] == STATE_ACTIVE]
    symbols = cfg.get(CFG_SYMBOLS) or {}
    if any((meta or {}).get("role") == ROLE_ADR and (meta or {}).get(META_ADR_OF) not in tickers
           for meta in symbols.values()):
        cfg[CFG_SYMBOLS] = {key: meta for key, meta in symbols.items()
                            if not ((meta or {}).get("role") == ROLE_ADR and meta.get(META_ADR_OF) not in tickers)}
    return cfg


def apply_candidate(cfg: dict, company: dict) -> dict:
    """The onboarding config: only the candidate company, no market-level symbols."""
    meta = meta_from_identity(company)
    meta.pop(META_ADR, None)
    with_tickers(cfg, {company["ticker"]: meta})
    cfg[CFG_SECTORS] = {company["sector"]: [company["ticker"]]} if company.get("sector") else {}
    cfg[CFG_ACTIVE_TICKERS] = [company["ticker"]]
    cfg[CFG_SYMBOLS] = {}
    return cfg


def active_tickers(cfg: dict) -> list[str]:
    """The active companies (predicted, published, displayed); a config built without the loader: all tickers."""
    active = cfg.get(CFG_ACTIVE_TICKERS)
    return list(cfg[CFG_TICKERS]) if active is None else [ticker for ticker in cfg[CFG_TICKERS] if ticker in active]


def active_sectors(cfg: dict) -> dict[str, list[str]]:
    """cfg["sectors"] with only active members; a sector without an active member is left out."""
    active = set(active_tickers(cfg))
    out = {}
    for sector, members in (cfg.get(CFG_SECTORS) or {}).items():
        kept = [ticker for ticker in members or [] if ticker in active]
        if kept or not members:
            out[sector] = kept
    return out
