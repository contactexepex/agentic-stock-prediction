"""Market regime detection (PASDS file 07, section 3) as a pure function (library).

CALM / TRENDING / EVENT_HEAVY / UNSTABLE from the vol index, the benchmark's 5-day return and
10-day realized volatility, and major scheduled events. Missing inputs pick the more
conservative regime, never the more optimistic one.
"""
from __future__ import annotations

import scoring

ORDER = ["CALM", "TRENDING", "EVENT_HEAVY", "UNSTABLE"]


def classify(th: dict, vol_level: float | None, bench_ret_5d: float | None,
             bench_vol_10d: float | None, major_event: bool,
             vol_change_1d: float | None = None) -> tuple[str, bool, list[str]]:
    """Return (regime, stress, notes). `th` is the market config's `regime` section."""
    notes: list[str] = []
    stress = vol_change_1d is not None and vol_change_1d > th["stress_vol_jump"]
    if stress:
        notes.append(f"stress: vol index jumped {scoring.percent(vol_change_1d)} in one day")

    if vol_level is None:
        notes.append("vol index unavailable: conservative EVENT_HEAVY floor")
    if bench_ret_5d is None or bench_vol_10d is None:
        notes.append("benchmark history incomplete")

    if (vol_level is not None and vol_level > th["unstable_vol"]) or \
       (bench_vol_10d is not None and bench_vol_10d > th["unstable_bench_vol"]) or stress:
        regime = "UNSTABLE"
    elif major_event or vol_level is None or vol_level > th["event_vol"]:
        regime = "EVENT_HEAVY"
    elif bench_ret_5d is not None and bench_ret_5d > th["trend_return_5d"] and vol_level < th["event_vol"]:
        regime = "TRENDING"
    else:
        regime = "CALM"  # PASDS conservative default for the remaining low-vol cases
    if bench_ret_5d is None and regime in ("CALM", "TRENDING"):
        regime = "EVENT_HEAVY"
        notes.append("no benchmark trend data: raised to EVENT_HEAVY")
    return regime, stress, notes
