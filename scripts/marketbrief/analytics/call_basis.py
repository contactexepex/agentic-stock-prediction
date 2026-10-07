"""Which return a direction call is scored on (the owner's trade, docs/DESIGN.md section 6).

- close_to_close: the as-of close to the close of the h-th session after it (every outcome stored before the
  switch; outcome rows without `label_basis` are this basis). Horizon label legacy_cc.
- open_to_close: buy at the open of D (the first session after the as-of close), sell at the close of the k-th
  session after D (N+k, decision 37: model/labels.py's end_offset, k + 1 sessions after the as-of session).
  Label n_plus_k. A 5-day call made before `call_scoring.n_plus_k_from` keeps the old window, the close of D+4
  (label legacy_5d_d4); a 1-day call was N+1 already. No open, no score.
A call made at or after `call_scoring.from` in config/settings.yaml is scored on `call_scoring.label_basis`;
without that setting every call is close_to_close. Stored outcomes are never rescored, and the two bases are
never pooled, nor are legacy labels pooled with n_plus_k: every summary of calls is split by basis and label or
names it."""

from __future__ import annotations

import pandas as pd

from marketbrief.constants.horizons import LABEL_LEGACY_5D_D4, LABEL_LEGACY_CC, LABEL_N_PLUS_K
from marketbrief.constants.model import LABEL_CLOSE_TO_CLOSE, LABEL_CONVENTIONS, LABEL_OPEN_TO_CLOSE
from marketbrief.constants.scoring import (
    BASIS_SHORT,
    MSG_UNKNOWN_BASIS,
    SETTING_BASIS,
    SETTING_CALL_SCORING,
    SETTING_FROM,
    SETTING_N_PLUS_K_FROM,
)
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


def n_plus_k_from(settings: dict | None = None) -> pd.Timestamp | None:
    """The first made_at whose open-to-close 5-day calls are N+5 (config/settings.yaml call_scoring.n_plus_k_from);
    None: every open-to-close call is N+k."""
    settings = load_settings() if settings is None else settings
    value = ((settings or {}).get(SETTING_CALL_SCORING) or {}).get(SETTING_N_PLUS_K_FROM)
    return pd.Timestamp(value) if value else None


def horizon_label(basis: str, horizon: int, made_at, since: pd.Timestamp | None) -> str:
    """The window a call is scored on: legacy_cc (close_to_close), legacy_5d_d4 (an open-to-close 5-day call made
    before `since`, sold at D+4's close) or n_plus_k."""
    if basis == LABEL_CLOSE_TO_CLOSE:
        return LABEL_LEGACY_CC
    old = since is not None and made_at is not None and pd.Timestamp(made_at) < since
    return LABEL_LEGACY_5D_D4 if int(horizon) == 5 and old else LABEL_N_PLUS_K


def target_offset(basis: str, horizon: int, label: str = LABEL_N_PLUS_K) -> int:
    """Bars after the as-of bar whose close resolves the call: open_to_close N+k: k + 1 (N+1: 2, N+5: 6),
    legacy_5d_d4: 5 (D+4); close_to_close (legacy_cc): h."""
    if basis == LABEL_CLOSE_TO_CLOSE or label == LABEL_LEGACY_CC:
        return int(horizon)
    if label == LABEL_LEGACY_5D_D4:
        return int(horizon)
    return end_offset(basis, horizon)


def label(basis) -> str:
    """A short reader's name of a basis (outcome rows without one are close_to_close)."""
    return BASIS_SHORT[basis if isinstance(basis, str) else LABEL_CLOSE_TO_CLOSE]


def current(frame: pd.DataFrame) -> str | None:
    """The basis of the newest scored call of a track-record frame (made_at, label_basis), or None."""
    if frame is None or frame.empty:
        return None
    return str(frame.sort_values(["made_at", "id"]).iloc[-1]["label_basis"])
