"""Report sections of the weekly review: ACI, calibration, ablations, proposals and method."""

from __future__ import annotations

from marketbrief.analytics import scoring
from marketbrief.utils.markdown import markdown_table
from marketbrief.pipeline.review.markdown_cells import ablation_rows, fnum, fpct, fval


def aci_lines(review_data) -> list[str]:
    """Adaptive Conformal Inference: tracker state and the historical replay (with the held-out check)."""
    lines = []
    aci = review_data["aci"]
    aci_settings = aci["settings"]
    lines += [
        "## Adaptive conformal inference (ACI)",
        "",
        f"Switched **{'on' if aci_settings.get('enabled') else 'off'}** (`aci.enabled` in config/ranges.yaml: "
        f"{fval(aci_settings.get('enabled'))}); gamma {aci_settings['gamma']}, max shift "
        f"{aci_settings['max_shift']}, min history "
        f"{aci_settings['min_history']} scored target dates, "
        f"{'one alpha per regime' if aci_settings['by_regime'] else 'one alpha'}. "
        "Current alpha from live outcomes scored by the week's end (the target miss rate is 0.50 for the 50% "
        "band, 0.20 for the 80% band; below target = wider band).",
        "",
        markdown_table(
            ["H", "Band", "Key", "Steps", "Alpha", "Used (after min history)", "Implied coverage"],
            [
                [
                    f"{stats['horizon_days']}d",
                    f"{stats['band']}%",
                    stats["key"],
                    stats["steps"],
                    fnum(stats["alpha"], 3),
                    fnum(stats["effective_alpha"], 3),
                    fpct(stats["implied_coverage"], 1),
                ]
                for stats in aci["state"]
            ],
        ),
    ]
    rep = aci.get("replay")

    def cmp_rows(cmp):
        """Table rows comparing fixed bands with ACI per horizon and group."""
        return [
            [
                f"{horizon}d",
                group,
                value["before"].get("n"),
                f"{fpct(value['before'].get('cover50'), 1)} → {fpct(value['after'].get('cover50'), 1)}",
                f"{fpct(value['before'].get('cover80'), 1)} → {fpct(value['after'].get('cover80'), 1)}",
                f"{fnum(value['before'].get('score50'))} → {fnum(value['after'].get('score50'))}",
                f"{fnum(value['before'].get('score80'))} → {fnum(value['after'].get('score80'))}",
            ]
            for horizon, groups in cmp.items()
            for group, value in groups.items()
            if value["before"].get("n")
        ]

    cmp_hdr = ["H", "Group", "n", "50% cover", "80% cover", "50% score", "80% score"]
    if rep and rep.get("note"):
        lines += [f"> {rep['note']}.", ""]
    if rep and rep.get("comparison"):
        lines += [
            f"Historical replay `{rep['id']}` (`replay.py --aci`), fixed bands → ACI on the same rows. "
            "**In-sample: the ACI settings in config/ranges.yaml were tuned on this replay window**, so these "
            "gains are optimistic:",
            "",
            markdown_table(cmp_hdr, cmp_rows(rep["comparison"])),
        ]
        held_out = rep.get("held_out")
        if held_out:
            sel = held_out["selected"]
            lines += [
                f"Held-out check: gamma and the alpha scope (one, or one per regime) picked on as-of dates up to "
                f"{held_out['tune_end']} only (selected gamma {sel['gamma']}, "
                f"{'per regime' if sel['by_regime'] else 'one alpha'}; "
                f"{'the config settings' if held_out['selected_is_config'] else 'NOT the config settings'}). "
                "Out of sample, fixed bands → the selected settings on the later as-of dates:",
                "",
                markdown_table(cmp_hdr, cmp_rows(held_out["test_selected"])),
            ]
            if not held_out["selected_is_config"] and held_out.get("test_config"):
                lines += [
                    "The config settings on the same later dates (not out of sample: they were chosen on the "
                    "whole window):",
                    "",
                    markdown_table(cmp_hdr, cmp_rows(held_out["test_config"])),
                ]
        else:
            lines += [
                "_No held-out check stored (`replay.py --aci --aci-tune-end DATE`): any ACI proposal is provisional._",
                "",
            ]
    elif not rep:
        lines += ["_No `replay.py --aci` record stored yet: no ACI proposal._", ""]

    return lines


def calibration_lines(rec, review_data) -> list[str]:
    """The latest calibration quantiles per horizon."""
    lines = []
    lines += [
        f"## Calibration (latest as of {rec['week_end']})",
        "",
        markdown_table(
            ["H", "Source", "History n", "Live n", "q10", "q25", "q75", "q90"],
            [
                [
                    f"{call['horizon_days']}d",
                    call["source"],
                    call["n_history"],
                    call["n_live"],
                    *(fnum(call[quantile_name], 2) for quantile_name in ("q10", "q25", "q75", "q90")),
                ]
                for call in review_data["calibration"]
            ],
        ),
    ]

    return lines


