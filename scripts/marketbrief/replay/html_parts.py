"""HTML pieces shared by the rule replay and the AI replay pages."""
from __future__ import annotations

import html


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def scaled_text(x, k=1, suffix="%", scale=100.0) -> str:
    return "n/a" if x is None else f"{scale * x:.{k}f}{suffix}"


def fmt_p(p) -> str:
    return "" if p is None else ("<0.001" if p < 0.001 else f"{p:.3g}")


def legend(extra: str = "") -> str:
    return ('<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>1-day ranges</span>'
            '<span><span class="sw" style="background:var(--s2)"></span>5-day ranges</span>' + extra + "</div>")
