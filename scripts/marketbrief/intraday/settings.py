"""config/intraday.yaml and the ids of a check."""

from __future__ import annotations

from datetime import datetime

import yaml

from marketbrief.contracts.strategies import STRATEGIES_FILE
from marketbrief.core import paths
from marketbrief.intraday.constants import CHECK_ID_PREFIX, EXPLANATION_ID_PREFIX, FILE_INTRADAY_CONFIG


def load_intraday_config() -> dict:
    """The intraday settings (read at call time, so tests can point paths.CONFIG elsewhere)."""
    return yaml.safe_load((paths.CONFIG / FILE_INTRADAY_CONFIG).read_text(encoding="utf-8"))


def check_time(now: datetime) -> datetime:
    """The check time: the clock truncated to the minute (a rerun in the same minute is the same check)."""
    return now.replace(second=0, microsecond=0)


def check_id(market: str, check_at: datetime) -> str:
    """ic-<market>-<YYYY-MM-DDTHH:MMZ>."""
    return f"{CHECK_ID_PREFIX}-{market}-{check_at:%Y-%m-%dT%H:%M}Z"


def row_id(check: str, ticker: str) -> str:
    """The id of one ticker's row of a check."""
    return f"{check}-{ticker}"


def explanation_id(check_row_id: str) -> str:
    """The id of the explainer's note on a check row."""
    return f"{EXPLANATION_ID_PREFIX}-{check_row_id}"


def configured_horizons() -> tuple[int, ...]:
    """The horizon list N+k (B9): B10's contracts.horizons.horizons() once built, else config/strategies.yaml
    `horizons` (W1), else () when neither exists (callers then use the horizons present in the data)."""
    from marketbrief.contracts import horizons as horizon_contract

    try:
        return tuple(int(k) for k in horizon_contract.horizons())
    except NotImplementedError:
        pass
    path = paths.CONFIG / STRATEGIES_FILE
    if not path.exists():
        return ()
    return tuple(int(k) for k in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("horizons") or [])


def trade_check_id(check: str, trade_id: str) -> str:
    """The id of one open trade's row of a check (W1: <check_id>-<trade_id>)."""
    return f"{check}-{trade_id}"


def alert_id(check: str, ticker: str, suffix: str) -> str:
    """The id of one alert of a check: <check_id>-<ticker>-trades | <check_id>-<ticker>-news-<news id>."""
    return f"{check}-{ticker}-{suffix}"
