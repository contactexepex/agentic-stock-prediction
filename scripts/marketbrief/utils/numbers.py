"""Number parsing and rounding helpers. The four `parse_*` / `json_safe_*` variants differ on purpose
(each source writes numbers its own way), so they stay separate functions instead of one flag-driven one."""

from __future__ import annotations

import math

import pandas as pd


def round_or_none(value, digits: int = 4):
    """`value` rounded to `digits` decimals as a float; None for None, NaN and infinities."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), digits)


def share_percent_text(share, decimals: int) -> str:
    """A share (0.625) as '62.5%' with `decimals` decimals, 'n/a' when missing. Python rounding (half to even
    on the binary value); the half-up whole-percent convention is scoring.percent."""
    return "n/a" if share is None else f"{100 * share:.{decimals}f}%"


def parse_nse_number(raw) -> float | None:
    """'1,234.5' or '12%' -> a float. A literal '0' is a real zero; missing markers give None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_accounting_amount(raw) -> float | None:
    """'1,234.5' -> 1234.5; '(12.5)' -> -12.5 (accounting negative); 'Rs.' is dropped; '.', '-', '' -> None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    text = str(raw).replace(",", "").replace("Rs.", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").strip()
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def parse_sec_number(raw: str | None) -> float | None:
    """A string from an SEC XML document ('1,234.5') as a float; None when missing or not a number."""
    try:
        return float(raw.replace(",", "")) if raw not in (None, "") else None
    except ValueError:
        return None


def json_safe_float(value, digits: int | None = None):
    """JSON-safe float (None and NaN/NA -> None), rounded to `digits` decimals when given."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value = float(value)
    return round(value, digits) if digits is not None else value
