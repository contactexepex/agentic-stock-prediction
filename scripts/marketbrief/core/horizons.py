"""The horizon list and the N+k window (docs/SPEC.md F2.7, decision 37; session B10).

N+k: buy at the open of D, the first market session after the as-of close; sell at the close of the k-th
session after D, counted through the market calendar (weekends and holidays skipped). From the as-of close the
exit is therefore the (k + 1)-th session (`exit_offset`), and a range or close-to-close return of horizon k spans
k + 1 sessions (`window_sessions`).

The horizon list comes from config/strategies.yaml `horizons` (config/ranges.yaml follows it unless a test config
sets its own). Records written before B10 carry no `horizon_label` and keep their old window; they are labelled
on read (`legacy_label`):
- n_plus_k      the decision-37 definition (every row B10's code writes; also old open-to-close 1-day rows, which
                were N+1 already: open of D to the close of D+1);
- legacy_cc     close-to-close calls and the old ranges (1-day: as-of close -> D's close; 5-day: -> D+4's close);
- legacy_5d_d4  open-to-close 5-day model labels and calls (open of D -> close of D+4).
Legacy rows are never pooled with n_plus_k rows."""
from __future__ import annotations

from datetime import date, timedelta

import yaml

from marketbrief.constants.horizons import (
    FILE_STRATEGIES_CONFIG,
    KEY_AI_HORIZONS,
    KEY_HORIZONS,
    LABEL_LEGACY_5D_D4,
    LABEL_LEGACY_CC,
    LABEL_N_PLUS_K,
    MSG_BAD_HORIZONS,
)
from marketbrief.core import calendar, paths


def strategies_config_path():
    """config/strategies.yaml of the current config folder, else the repository's own (a test's scratch config
    folder often holds only the files it changes)."""
    path = paths.CONFIG / FILE_STRATEGIES_CONFIG
    return path if path.exists() else paths.CODE / "config" / FILE_STRATEGIES_CONFIG


def read_list(key: str) -> tuple[int, ...]:
    """A horizon list of config/strategies.yaml, checked: positive whole numbers, ascending, no repeats."""
    values = (yaml.safe_load(strategies_config_path().read_text()) or {}).get(key)
    if (not isinstance(values, list) or not values
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in values)
            or list(values) != sorted(set(values))):
        raise SystemExit(MSG_BAD_HORIZONS.format(key=key, values=values))
    return tuple(values)


def horizons() -> tuple[int, ...]:
    """The horizon list (k of N+k), e.g. (1, 2, 3, 4, 5)."""
    return read_list(KEY_HORIZONS)


def ai_horizons() -> tuple[int, ...]:
    """The AI traders' horizons (decision 38), e.g. (1, 3, 5)."""
    return read_list(KEY_AI_HORIZONS)


def exit_offset(horizon: int) -> int:
    """Sessions after the as-of session whose close is the exit of N+k: k + 1 (D is the first)."""
    return int(horizon) + 1


def window_sessions(horizon: int) -> int:
    """Sessions from the as-of close to the exit close of N+k (the range and close-to-close window): k + 1."""
    return exit_offset(horizon)


def entry_exit(cfg: dict, as_of: date, horizon: int) -> tuple[date, date]:
    """(D, the exit session of N+k) after an as-of session, through the market calendar."""
    sessions = calendar.sessions_ahead(cfg, as_of + timedelta(days=1), exit_offset(horizon))
    return sessions[0], sessions[-1]


def legacy_label(kind: str, horizon: int, label_basis: str | None = None) -> str:
    """The label of a row stored without `horizon_label` (written before B10): ranges and close-to-close calls
    are legacy_cc; open-to-close 1-day scores and calls are N+1 (same window); open-to-close 5-day ones are
    legacy_5d_d4. kind: "ranges", "model_scores" or "outcomes"."""
    if kind == "ranges" or (kind == "outcomes" and (label_basis or "close_to_close") == "close_to_close"):
        return LABEL_LEGACY_CC
    return LABEL_N_PLUS_K if int(horizon) == 1 else LABEL_LEGACY_5D_D4


def horizon_key(horizon: int, label: str | None = None) -> str:
    """The summary key of a horizon: '<k>d' for N+k rows, '<k>d <label>' for legacy ones (never pooled)."""
    return f"{int(horizon)}d" if label in (None, LABEL_N_PLUS_K) else f"{int(horizon)}d {label}"
