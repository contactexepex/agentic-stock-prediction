"""Feature-set variants of the signal-model backtest and their headline numbers (model_backtest.py
--cross-groups / --ablate; docs/DESIGN.md section 15).

A variant is a name and the cross-market groups it switches on; every other setting is config/model.yaml
as written (nothing is tuned on the test period). --ablate evaluates on one panel: `all` (every group),
`none` (the current features), `only <group>` (current features plus one group) and `all minus <group>`.
The headline per market x horizon x label: out-of-sample n, Brier and its base-rate reference, Brier
skill, AUC with its 95% block-bootstrap interval, and for open-to-close the paper long per threshold after
costs with the model-minus-baseline differences. `scores_skill`: Brier skill > 0 and the AUC interval above
0.5. `skill` (open-to-close only, the tradable label): scores_skill and, at some threshold, the long beats
every baseline with an interval above 0. Close-to-close has no paper test and `skill` false: with features
known only after the as-of close (the overnight cues), predicting the close-to-close move includes the
overnight gap, which no one can buy at the as-of close."""
from __future__ import annotations

import copy

from marketbrief.constants.model import CROSS_KEY, CROSS_MARKET_FEATURES, MIN_VERDICT_DATES

ALL, NONE, CONFIG = "all", "none", "config"


def market_groups(market: str) -> tuple[str, ...]:
    """The cross-market groups defined for a market."""
    return tuple(CROSS_MARKET_FEATURES.get(market, {}))


def with_groups(settings: dict, market: str, groups) -> dict:
    """A copy of the settings with exactly `groups` switched on for `market`."""
    out = copy.deepcopy(settings)
    out.setdefault(CROSS_KEY, {})[market] = {group: group in groups for group in market_groups(market)}
    return out


def parse_groups(text: str, market: str, configured: tuple[str, ...]) -> tuple[str, ...]:
    """--cross-groups: config (as config/model.yaml says), none, all, or a comma list of groups."""
    if text == CONFIG:
        return configured
    if text == NONE:
        return ()
    if text == ALL:
        return market_groups(market)
    wanted = tuple(part.strip() for part in text.split(",") if part.strip())
    unknown = [g for g in wanted if g not in market_groups(market)]
    if unknown:
        raise SystemExit(f"unknown cross-market group(s) for {market}: {unknown}; known: {market_groups(market)}")
    return wanted


def ablation_variants(market: str) -> list[tuple[str, tuple[str, ...]]]:
    """all first (the fully reported variant), then none, only <g> and all minus <g> for each group."""
    groups = market_groups(market)
    return [(ALL, groups), (NONE, ()), *((f"only {g}", (g,)) for g in groups),
            *((f"all minus {g}", tuple(x for x in groups if x != g)) for g in groups)]


def beats_all(paper_threshold: dict) -> bool:
    """True when the long has positions and every model-minus-baseline difference has at least
    MIN_VERDICT_DATES common dates and an interval above 0 (a baseline too sparse to compare is not beaten)."""
    diffs = paper_threshold["vs"].values()
    return bool(paper_threshold["long"]["positions"]) and all(
        d["dates"] >= MIN_VERDICT_DATES and d["ci95_pct"][0] is not None and d["ci95_pct"][0] > 0 for d in diffs)


def headline(res: dict) -> dict:
    """The compact numbers of one market x horizon x label result."""
    if "brier" not in res:
        return {"skipped": res.get("skipped")}
    out = {key: res.get(key) for key in ("n", "first_date", "last_date", "up_share", "brier", "brier_base_rate",
                                         "brier_skill", "auc", "auc95")}
    low = (res.get("auc95") or [None])[0]
    scores_ok = (res["brier_skill"] or 0) > 0 and low is not None and low > 0.5
    paper = {}
    for threshold, block in ((res.get("paper") or {}).get("thresholds") or {}).items():
        paper[threshold] = {"positions": block["long"]["positions"], "dates": block["long"]["dates"],
                            "mean_pct": block["long"]["mean_pct"], "ci95_pct": block["long"]["ci95_pct"],
                            "vs": {name: {"mean_pct": d["mean_pct"], "ci95_pct": d["ci95_pct"], "dates": d["dates"]}
                                   for name, d in block["vs"].items()},
                            "beats_every_baseline": beats_all(block)}
    if paper:
        out["paper"] = paper
    out["scores_skill"] = scores_ok
    out["skill"] = scores_ok and any(p["beats_every_baseline"] for p in paper.values())
    return out


def headline_lines(market: str, variant: str, by_spec: dict) -> list[str]:
    """One text line per horizon x label of a variant (by_spec: {key: headline()})."""
    lines = []
    for key, h in sorted(by_spec.items()):
        if "brier" not in h:
            lines.append(f"{market} | {variant} | {key} | skipped")
            continue
        paper = "; ".join(f"p>={t}: {p['positions']} pos, {p['mean_pct']}% {p['ci95_pct']}, vs always_up "
                          f"{p['vs']['always_up']['mean_pct']} {p['vs']['always_up']['ci95_pct']}"
                          for t, p in (h.get("paper") or {}).items())
        lines.append(f"{market} | {variant} | {key} | n {h['n']} | {h['first_date']}..{h['last_date']} | Brier "
                     f"{h['brier']} vs {h['brier_base_rate']} skill {h['brier_skill']} | AUC {h['auc']} {h['auc95']} | "
                     f"scores skill {h['scores_skill']} | skill {h['skill']}" + (f" | {paper}" if paper else ""))
    return lines
