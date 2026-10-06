"""Which range engine inputs are on (config/ranges.yaml). `enabled` is true/false, a list of markets, or a mapping
market -> true/false or a list of horizons (e.g. {us: [1]})."""

from __future__ import annotations


def enabled(range_config: dict, name: str, market: str, horizon: int | None = None) -> bool:
    """Is an input on for this market (and horizon)? Without a horizon: on for any horizon."""
    switched_on = (range_config.get(name) or {}).get("enabled", False)
    if isinstance(switched_on, dict):
        switched_on = switched_on.get(market, False)
        if isinstance(switched_on, list):
            return (
                bool(switched_on)
                if horizon is None
                else int(horizon) in [int(horizon_value) for horizon_value in switched_on]
            )
        return bool(switched_on)
    return market in switched_on if isinstance(switched_on, list) else bool(switched_on)
