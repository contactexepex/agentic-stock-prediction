"""Which range engine inputs are on (config/ranges.yaml). `enabled` is true/false, a list of markets, or a mapping
market -> true/false or a list of horizons (e.g. {us: [1]})."""
from __future__ import annotations


def enabled(range_config: dict, name: str, market: str, horizon: int | None = None) -> bool:
    """Is an input on for this market (and horizon)? Without a horizon: on for any horizon."""
    on = (range_config.get(name) or {}).get("enabled", False)
    if isinstance(on, dict):
        on = on.get(market, False)
        if isinstance(on, list):
            return bool(on) if horizon is None else int(horizon) in [int(x) for x in on]
        return bool(on)
    return market in on if isinstance(on, list) else bool(on)
