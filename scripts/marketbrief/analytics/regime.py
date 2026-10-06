"""Market regime detection (PASDS file 07, section 3) as a pure function (library).

CALM / TRENDING / EVENT_HEAVY / UNSTABLE from the vol index, the benchmark's 5-day return and
10-day realized volatility, and major scheduled events. Missing inputs pick the more
conservative regime, never the more optimistic one.
"""
from __future__ import annotations

from marketbrief.analytics.scoring import percent
from marketbrief.constants.regime import (MSG_BENCHMARK_INCOMPLETE, MSG_NO_BENCHMARK_TREND, MSG_NO_VOL_INDEX,
                                          MSG_STRESS, REGIME_CALM, REGIME_EVENT_HEAVY, REGIME_TRENDING,
                                          REGIME_UNSTABLE)


def classify(thresholds: dict, vol_level: float | None, bench_ret_5d: float | None,
             bench_vol_10d: float | None, major_event: bool,
             vol_change_1d: float | None = None) -> tuple[str, bool, list[str]]:
    """Return (regime, stress, notes). `thresholds` is the market config's `regime` section."""
    notes: list[str] = []
    stress = vol_change_1d is not None and vol_change_1d > thresholds["stress_vol_jump"]
    if stress:
        notes.append(MSG_STRESS.format(change=percent(vol_change_1d)))

    if vol_level is None:
        notes.append(MSG_NO_VOL_INDEX)
    if bench_ret_5d is None or bench_vol_10d is None:
        notes.append(MSG_BENCHMARK_INCOMPLETE)

    if (vol_level is not None and vol_level > thresholds["unstable_vol"]) or \
       (bench_vol_10d is not None and bench_vol_10d > thresholds["unstable_bench_vol"]) or stress:
        regime = REGIME_UNSTABLE
    elif major_event or vol_level is None or vol_level > thresholds["event_vol"]:
        regime = REGIME_EVENT_HEAVY
    elif (bench_ret_5d is not None and bench_ret_5d > thresholds["trend_return_5d"]
          and vol_level < thresholds["event_vol"]):
        regime = REGIME_TRENDING
    else:
        regime = REGIME_CALM  # PASDS conservative default for the remaining low-vol cases
    if bench_ret_5d is None and regime in (REGIME_CALM, REGIME_TRENDING):
        regime = REGIME_EVENT_HEAVY
        notes.append(MSG_NO_BENCHMARK_TREND)
    return regime, stress, notes

