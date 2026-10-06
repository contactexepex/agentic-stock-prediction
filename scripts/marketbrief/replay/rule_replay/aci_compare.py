"""Comparison of fixed bands with Adaptive Conformal Inference, held-out tuning and its HTML tables."""
from __future__ import annotations

from datetime import date
import numpy as np
import pandas as pd
from marketbrief.analytics import adaptive_conformal
from marketbrief.utils.numbers import round_or_none
from marketbrief.constants.replay import ACI_GRID, CMP_KEYS
from marketbrief.replay.html_parts import esc, scaled_text
from marketbrief.replay.rule_replay.inputs import load_inputs
from marketbrief.replay.rule_replay.range_rows import replay_rows
from marketbrief.replay.rule_replay.replay_statistics import range_summary


def aci_comparison(before: dict, after: dict) -> dict:
    """Same rows, fixed bands (before) vs ACI (after): overall, by regime and by major event."""
    out = {}
    for h, hb in before["horizons"].items():
        ha = after["horizons"].get(h, {})
        groups = {"overall": (hb.get("overall", {}), ha.get("overall", {}))}
        for sect in ("by_regime", "by_major_event"):
            for k, v in (hb.get(sect) or {}).items():
                groups[k] = (v, (ha.get(sect) or {}).get(k, {}))
        out[h] = {k: {"before": {c: b.get(c) for c in CMP_KEYS}, "after": {c: a.get(c) for c in CMP_KEYS}}
                  for k, (b, a) in groups.items()}
    return out


def two_decimals_text(x, k: int = 2) -> str:
    return "" if x is None else f"{x:.{k}f}"


ACI_SETTING_KEYS = ("gamma", "max_shift", "min_history", "by_regime")


def aci_tag(a: dict, tune_end: date | None = None) -> str:
    """Replay id / file suffix naming the ACI settings (and the held-out split), e.g.
    -aci-g0.01-regime-s0.15-m20-t2024-12-31."""
    t = (f"-aci-g{a['gamma']:g}-{'regime' if a['by_regime'] else 'all'}-s{a['max_shift']:g}"
         f"-m{int(a['min_history'])}")
    return t + (f"-t{tune_end}" if tune_end else "")


def comparison_groups(g: pd.DataFrame, h: int) -> dict:
    out = {"overall": range_summary(g, h)}
    for k, x in g.groupby("regime"):
        out[str(k)] = range_summary(x, h)
    out["major event in horizon"] = range_summary(g[g["major"]], h)
    out["no major event"] = range_summary(g[~g["major"]], h)
    return out


def rows_comparison(fixed: dict, after: dict, keep) -> dict:
    """fixed vs ACI on the rows `keep(frame)` selects, per horizon: overall, by regime, by major event."""
    out = {}
    for h, gf in fixed.items():
        b, a = comparison_groups(gf[keep(gf)], h), comparison_groups(after[h][keep(after[h])], h)
        out[str(h)] = {k: {"before": {c: v.get(c) for c in CMP_KEYS}, "after": {c: a.get(k, {}).get(c) for c in CMP_KEYS}}
                       for k, v in b.items()}
    return out


def mean_rel_score80(cmp: dict) -> float | None:
    rel = [g["overall"]["after"]["score80"] / g["overall"]["before"]["score80"] - 1 for g in cmp.values()
           if g["overall"]["before"].get("score80") and g["overall"]["after"].get("score80") is not None]
    return float(np.mean(rel)) if rel else None


