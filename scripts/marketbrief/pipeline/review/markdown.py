"""The weekly review's markdown report, assembled from its sections."""

from __future__ import annotations

from marketbrief.core.market_config import load_ranges_config
from marketbrief.pipeline.review.markdown_sections import (
    call_lines,
    header_lines,
    range_lines,
    score_lines,
    window_names,
)
from marketbrief.pipeline.review.markdown_sections_scores import (
    ablation_lines,
    aci_lines,
    calibration_lines,
    method_lines,
    proposal_lines,
)


def markdown(cfg: dict, review_config: dict, rec: dict, review_data: dict) -> str:
    """The weekly review as markdown."""
    by_horizon = " / ".join(f"{horizon}d" for horizon in load_ranges_config(cfg["market"])["horizons"])
    win_names = window_names(rec, review_config)
    lines = header_lines(cfg, rec, review_config, review_data, win_names)
    lines += range_lines(review_config, review_data, win_names)
    lines += call_lines(review_config, review_data, win_names)
    lines += score_lines(review_config, review_data, win_names)
    lines += aci_lines(review_data)
    lines += calibration_lines(rec, review_data)
    lines += ablation_lines(rec, review_data, by_horizon)
    lines += proposal_lines(review_config, review_data, by_horizon)
    lines += method_lines(review_config)
    return "\n".join(lines)
