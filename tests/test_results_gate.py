"""Results digests (WS6): the pure gate (marketbrief/results/gate.py) on hand-made releases. SCRATCH TEST DATA."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.results.gate import ReleaseView, check_record  # noqa: E402
from marketbrief.results.sources import TextSource  # noqa: E402

CONF = {
    "max_bullets": 5,
    "quote_max_words": 40,
    "text_max_chars": 300,
    "topics": ["headline_numbers", "guidance", "one_off", "commentary"],
}
TEXT = (
    "Net sales were $95.7 billion, up 11% from $86.2 billion a year ago. “We remain cautious” on the "
    "outlook for fiscal 2027, the CFO said."
)
VIEW = ReleaseView(
    "results",
    {"d1": TextSource("d1", "filing", "ex99.htm", None, "2026-09-24T20:00:00+00:00", TEXT)},
    {"revenue": 9.5723e10, "revenue_yoy_pct": 11.1, "eps_diluted": 6.75, "surprise_pct": 3.2},
    {"2026", "4", "30", "08"},
)


def rec(*bullets, **extra) -> dict:
    return {
        "release_id": "COST-results-2026-09-24",
        "kind": "results",
        "prompt_version": "results-v1",
        "bullets": list(bullets),
        **extra,
    }


def bullet(text, quote="Net sales were $95.7 billion, up 11% from $86.2 billion a year ago.", topic="headline_numbers"):
    return {"topic": topic, "text": text, "quote": quote, "source_id": "d1"}


def errors(record) -> list[str]:
    return check_record(record, {"COST-results-2026-09-24": VIEW}, set(), CONF)[0]


def test_numbers_in_text_come_from_the_quote_or_the_release():
    assert errors(rec(bullet("Net sales were $95.7 billion, up 11%."))) == []
    assert errors(rec(bullet("Revenue grew 11.1% and EPS was 6.75; surprise 3.2%."))) == []
    assert errors(rec(bullet("Net sales of $95,723 million."))) == []  # the release's revenue, restated scale
    assert errors(rec(bullet("Revenue grew 10% year on year.")))  # 10% is neither: trailing zero is no rounding
    assert errors(rec(bullet("EPS was 6.8."))) == []  # 6.75 rounded to the stated 1 decimal
    assert errors(rec(bullet("EPS was 6.9.")))  # outside the stated rounding
    assert errors(rec(bullet("Net sales rose 30%.", quote="the outlook for fiscal 2027, the CFO said.")))
    assert errors(rec(bullet("Results for quarter 4 of 2026."))) == []  # digits of the period labels


def test_quotes_ids_enums_and_limits():
    assert (
        errors(
            rec(
                bullet(
                    "Management remains cautious on the outlook.",
                    quote='"We remain cautious" on the outlook',
                    topic="guidance",
                )
            )
        )
        == []
    )  # typographic quotes normalised
    assert "quote not found verbatim" in errors(rec(bullet("x", quote="We remain very cautious")))[0]
    assert "not a stored text" in errors(rec({**bullet("x"), "source_id": "d9"}))[0]
    assert "must not predict prices" in errors(rec(bullet("Shares will rise after the beat.")))[0]
    assert "topic must be one of" in errors(rec(bullet("x", topic="rating")))[0]
    assert "at most 5" in errors(rec(*[bullet("Net sales were $95.7 billion.")] * 6))[0]
    assert "unknown field 'extra'" in errors(rec(bullet("x"), extra=1))[0]
    assert "prompt_version must match" in errors(rec(bullet("x"), prompt_version="v1"))[0]
    assert "is not a current release" in errors({**rec(bullet("x")), "release_id": "COST-results-2026-06-01"})[0]
    assert errors(rec()) == []  # abstaining is allowed
