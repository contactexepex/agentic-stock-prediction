"""HTML pieces shared by the rule replay and the AI replay pages."""

from __future__ import annotations

import html

from marketbrief.constants.replay_page import SERIES_COLORS


def escape_html(value) -> str:
    """HTML-escape a value."""
    return html.escape(str(value), quote=True)


def scaled_text(value, decimals=1, suffix="%", scale=100.0) -> str:
    """A share scaled to a percent text with the given decimals; n/a when missing."""
    return "n/a" if value is None else f"{scale * value:.{decimals}f}{suffix}"


def p_value_text(p_value) -> str:
    """A p-value as text (<0.001 for very small ones)."""
    return "" if p_value is None else ("<0.001" if p_value < 0.001 else f"{p_value:.3g}")


def horizon_keys(by_horizon: dict) -> list[str]:
    """The horizon keys of a summary ("1", "2", ...), ascending in k: every horizon present in the data."""
    return sorted(by_horizon, key=int)


def series_color(horizon_keys_present: list[str], horizon: str) -> str:
    """The chart colour of a horizon: the n-th series colour (--s1 ... --s5, cycled) by its position."""
    return f"var(--s{horizon_keys_present.index(horizon) % SERIES_COLORS + 1})"


def legend(horizons: list[str], extra: str = "") -> str:
    """The legend of the N+k range series (one entry per horizon present), with extra entries."""
    return (
        '<div class="legend">'
        + "".join(
            f'<span><span class="sw" style="background:{series_color(horizons, horizon)}"></span>N+{horizon} '
            "ranges</span>"
            for horizon in horizons
        )
        + extra
        + "</div>"
    )
