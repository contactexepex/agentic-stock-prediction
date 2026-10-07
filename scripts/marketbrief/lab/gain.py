"""The expected rise and shortfall of a prediction from its own 80% range (B2's corrected F1.7.3, docs/ws/b2.md):
the exit close X is read as normal with mean = the target and sigma = (hi80 - lo80) / (2 x 1.2816); in % of the
reference price C, move = E[X / C - 1 | X > C] and loss = E[1 - X / C | X < C]. Used by the head-to-head picks
(lab/picks.py) and the cost-viable flag (lab/cost_views.py), so the two always agree."""
from __future__ import annotations

import math

from marketbrief.lab.constants import PERCENT, Z80


def normal_pdf(z: float) -> float:
    """Standard normal density."""
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def normal_cdf(z: float) -> float:
    """Standard normal distribution function."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def conditional_move_loss(close: float, target: float, lo80: float, hi80: float) -> tuple[float, float]:
    """(move, loss) in % of C: E[X/C - 1 | X > C] and E[1 - X/C | X < C] for X ~ N(target, sigma)."""
    sigma = (float(hi80) - float(lo80)) / (2 * Z80)
    if sigma <= 0:
        gap = (float(target) / close - 1) * PERCENT
        return max(gap, 0.0), max(-gap, 0.0)
    z = (close - float(target)) / sigma
    above, below = 1 - normal_cdf(z), normal_cdf(z)
    upside = (float(target) - close) * above + sigma * normal_pdf(z)     # E[(X - C)+]
    downside = (close - float(target)) * below + sigma * normal_pdf(z)   # E[(C - X)+]
    move = upside / above / close * PERCENT if above > 0 else 0.0
    loss = downside / below / close * PERCENT if below > 0 else 0.0
    return move, loss


def expected_gain_pct(prob: float, move: float, loss: float, cost_pct: float) -> float:
    """p x move - (1 - p) x loss - cost, in %."""
    return prob * move - (1 - prob) * loss - cost_pct
