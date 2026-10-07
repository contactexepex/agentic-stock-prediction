"""Comparison of fixed bands with Adaptive Conformal Inference, held-out tuning and its HTML tables."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from marketbrief.analytics import adaptive_conformal
from marketbrief.constants.replay import ACI_GRID, CMP_KEYS
from marketbrief.replay.html_parts import escape_html, scaled_text
from marketbrief.replay.rule_replay.inputs import load_inputs
from marketbrief.replay.rule_replay.range_rows import replay_rows
from marketbrief.replay.rule_replay.replay_statistics import range_summary
from marketbrief.utils.numbers import round_or_none


def aci_comparison(before: dict, after: dict) -> dict:
    """Same rows, fixed bands (before) vs ACI (after): overall, by regime and by major event."""
    out = {}
    for horizon, horizon_before in before["horizons"].items():
        horizon_after = after["horizons"].get(horizon, {})
        groups = {"overall": (horizon_before.get("overall", {}), horizon_after.get("overall", {}))}
        for sect in ("by_regime", "by_major_event"):
            for key, section_row in (horizon_before.get(sect) or {}).items():
                groups[key] = (section_row, (horizon_after.get(sect) or {}).get(key, {}))
        out[horizon] = {
            key: {
                "before": {metric: before_stats.get(metric) for metric in CMP_KEYS},
                "after": {metric: after_stats.get(metric) for metric in CMP_KEYS},
            }
            for key, (before_stats, after_stats) in groups.items()
        }
    return out


def two_decimals_text(value, decimals: int = 2) -> str:
    """A number with the given decimals, empty when missing."""
    return "" if value is None else f"{value:.{decimals}f}"


ACI_SETTING_KEYS = ("gamma", "max_shift", "min_history", "by_regime")


def aci_tag(settings: dict, tune_end: date | None = None) -> str:
    """Replay id / file suffix naming the ACI settings (and the held-out split), e.g.
    -aci-g0.01-regime-s0.15-m20-t2024-12-31."""
    tag = (
        f"-aci-g{settings['gamma']:g}-{'regime' if settings['by_regime'] else 'all'}-s{settings['max_shift']:g}"
        f"-m{int(settings['min_history'])}"
    )
    return tag + (f"-t{tune_end}" if tune_end else "")


def comparison_groups(group: pd.DataFrame, horizon: int) -> dict:
    """Range summaries of all rows and of each regime."""
    out = {"overall": range_summary(group, horizon)}
    for key, regime_group in group.groupby("regime"):
        out[str(key)] = range_summary(regime_group, horizon)
    out["major event in horizon"] = range_summary(group[group["major"]], horizon)
    out["no major event"] = range_summary(group[~group["major"]], horizon)
    return out


def rows_comparison(fixed: dict, after: dict, keep) -> dict:
    """fixed vs ACI on the rows `keep(frame)` selects, per horizon: overall, by regime, by major event."""
    out = {}
    for horizon, fixed_group in fixed.items():
        before, after_groups = (
            comparison_groups(fixed_group[keep(fixed_group)], horizon),
            comparison_groups(after[horizon][keep(after[horizon])], horizon),
        )
        out[str(horizon)] = {
            key: {
                "before": {metric: group_row.get(metric) for metric in CMP_KEYS},
                "after": {metric: after_groups.get(key, {}).get(metric) for metric in CMP_KEYS},
            }
            for key, group_row in before.items()
        }
    return out


def mean_rel_score80(comparison: dict) -> float | None:
    """The mean relative change of the 80% score over the groups."""
    rel = [
        group["overall"]["after"]["score80"] / group["overall"]["before"]["score80"] - 1
        for group in comparison.values()
        if group["overall"]["before"].get("score80") and group["overall"]["after"].get("score80") is not None
    ]
    return float(np.mean(rel)) if rel else None


def held_out(
    cfg: dict, ranges_config: dict, con, tune_end: date, start: date | None = None, end: date | None = None
) -> dict:
    """Out-of-sample check of the ACI settings: every ACI_GRID variant is replayed (ACI runs online over
    the whole window), the variant with the lowest mean relative 80% interval score on the TUNING rows
    (as-of date and target close on or before tune_end) is selected, and fixed bands vs that variant (and
    vs the run's settings) are compared on the TEST rows only (as-of date after tune_end). `config` and
    `selected_is_config` describe the run's settings: config/ranges.yaml's unless --aci-gamma or --aci-by-regime
    changed them (issue #33; the weekly review only reads replays whose settings equal the config's)."""
    bars, extra = load_inputs(cfg, ranges_config, con)
    fixed, _ = replay_rows(
        cfg,
        {**ranges_config, "aci": {**adaptive_conformal.settings(ranges_config), "enabled": False}},
        bars,
        extra,
        start,
        end,
    )

    def tune(group: pd.DataFrame) -> pd.Series:  # outcome known by tune_end too (N+k exits cross it)
        """The rows used to choose the settings (as-of date and outcome on or before the tune end)."""
        return (group["date"] <= tune_end) & group["bar_target"].map(
            lambda item: isinstance(item, date) and item <= tune_end
        )

    def test(group: pd.DataFrame) -> pd.Series:
        """The rows after the tune end, used to test the chosen settings."""
        return group["date"] > tune_end

    variants, frames = [], {}
    for gamma, by_regime in ACI_GRID:
        replay_ranges = aci_ranges_config(ranges_config, gamma, by_regime)
        res, _ = replay_rows(cfg, replay_ranges, bars, extra, start, end)
        key = aci_tag(replay_ranges["aci"])
        frames[key] = (replay_ranges["aci"], res)
        variants.append(
            {
                "tag": key,
                "gamma": gamma,
                "by_regime": by_regime,
                "tune_rel_score80": round_or_none(mean_rel_score80(rows_comparison(fixed, res, tune))),
            }
        )
    best = min(
        (variant for variant in variants if variant["tune_rel_score80"] is not None),
        key=lambda variant: variant["tune_rel_score80"],
    )
    selected_settings, selected_result = frames[best["tag"]]
    current_settings = aci_ranges_config(ranges_config)["aci"]
    current_key = aci_tag(current_settings)
    if current_key not in frames:
        frames[current_key] = (
            current_settings,
            replay_rows(cfg, aci_ranges_config(ranges_config), bars, extra, start, end)[0],
        )
    return {
        "tune_end": str(tune_end),
        "grid": variants,
        "selected": {setting: selected_settings[setting] for setting in ACI_SETTING_KEYS},
        "config": {setting: current_settings[setting] for setting in ACI_SETTING_KEYS},
        "selected_is_config": all(
            selected_settings[setting] == current_settings[setting] for setting in ACI_SETTING_KEYS
        ),
        "test_selected": rows_comparison(fixed, selected_result, test),
        "test_config": rows_comparison(fixed, frames[current_key][1], test),
        "tune_config": rows_comparison(fixed, frames[current_key][1], tune),
    }


def held_out_html(held_out_result: dict | None) -> str:
    """The HTML of the held-out check, empty when there is none."""
    if not held_out_result:
        return '<p class="note">No held-out check in this run (replay.py --aci --aci-tune-end DATE).</p>'
    selected = held_out_result["selected"]
    same = " = this run's settings" if held_out_result["selected_is_config"] else " (not this run's settings)"
    return (
        f"<h3>Held-out check</h3><p>gamma and one-or-per-regime alpha picked from {len(held_out_result['grid'])} "
        f"variants on "
        f"as-of dates up to {escape_html(held_out_result['tune_end'])} only (lowest 80% interval score): gamma "
        f"{selected['gamma']}, "
        f"{'per regime' if selected['by_regime'] else 'one alpha'}"
        f"{same}. "
        f"Fixed bands vs that choice on the later, unseen as-of dates:</p>{aci_table(held_out_result['test_selected'])}"
        + (
            ""
            if held_out_result["selected_is_config"]
            else f"<p>Fixed bands vs this run's settings (config/ranges.yaml unless --aci-gamma or --aci-by-regime "
            f"changed them) on the same later "
            f"dates:</p>{aci_table(held_out_result['test_config'])}"
        )
    )


def aci_table(comparison: dict) -> str:
    """The before and after table of fixed bands against ACI."""
    rows = []
    for horizon, groups in comparison.items():
        for key, group_row in groups.items():
            before, after = group_row["before"], group_row["after"]
            if not before.get("n"):
                continue
            rows.append(
                f"<tr><td>N+{horizon}</td><td>{escape_html(key)}</td><td>{before['n']:,}</td>"
                + "".join(
                    f"<td>{scaled_text(before.get(metric))} → {scaled_text(after.get(metric))}</td>"
                    for metric in ("cover50", "cover80")
                )
                + "".join(
                    f"<td>{two_decimals_text(before.get(metric))} → {two_decimals_text(after.get(metric))}</td>"
                    for metric in ("width80_pct", "score50", "score80")
                )
                + f"<td>{two_decimals_text(before.get('qs_pct'), 3)} → "
                f"{two_decimals_text(after.get('qs_pct'), 3)}</td></tr>"
            )
    head = (
        "<tr><th>H</th><th>Group</th><th>n</th><th>50% held</th><th>80% held</th><th>80% width</th>"
        "<th>50% score</th><th>80% score</th><th>Quantile score</th></tr>"
    )
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def aci_ranges_config(ranges_config: dict, gamma: float | None = None, by_regime: bool | None = None) -> dict:
    """A copy of the range settings with ACI switched on (optionally another gamma / by_regime)."""
    aci_settings = {**adaptive_conformal.settings(ranges_config), "enabled": True}
    if gamma is not None:
        aci_settings["gamma"] = gamma
    if by_regime is not None:
        aci_settings["by_regime"] = by_regime
    return {**ranges_config, "aci": aci_settings}
