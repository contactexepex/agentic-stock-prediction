"""HTML pieces shared by the rule replay and the AI replay pages."""

from __future__ import annotations

import html


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def scaled_text(value, key=1, suffix="%", scale=100.0) -> str:
    return "n/a" if value is None else f"{scale * value:.{key}f}{suffix}"


def fmt_p(p_value) -> str:
    return "" if p_value is None else ("<0.001" if p_value < 0.001 else f"{p_value:.3g}")


def legend(extra: str = "") -> str:
    return (
        '<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>1-day ranges</span>'
        '<span><span class="sw" style="background:var(--s2)"></span>5-day ranges</span>' + extra + "</div>"
    )