def held_out(cfg: dict, rc: dict, con, tune_end: date, start: date | None = None, end: date | None = None) -> dict:
    """Out-of-sample check of the ACI settings: every ACI_GRID variant is replayed (ACI runs online over
    the whole window), the variant with the lowest mean relative 80% interval score on the TUNING rows
    (as-of date and target close on or before tune_end) is selected, and fixed bands vs that variant (and
    vs the config's settings) are compared on the TEST rows only (as-of date after tune_end)."""
    bars, extra = load_inputs(cfg, rc, con)
    fixed, _ = replay_rows(cfg, {**rc, "aci": {**adaptive_conformal.settings(rc), "enabled": False}}, bars, extra, start, end)

    def tune(g: pd.DataFrame) -> pd.Series:   # outcome known by tune_end too (5-day targets cross it)
        return (g["date"] <= tune_end) & g["bar_target"].map(lambda x: isinstance(x, date) and x <= tune_end)

    def test(g: pd.DataFrame) -> pd.Series:
        return g["date"] > tune_end

    variants, frames = [], {}
    for gamma, br in ACI_GRID:
        r = aci_rc(rc, gamma, br)
        res, _ = replay_rows(cfg, r, bars, extra, start, end)
        key = aci_tag(r["aci"])
        frames[key] = (r["aci"], res)
        variants.append({"tag": key, "gamma": gamma, "by_regime": br,
                         "tune_rel_score80": round_or_none(mean_rel_score80(rows_comparison(fixed, res, tune)))})
    best = min((v for v in variants if v["tune_rel_score80"] is not None), key=lambda v: v["tune_rel_score80"])
    sel_settings, sel_res = frames[best["tag"]]
    cur = aci_rc(rc)["aci"]
    cur_key = aci_tag(cur)
    if cur_key not in frames:
        frames[cur_key] = (cur, replay_rows(cfg, aci_rc(rc), bars, extra, start, end)[0])
    return {"tune_end": str(tune_end), "grid": variants,
            "selected": {k: sel_settings[k] for k in ACI_SETTING_KEYS},
            "config": {k: cur[k] for k in ACI_SETTING_KEYS},
            "selected_is_config": all(sel_settings[k] == cur[k] for k in ACI_SETTING_KEYS),
            "test_selected": rows_comparison(fixed, sel_res, test),
            "test_config": rows_comparison(fixed, frames[cur_key][1], test),
            "tune_config": rows_comparison(fixed, frames[cur_key][1], tune)}


def held_out_html(ho: dict | None) -> str:
    if not ho:
        return "<p class=\"note\">No held-out check in this run (replay.py --aci --aci-tune-end DATE).</p>"
    sel = ho["selected"]
    return (f"<h3>Held-out check</h3><p>gamma and one-or-per-regime alpha picked from {len(ho['grid'])} variants on "
            f"as-of dates up to {esc(ho['tune_end'])} only (lowest 80% interval score): gamma {sel['gamma']}, "
            f"{'per regime' if sel['by_regime'] else 'one alpha'}"
            f"{' = the config settings' if ho['selected_is_config'] else ' (not the config settings)'}. "
            f"Fixed bands vs that choice on the later, unseen as-of dates:</p>{aci_table(ho['test_selected'])}"
            + ("" if ho["selected_is_config"] else
               f"<p>Fixed bands vs the config settings on the same later dates:</p>{aci_table(ho['test_config'])}"))


def aci_table(cmp: dict) -> str:
    rows = []
    for h, groups in cmp.items():
        for k, v in groups.items():
            b, a = v["before"], v["after"]
            if not b.get("n"):
                continue
            rows.append(f"<tr><td>{h}d</td><td>{esc(k)}</td><td>{b['n']:,}</td>"
                        + "".join(f"<td>{scaled_text(b.get(c))} → {scaled_text(a.get(c))}</td>" for c in ("cover50", "cover80"))
                        + "".join(f"<td>{two_decimals_text(b.get(c))} → {two_decimals_text(a.get(c))}</td>"
                                  for c in ("width80_pct", "score50", "score80"))
                        + f"<td>{two_decimals_text(b.get('qs_pct'), 3)} → {two_decimals_text(a.get('qs_pct'), 3)}</td></tr>")
    head = ("<tr><th>H</th><th>Group</th><th>n</th><th>50% held</th><th>80% held</th><th>80% width</th>"
            "<th>50% score</th><th>80% score</th><th>Quantile score</th></tr>")
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def aci_rc(rc: dict, gamma: float | None = None, by_regime: bool | None = None) -> dict:
    """A copy of the range settings with ACI switched on (optionally another gamma / by_regime)."""
    a = {**adaptive_conformal.settings(rc), "enabled": True}
    if gamma is not None:
        a["gamma"] = gamma
    if by_regime is not None:
        a["by_regime"] = by_regime
    return {**rc, "aci": a}
