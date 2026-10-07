"""Evidence for the corrected expected gain (docs/ws/b2.md): which horizon "best expected gain" picks under the
spec's draft formula (move = target / C - 1, loss = 1 - lo80 / C) and under the corrected one (lab/picks.py).

- example_spread: W1's example predictions (design/catalogue/prediction.json), every rule and AI strategy with at
  least one qualifying horizon per company;
- history_spread: a back-test sample on stored bars: per ticker and each of the last `days` as-of rows whose N+5 exit
  is stored, per horizon
  N+k, a no-look-ahead base-rate forecast from the previous `window` rows whose exit had closed by then: p = the
  share of rising N+k trades (open of D to the k-th close after D), target = C x (1 + their mean return), 80% band
  = C x (1 + their 10% and 90% quantiles); horizons with p >= `threshold` are the candidates."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from marketbrief.lab.constants import PERCENT, PICK_GAIN
from marketbrief.lab.picks import candidate, pick


def draft_gain(pred: dict, cost: float) -> float:
    """The spec draft: p x (target / C - 1) - (1 - p) x (1 - lo80 / C) - costs, in %."""
    close, prob = float(pred["base_close"]), float(pred["prob_up"])
    move, loss = (pred["target_price"] / close - 1) * PERCENT, (1 - pred["lo80"] / close) * PERCENT
    return prob * move - (1 - prob) * loss - cost


def spread(groups: list[list[dict]], market_of, rates: dict, eurusd: float) -> dict:
    """Picked-horizon counts per rule: corrected = lab/picks.py (gain per session held), per_trade = the corrected
    gain ranked per trade, draft = the spec's draft; plus how many candidates and corrected picks have a positive
    expected gain, and how many draft picks do."""
    corrected, per_trade, draft = Counter(), Counter(), Counter()
    counts = {"candidates": 0, "candidates_positive": 0, "corrected_best_positive": 0, "draft_best_positive": 0}
    for preds in groups:
        market = market_of(preds[0])
        pairs = [(p, c) for p in preds if (c := candidate(p, market, rates[market], eurusd)) is not None]
        if not pairs:
            continue
        cands = [c for _, c in pairs]
        chosen = pick(cands, PICK_GAIN)
        corrected[chosen["horizon_days"]] += 1
        per_trade[max(cands, key=lambda c: (c["expected_gain_pct"], -c["horizon_days"]))["horizon_days"]] += 1
        best = max((draft_gain(p, c["costs_pct"]), -int(p["horizon_days"]), int(p["horizon_days"])) for p, c in pairs)
        draft[best[2]] += 1
        counts["candidates"] += len(cands)
        counts["candidates_positive"] += sum(c["expected_gain_pct"] > 0 for c in cands)
        counts["corrected_best_positive"] += chosen["expected_gain_pct"] > 0
        counts["draft_best_positive"] += best[0] > 0
    return {"groups": sum(corrected.values()), "corrected": dict(sorted(corrected.items())),
            "per_trade": dict(sorted(per_trade.items())), "draft": dict(sorted(draft.items())),
            **{key: int(value) for key, value in counts.items()}}


def example_spread(path: Path, rates: dict, eurusd: float) -> dict:
    """The spread on W1's example predictions (per company, strategy and as-of day)."""
    records = json.loads(path.read_text(encoding="utf-8"))["records"]
    groups: dict[tuple, list[dict]] = {}
    for pred in records:
        if pred["family"] in ("rule", "ai") and pred["qualifies"] and pred["prob_up"] is not None:
            groups.setdefault((pred["strategy_id"], pred["ticker"], pred["as_of_date"]), []).append(pred)
    return spread([groups[key] for key in sorted(groups)], lambda p: p["market"], rates, eurusd)


def base_rate_predictions(ticker: str, bars: pd.DataFrame, horizons: tuple[int, ...], settings: dict) -> list[list]:
    """Per as-of row of the sample, the base-rate predictions of each horizon with p >= threshold. The sample is
    the last `days` as-of rows whose longest exit is stored (D and the exit dates are the bars' own sessions)."""
    bars = bars.dropna(subset=["open", "close"]).sort_index()
    opens, closes = bars["open"].to_numpy(dtype=float), bars["close"].to_numpy(dtype=float)
    dates = [str(day.date()) for day in bars.index]
    window, last = settings["window"], len(bars) - 1 - max(horizons)
    groups = []
    for t in range(max(last - settings["days"], window + max(horizons) + 2), last):
        preds = []
        for k in horizons:
            starts = np.arange(t - window, t - k)          # as-of rows whose N+k exit (row s + 1 + k) <= t
            returns = closes[starts + 1 + k] / opens[starts + 1] - 1
            prob = float((returns > 0).mean())
            if prob < settings["threshold"]:
                continue
            close = closes[t]
            preds.append({"id": f"{ticker}-{t}-{k}", "horizon_days": k, "prob_up": prob, "base_close": close,
                          "market": settings["market"], "session_date": dates[t + 1], "exit_date": dates[t + 1 + k],
                          "target_price": close * (1 + returns.mean()), "lo80": close * (1 + np.quantile(returns, 0.1)),
                          "hi80": close * (1 + np.quantile(returns, 0.9)), "amount": settings["amount"]})
        if preds:
            groups.append(preds)
    return groups


def history_spread(market: str, bars: dict[str, pd.DataFrame], horizons: tuple[int, ...], rates: dict,
                   settings: dict) -> dict:
    """The spread on the stored-bar sample of one market. settings: days, window, threshold, amount, eurusd."""
    groups = []
    for ticker in sorted(bars):
        groups += base_rate_predictions(ticker, bars[ticker], horizons, {**settings, "market": market})
    if not groups:
        return {"groups": 0}
    return spread(groups, lambda _: market, rates, settings["eurusd"])

