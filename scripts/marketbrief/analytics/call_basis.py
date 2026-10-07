"""Which return a direction call is scored on (the owner's trade, docs/DESIGN.md section 6).

- close_to_close: the as-of close to the close of the h-th session after it (every outcome stored before the
  switch; outcome rows without `label_basis` are this basis).
- open_to_close: buy at the open of D (the first session after the as-of close), sell at the close of D+1 for a
  1-day call and of D+4 for a 5-day call: model/labels.py's offsets (end_offset). No open, no score.
A call made at or after `call_scoring.from` in config/settings.yaml is scored on `call_scoring.label_basis`;
without that setting every call is close_to_close. Stored outcomes are never rescored, and the two bases are
never pooled: every summary of calls is split by basis or names it."""

from __future__ import annotations

import pandas as pd

from marketbrief.constants.model import LABEL_CLOSE_TO_CLOSE, LABEL_CONVENTIONS, LABEL_OPEN_TO_CLOSE
from marketbrief.constants.scoring import BASIS_SHORT, MSG_UNKNOWN_BASIS, SETTING_BASIS, SETTING_CALL_SCORING, SETTING_FROM
from marketbrief.core.settings import load_settings
from marketbrief.model.labels import end_offset


def switch(settings: dict | None = None) -> tuple[str, pd.Timestamp] | None:
    """(basis, first made_at it applies to) from config/settings.yaml `call_scoring`, or None."""
    settings = load_settings() if settings is None else settings
    spec = (settings or {}).get(SETTING_CALL_SCORING) or {}
    if not spec.get(SETTING_FROM):
        return None
    basis = spec.get(SETTING_BASIS, LABEL_OPEN_TO_CLOSE)
    if basis not in LABEL_CONVENTIONS:
        raise SystemExit(MSG_UNKNOWN_BASIS.format(basis=basis, known=", ".join(LABEL_CONVENTIONS)))
    return basis, pd.Timestamp(spec[SETTING_FROM])


def basis_for(made_at, rule: tuple[str, pd.Timestamp] | None) -> str:
    """The basis a call made at `made_at` is scored on."""
    if rule is None or made_at is None or (not isinstance(made_at, str) and pd.isna(made_at)):
        return LABEL_CLOSE_TO_CLOSE
    return rule[0] if pd.Timestamp(made_at) >= rule[1] else LABEL_CLOSE_TO_CLOSE


def target_offset(basis: str, horizon: int) -> int:
    """Bars after the as-of bar whose close resolves the call (open_to_close 1d: 2, 5d: 5; close_to_close: h)."""
    return end_offset(basis, horizon)


def label(basis) -> str:
    """A short reader's name of a basis (outcome rows without one are close_to_close)."""
    return BASIS_SHORT[basis if isinstance(basis, str) else LABEL_CLOSE_TO_CLOSE]


def current(frame: pd.DataFrame) -> str | None:
    """The basis of the newest scored call of a track-record frame (made_at, label_basis), or None."""
    if frame is None or frame.empty:
        return None
    return str(frame.sort_values(["made_at", "id"]).iloc[-1]["label_basis"])
