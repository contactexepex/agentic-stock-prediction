"""HTML pieces shared by the rule replay and the AI replay pages."""

from __future__ import annotations

import html


def escape_html(value) -> str:
    """HTML-escape a value."""
    return html.escape(str(value), quote=True)


def scaled_text(value, decimals=1, suffix="%", scale=100.0) -> str:
    """A share scaled to a percent text with the given decimals; n/a when missing."""
    return "n/a" if value is None else f"{scale * value:.{decimals}f}{suffix}"


def p_value_text(p_value) -> str:
    """A p-value as text (<0.001 for very small ones)."""
    return "" if p_value is None else ("<0.001" if p_value < 0.001 else f"{p_value:.3g}")


def legend(extra: str = "") -> str:
    """The legend of the 1-day and 5-day series, with extra entries."""
    return (
        '<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>1-day ranges</span>'
        '<span><span class="sw" style="background:var(--s2)"></span>5-day ranges</span>' + extra + "</div>"
    )
