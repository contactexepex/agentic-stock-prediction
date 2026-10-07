"""Loading config/markets/<market>.yaml and config/ranges.yaml, and reading symbol roles from them."""

from __future__ import annotations

import yaml

from marketbrief.constants.config_keys import (
    BY_MARKET_SUFFIX,
    CFG_MARKET,
    CFG_SECTOR_ETFS,
    CFG_SECTORS,
    CFG_SYMBOLS,
    CFG_TICKERS,
    META_ROLE,
    META_SECTOR,
    META_SECTOR_ETF,
    META_SECTORS,
    META_YAHOO,
    ROLE_BENCHMARK,
    ROLE_SECTOR_ETF,
    ROLE_VOL_INDEX,
)
from marketbrief.constants.files import DIR_CONFIG_MARKETS, FILE_RANGES_CONFIG, YAML_SUFFIX
from marketbrief.constants.horizons import KEY_HORIZONS
from marketbrief.constants.messages import (
    MSG_SECTOR_MAPPED_TWICE,
    MSG_SECTOR_UNKNOWN,
    MSG_SECTORS_ONLY_FOR_SECTOR_ETF,
    MSG_UNKNOWN_MARKET,
)
from marketbrief.core import paths
from marketbrief.core.horizons import horizons
from marketbrief.lifecycle.loader import apply_watchlist


def load_ranges_config(market: str | None = None) -> dict:
    """config/ranges.yaml. With a market, a setting `<key>_by_market: {market: value}` replaces
    `<key>` for that market (e.g. earnings_vol_multiple_by_market). `horizons` follows config/strategies.yaml
    (core/horizons.py) unless the file sets its own list (test configs)."""
    ranges_config = yaml.safe_load((paths.CONFIG / FILE_RANGES_CONFIG).read_text())
    if KEY_HORIZONS not in ranges_config:
        ranges_config[KEY_HORIZONS] = list(horizons())
    if market:
        for key in [setting for setting in ranges_config if setting.endswith(BY_MARKET_SUFFIX)]:
            if market in (ranges_config[key] or {}):
                ranges_config[key.removesuffix(BY_MARKET_SUFFIX)] = ranges_config[key][market]
    return ranges_config


def market_names() -> list[str]:
    """The configured markets, sorted."""
    return sorted(market_path.stem for market_path in (paths.CONFIG / DIR_CONFIG_MARKETS).glob(f"*{YAML_SUFFIX}"))


def load_market(name: str) -> dict:
    """A market's config with defaults filled in: Yahoo symbol, sector and sector ETF per ticker. The company lists
    (tickers, sector membership, active_tickers) come from the watchlist events as of the run's clock
    (marketbrief/lifecycle/loader.py, docs/SPEC.md F8.2)."""
    path = paths.CONFIG / DIR_CONFIG_MARKETS / f"{name}{YAML_SUFFIX}"
    if not path.exists():
        raise SystemExit(MSG_UNKNOWN_MARKET.format(name=name, available=market_names()))
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault(CFG_MARKET, name)
    cfg.setdefault(CFG_SYMBOLS, {})
    apply_watchlist(cfg, name)
    for key, meta in cfg[CFG_TICKERS].items():
        meta.setdefault(META_YAHOO, key)
    for key, meta in cfg[CFG_SYMBOLS].items():
        meta.setdefault(META_YAHOO, key)
    sector_of = {
        ticker: sector for sector, sector_tickers in cfg.get(CFG_SECTORS, {}).items() for ticker in sector_tickers
    }
    for key, meta in cfg[CFG_TICKERS].items():
        meta.setdefault(META_SECTOR, sector_of.get(key))
    cfg[CFG_SECTOR_ETFS] = sector_etf_map(cfg)
    for key, meta in cfg[CFG_TICKERS].items():
        meta.setdefault(META_SECTOR_ETF, cfg[CFG_SECTOR_ETFS].get(meta.get(META_SECTOR)))
    return cfg


def sector_etf_map(cfg: dict) -> dict[str, str]:
    """Watchlist sector -> the sector_etf symbol that stands for it (the symbol's `sectors` list).
    A sector named by no symbol is absent. Config mistakes (see sector_etf_problems) are skipped
    here, so a typo never stops a daily run; tests/test_signals.py checks the real configs."""
    known, etf_of_sector = set(cfg.get(CFG_SECTORS) or {}), {}
    for key, meta in cfg[CFG_SYMBOLS].items():
        if meta.get(META_ROLE) != ROLE_SECTOR_ETF:
            continue
        for sector in meta.get(META_SECTORS) or []:
            if sector in known:
                etf_of_sector.setdefault(sector, key)  # the first symbol listed wins
    return etf_of_sector


def sector_etf_problems(cfg: dict) -> list[str]:
    """Mistakes in the symbols' `sectors` lists: an unknown sector, a sector claimed by two
    symbols, or `sectors` on a symbol whose role is not sector_etf."""
    known, claimed_by, problems = set(cfg.get(CFG_SECTORS) or {}), {}, []
    for key, meta in cfg[CFG_SYMBOLS].items():
        if meta.get(META_SECTORS) and meta.get(META_ROLE) != ROLE_SECTOR_ETF:
            problems.append(MSG_SECTORS_ONLY_FOR_SECTOR_ETF.format(symbol=key))
        for sector in meta.get(META_SECTORS) or []:
            if sector not in known:
                problems.append(MSG_SECTOR_UNKNOWN.format(symbol=key, sector=sector))
            elif sector in claimed_by:
                problems.append(MSG_SECTOR_MAPPED_TWICE.format(sector=sector, first=claimed_by[sector], second=key))
            else:
                claimed_by[sector] = key
    return problems


def symbols_by_role(cfg: dict, role: str) -> dict[str, dict]:
    """The market-level symbols (cues, factors, benchmark ...) that have this role."""
    return {symbol: meta for symbol, meta in cfg[CFG_SYMBOLS].items() if meta.get(META_ROLE) == role}


def benchmark_key(cfg: dict) -> str | None:
    """The benchmark symbol's key, or None."""
    return next(iter(symbols_by_role(cfg, ROLE_BENCHMARK)), None)


def vol_index_key(cfg: dict) -> str | None:
    """The volatility index symbol's key, or None."""
    return next(iter(symbols_by_role(cfg, ROLE_VOL_INDEX)), None)
