"""One NSE session for a collector run, paced as the market config says (tests replace `nse_client`)."""
from __future__ import annotations

from marketbrief.constants.config_keys import CFG_RELATIONS, REL_ARCHIVES, REL_BASE, REL_PAUSE_SECONDS
from marketbrief.constants.sources import NSE_ARCHIVES_URL, NSE_BASE_URL, NSE_DEFAULT_PAUSE_SECONDS
from marketbrief.sources.nse_client import Nse


def nse_client(cfg: dict) -> Nse:
    """The NSE client of a market config (its `relations` section: base, archives, pause_seconds)."""
    relations = cfg.get(CFG_RELATIONS) or {}
    return Nse(relations.get(REL_BASE, NSE_BASE_URL), relations.get(REL_ARCHIVES, NSE_ARCHIVES_URL),
               pause=float(relations.get(REL_PAUSE_SECONDS, NSE_DEFAULT_PAUSE_SECONDS)))
