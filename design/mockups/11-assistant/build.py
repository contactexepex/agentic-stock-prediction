"""Assistant mockup (docs/SPEC.md section 6, page 11; F11): the chat with sources and as-of times.

    python design/mockups/11-assistant/build.py [--out DIR]

The payload is the catalogue's Assistant answer entity (`assistant_answer.json`, W1's answer to the design track's
data request 6: the `explain` tool's output `answer` with `text`, `cited_ids`, `as_of`, `not_in_data`, plus the
proposed `cited` and `declined`) per market, asked at or before the cut-off, oldest first, plus the shell's market
status and go-live state. The page computes nothing but presentation. Deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "scoreboard_row", "assistant_answer")
REFERENCE_STRATEGY = "rule.model_news.v1"
ANSWER_FIELDS = ("id", "market", "channel", "asked_at", "question", "text", "cited_ids", "cited", "as_of", "not_in_data",
                 "declined")
CITED_FIELDS = ("id", "kind", "as_of")


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    answers = []
    # An answer is a record written when the question was asked: it is shown only when `asked_at` is at or before
    # the cut-off (the record's write time, as every page of the track filters), and the data it read (`as_of`) is
    # at or before `asked_at`. The catalogue's example answers are all asked 10-25 minutes after the noon cut-off,
    # so the example payload holds none (judge round 1); answers asked before the cut-off are requested from W1.
    for r in sorted((r for r in files["assistant_answer"]["records"] if r["market"] == market), key=lambda r: r["asked_at"]):
        if r["asked_at"] > cutoff:
            continue
        rec = pick(r, ANSWER_FIELDS)
        rec["cited"] = [pick(c, CITED_FIELDS) for c in r["cited"]]
        assert rec["as_of"] <= rec["asked_at"], (rec["id"], rec["as_of"], rec["asked_at"])
        for c in rec["cited"]:
            assert c["as_of"] <= rec["as_of"], (rec["id"], c)
        answers.append(rec)
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "answers": answers,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("assistant", "docs/SPEC.md section 6, page 11; F11; F10 explain tool", "POST /api/assistant (the explain tool)",
                    "(none: conversations are an operational log in MotherDuck schema app, kept 90 days)", NAMES, cutoff, markets)
    data["_data_requests"] = [
        "example answers asked at or before the catalogue's as_of (asked_at <= 2026-10-07T12:00:00Z) with as_of at or "
        "before asked_at and every cited record stored by then: the stored examples are asked 12:10-12:25Z, after the "
        "cut-off, so a page at the cut-off's clock shows none of them (judge round 1); the page shows its empty state "
        "and generic starter questions until then",
        "the assistant's budget state (today's spend against the daily budget and the month's against the cap, F11) "
        "so the panel can say when it is over budget: not in the catalogue; the page shows the caps as spec constants "
        "and says the spend is not stored in the example data",
    ]
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"answers {len(p['answers'])}, not_in_data {sum(1 for a in p['answers'] if a['not_in_data'])}, "
                                  f"declined {sum(1 for a in p['answers'] if a['declined'])}, "
                                  f"cited {sum(len(a['cited']) for a in p['answers'])}")