def ablation_lines(rec, review_data, by_horizon) -> list[str]:
    """Ablations: replay of the live scored ranges and walk-forward on stored prices."""
    lines = []
    ab_hdr = [
        "Variant",
        "n",
        f"50% cover ({by_horizon})",
        f"80% cover ({by_horizon})",
        f"80% width ({by_horizon})",
        f"80% score ({by_horizon})",
        "Score vs current",
        "Verdict",
    ]
    live = review_data["live_ablation"]
    lines += [
        "## Ablation: replay of live scored ranges (since start)",
        "",
        "Each stored range is rebuilt with one input changed (same quantiles, base and outcome). Inputs that "
        "only exist live (cues, AI calls, earnings and event flags) can only be judged here.",
        "",
    ]
    if live["n"]:
        lines += [
            f"Round-trip consistency check against the current config: the replay rebuilds {live['reproduced']} "
            f"of {live['n']} published ranges exactly (the rest used settings or inputs it holds fixed). This "
            "checks the decomposition only; it is not an independent validation of the quantile model.",
            "",
            markdown_table(ab_hdr, ablation_rows(live)),
        ]
    else:
        lines += ["_No scored live ranges yet._", ""]
    hist = review_data["history_ablation"]
    lines += ["## Ablation: walk-forward on stored prices", ""]
    if hist.get("n"):
        share = ", ".join(
            f"{regime} {scoring.percent(value)}" for regime, value in hist["regime_share"].items() if value
        )
        lines += [
            f"Last {hist['sessions']} sessions up to {rec['week_end']}, built as `backtest.py` does (each day sees "
            "only outcomes known before it), plus regime and market-event widening rebuilt from stored bars "
            f"(regime mix: {share}). No AI, cue or earnings inputs.",
            "",
            markdown_table(ab_hdr, ablation_rows(hist)),
        ]
    else:
        lines += [f"_Not run: {hist.get('error', 'skipped')}._", ""]

    return lines


def proposal_lines(review_config, review_data, by_horizon) -> list[str]:
    """Proposed config changes, what to drop and the forecaster confidence advice."""
    lines = []
    props = review_data["proposals"]
    lines += [
        "## Proposed changes to config/ranges.yaml",
        "",
        "**Not applied.** Shown for a human to decide in the weekly run; edit `config/ranges.yaml` by hand "
        "and note the change in the commit message.",
        "",
    ]
    rows = []
    for proposal in props:
        for change in proposal["changes"]:
            rows.append(
                [
                    f"`{change['param']}`",
                    fval(change["current"]),
                    fval(change["proposed"]),
                    proposal["source"],
                    proposal["n"],
                    f"{proposal['rel_score']:+.1%}",
                    " / ".join(
                        f"{fpct(proposal['cover80_before'].get(horizon))} → "
                        f"{fpct(proposal['cover80_after'].get(horizon))}"
                        for horizon in proposal["cover80_after"]
                    ),
                    proposal["variant"],
                ]
            )
    lines += [
        markdown_table(
            [
                "Parameter",
                "Current",
                "Proposed",
                "Evidence",
                "n",
                "Score change",
                f"80% cover ({by_horizon})",
                "Variant",
            ],
            rows,
        )
        if rows
        else f"_None: no variant cleared the thresholds (n >= {review_config['min_n_recommend']}, score "
        f"{scoring.percent(review_config['min_improvement'])} better without coverage falling more than "
        f"{scoring.percent(review_config['coverage_tolerance'])} "
        f"further below target, or 80% coverage "
        f"{scoring.percent(review_config['min_coverage_gain'])} closer to target)._\n"
    ]
    drops = [proposal["variant"] for proposal in props if proposal["drop"]]
    lines += [
        "### What to drop",
        "",
        ("- " + "\n- ".join(drops)) if drops else "_Nothing: no input's removal cleared the thresholds._",
        "",
        "### Forecaster confidence",
        "",
        ("- " + "\n- ".join(review_data["advice"]))
        if review_data["advice"]
        else f"_No advice: no confidence band with n >= {review_config['min_n_calls']} misses its stated confidence._",
        "",
    ]
    return lines


def method_lines(review_config) -> list[str]:
    """The method notes closing the review."""
    lines = []
    lines += [
        "## Method",
        "",
        f"- Thresholds from `config/review.yaml`: flag below n={review_config['min_n']}, no proposal below "
        f"n={review_config['min_n_recommend']} ranges or n={review_config['min_n_calls']} calls per band.",
        "- Score change = average over horizons of the relative change in the 80% interval score (negative is better).",
        "- Each variant changes one input against the current config; proposals are not tested together, "
        "so change one parameter at a time and let the next review confirm it.",
        "- Only coverage falling below target blocks a proposal; over-coverage is priced by the interval "
        "score and narrowed by the daily self-calibration (`calibrate.py`).",
        "- `warmup_bars` and `min_pool` are ablated on price history only. `min_pool` matters only when a "
        "day's pool is smaller than it (live then falls back to normal quantiles, the walk-forward skips the "
        "day), so on two years of bars it rarely binds.",
        "- AI judgement is never backtested: AI drift and AI widening are judged only on live ranges.",
        "",
    ]
    return lines
