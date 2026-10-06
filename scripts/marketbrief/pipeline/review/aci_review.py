"""Adaptive Conformal Inference in the review: tracker state and the proposal from a replay."""

from __future__ import annotations

import json
from datetime import date

import numpy as np

from marketbrief.analytics import adaptive_conformal
from marketbrief.constants.review import ACI_SETTING_KEYS, TARGETS


def aci_state(con, ranges_config: dict, week_end: date) -> dict:
    """Current ACI alpha per horizon and band from live outcomes scored by the end of the week
    (shown whether or not ACI is switched on)."""
    now = f"{week_end}T23:59:59+00:00"
    try:
        tracker = adaptive_conformal.live_tracker(con, ranges_config, now, until=week_end)
    except Exception:  # a connection without range_outcomes (nothing scored): no state
        tracker = adaptive_conformal.Tracker(ranges_config)
    return {"settings": adaptive_conformal.settings(ranges_config), "state": tracker.snapshot()}


def same_aci_settings(stored: dict | None, ranges_config: dict) -> bool:
    """True when a stored replay used the ACI settings of the ranges config."""
    current_settings = adaptive_conformal.settings(ranges_config)
    return bool(stored) and all(stored.get(key) == current_settings[key] for key in ACI_SETTING_KEYS)


def latest_aci_replay(con, week_end: date, ranges_config: dict) -> dict | None:
    """The newest `replay.py --aci` record ending by the week's end whose ACI settings (gamma, max_shift,
    min_history, by_regime) equal config/ranges.yaml's; records with other settings are skipped and
    counted in `note`. Returns its before/after comparison and held-out check (if run)."""
    try:
        rows = con.execute(
            "SELECT id, end_date, settings, detail FROM replays WHERE id LIKE '%-aci%' "
            "AND end_date <= ? ORDER BY computed_at DESC, id DESC",
            [week_end],
        ).fetchall()
    except Exception:  # no replays stored
        return None
    skipped = 0
    for rid, end, settings, detail in rows:
        settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
        detail = json.loads(detail) if isinstance(detail, str) else (detail or {})
        if not detail.get("aci_comparison"):
            continue
        if not same_aci_settings(settings.get("aci"), ranges_config):
            skipped += 1
            continue
        return {
            "id": rid,
            "end_date": str(end)[:10],
            "comparison": detail["aci_comparison"],
            "held_out": detail.get("aci_held_out"),
            "settings": settings.get("aci"),
            "note": f"{skipped} newer ACI replay(s) with other settings than config/ranges.yaml skipped"
            if skipped
            else "",
        }
    if skipped:
        return {
            "id": None,
            "comparison": None,
            "held_out": None,
            "settings": None,
            "note": f"{skipped} stored ACI replay(s), none with the config/ranges.yaml ACI settings "
            f"({', '.join(f'{key} {adaptive_conformal.settings(ranges_config)[key]}' for key in ACI_SETTING_KEYS)}): "
            f"no ACI proposal; "
            "run replay.py --aci with the current settings",
        }
    return None


def aci_passes(comparison: dict) -> tuple[bool, list[float], dict, dict, int]:
    """On every horizon: lower 80% and no higher 50% interval score, and both bands' coverage closer to target."""
    rel, passed, before80, after80, sample_size = [], True, {}, {}, 0
    for horizon, groups in (comparison or {}).items():
        before, after = groups["overall"]["before"], groups["overall"]["after"]
        if not before.get("n") or before.get("score80") is None or after.get("score80") is None:
            return False, [], {}, {}, 0
        sample_size += before["n"]
        better = after["score80"] < before["score80"] and after["score50"] <= before["score50"]
        closer = all(
            abs(after[f"cover{key}"] - target) < abs(before[f"cover{key}"] - target) for key, target in TARGETS.items()
        )
        passed &= better and closer
        rel.append(after["score80"] / before["score80"] - 1)
        before80[f"{horizon}d"], after80[f"{horizon}d"] = before["cover80"], after["cover80"]
    return passed and bool(rel), rel, before80, after80, sample_size


def aci_proposal(ranges_config: dict, rep: dict | None) -> dict | None:
    """Propose switching ACI on (never when it is already on, never from a replay with other settings).
    Out of sample: the replay's held-out check (replay.py --aci-tune-end) selected the config's settings
    on the tuning dates and they pass `aci_passes` on the later test dates. Otherwise, if the whole
    window passes, the proposal is PROVISIONAL: in-sample, the settings were tuned on that replay."""
    if rep is None or not rep.get("comparison") or (ranges_config.get("aci") or {}).get("enabled"):
        return None
    if not same_aci_settings(rep.get("settings"), ranges_config):
        return None
    held_out = rep.get("held_out")
    reason = "no held-out check (replay.py --aci --aci-tune-end)"
    if held_out:
        ok_t, rel_t, b_t, a_t, n_t = aci_passes(held_out.get("test_selected"))
        if held_out.get("selected_is_config") and ok_t:
            return {
                "variant": f"ACI on (replay {rep['id']})",
                "n": n_t,
                "verdict": "improves score",
                "drop": False,
                "source": f"historical replay, out of sample (as-of dates after {held_out['tune_end']})",
                "evidence": "out-of-sample",
                "provisional": False,
                "rel_score": round(float(np.mean(rel_t)), 4),
                "changes": [{"param": "aci.enabled", "current": False, "proposed": True}],
                "cover80_before": b_t,
                "cover80_after": a_t,
            }
        reason = (
            "held-out tuning picked other settings"
            if not held_out.get("selected_is_config")
            else "held-out test dates do not pass"
        )
    passed, rel, before, after, sample_size = aci_passes(rep["comparison"])
    if not passed:
        return None
    return {
        "variant": f"ACI on (replay {rep['id']}), PROVISIONAL",
        "n": sample_size,
        "verdict": "improves score (in-sample)",
        "drop": False,
        "source": f"historical replay, in-sample: settings tuned on this replay; {reason}",
        "evidence": "in-sample",
        "provisional": True,
        "rel_score": round(float(np.mean(rel)), 4),
        "changes": [{"param": "aci.enabled", "current": False, "proposed": True}],
        "cover80_before": before,
        "cover80_after": after,
    }
