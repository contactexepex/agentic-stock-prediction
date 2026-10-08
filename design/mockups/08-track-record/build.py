"""Track record mockup (docs/SPEC.md section 6, page 8): prediction accuracy over time, calibration, scoring bases apart.

    python design/mockups/08-track-record/build.py [--out DIR]

The payload is the catalogue's Track record read model (`track_record.json`, W1's answer to the design track's data
request 5: the dashboard's `rm.track_record`) per market, plus the shell's market status and go-live state. The page
computes nothing but presentation (bars, the "not enough history yet" gate on `min_sample`, the band labels).
Deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "scoreboard_row", "track_record")
REFERENCE_STRATEGY = "rule.model_news.v1"
TRACK_FIELDS = ("market", "as_of", "skill", "calls", "ranges", "replay", "min_sample", "backtest", "example_parts")


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    track = next(r for r in files["track_record"]["records"] if r["market"] == market)
    assert track["as_of"] <= cutoff, (market, track["as_of"], cutoff)
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "track": pick(track, TRACK_FIELDS),
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("track-record", "docs/SPEC.md section 6, page 8; decision 17", "GET /api/v1/markets/{market}/track-record",
                    "rm.track_record", NAMES, cutoff, markets)
    data["_data_requests"] = [
        "a weekly series of hit rate and Brier per scoring basis (accuracy over time): not in rm.track_record; the "
        "catalogue says it is a request to the read model's owner (B4). The page shows the 'over time' card as an "
        "empty state until then",
    ]
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"calls bases {[c['key'] for c in p['track']['calls']]}, "
                                  f"n {[c['all']['n'] for c in p['track']['calls']]}, ranges {len(p['track']['ranges'])}, "
                                  f"replay {'yes' if p['track']['replay'] else 'none'}, skill {p['track']['skill']['state']}, "
                                  f"backtest scores {len(p['track']['backtest']['scores'])}")
