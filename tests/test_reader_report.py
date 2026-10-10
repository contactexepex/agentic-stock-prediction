"""The reader's daily report (C2, presentation/reader/): the lean and plain-language "why" built from a stored
model score, the flags, the 20-second glance and "what changed" summaries, and the page's self-contained assets."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.constants import reader as text  # noqa: E402
from marketbrief.presentation.reader import gather, page, why  # noqa: E402


def score(prob, groups, base=0.48, items=None):
    return {"prob_up": prob, "base_rate": base,
            "contributions": {"groups": groups, "news": {"items": items, "ids": []}}}


def test_lean_thresholds():
    assert why.lean(None) == ("none", "none")
    assert why.lean(0.5) == why.lean(0.519) == why.lean(0.481) == ("none", "none")
    assert why.lean(0.52) == ("up", "slight") and why.lean(0.48) == ("down", "slight")
    assert why.lean(0.55) == ("up", "clear") and why.lean(0.4499) == ("down", "clear")


def test_why_line_names_the_strongest_reason_each_way():
    s = score(0.56, {"baseline": -0.1, "news": 1.4, "regime": -0.09, "volume": 0.01}, items=27)
    assert why.why_line(s) == ("Leans up mainly because recent verified news is positive (27 items); "
                               "on the other side, the market mood tilts it down.")
    one = score(0.47, {"baseline": -0.2, "momentum": -0.3}, items=1)
    assert why.why_line(one) == "Leans slightly down mainly because the recent price trend points down."


def test_why_line_baseline_and_no_signal():
    # the usual odds (the model's baseline) push the lean more than any signal: say so
    s = score(0.47, {"baseline": -0.45, "news": -0.2}, base=0.4756, items=6)
    assert why.why_line(s) == ("Leans slightly down, mostly from the usual odds (in the past 48% of such cases went "
                               "up); also recent verified news is negative (6 items).")
    flat = score(0.49, {"baseline": -0.45, "news": 0.0}, base=0.4756)
    assert why.why_line(flat) == "No strong signal: the model stays close to the usual odds (48% of past cases went up)."
    assert why.why_line(None) == why.why_line({"prob_up": None}) == text.WHY_NO_SCORE
    unknown = score(0.6, {"cross market": 0.3})
    assert why.why_line(unknown) == "Leans up mainly because the cross market signals point up."


def test_flags():
    assert why.flags("OK", None, False) == []
    assert why.flags("OK", 9, False) == []
    assert [f["text"] for f in why.flags("BLOCKED", 3, True)] == [
        "Results in 3 days: prices can jump", "Data problem: no forecast is trusted today",
        "Some recent news was contradicted by other sources"]
    assert why.flags("OK", 1, False)[0]["text"] == text.EARNINGS_TODAY


def card(ticker, rows):
    return {"ticker": ticker, "forecasts": [
        {"h": h, "prob_up": p, "lean": why.lean(p)[0], "move_pct": m, "change": c} for h, p, m, c in rows]}


def test_glance_counts_and_biggest_moves():
    cards = [card("A", [(1, 0.6, 1.5, None)]), card("B", [(1, 0.4, -2.0, None)]), card("C", [(1, 0.5, 0.0, None)]),
             card("D", [(1, None, 0.7, None)]), card("E", [])]
    g = gather.glance(cards)["1"]
    assert (g["up"], g["down"], g["none"], g["no_score"]) == (1, 1, 1, 2)
    assert g["moves"] == ["B", "A", "D"]                 # by size of the move; a 0% move is never listed
    assert gather.glance(cards)["3"]["no_score"] == 5


class Statuses:
    def of(self, nid, ticker, when):
        return "corroborated" if nid == "n1" else "unverified"


def test_changes_lists_big_moves_and_newly_counted_news():
    big = {"since": "2026-10-08T02:26:06Z", "target_pct": -4.06, "prob_pts": -0.0337, "news_added": ["n1", "n2"]}
    small = {"since": "2026-10-08T02:26:06Z", "target_pct": 0.1, "prob_pts": 0.001, "news_added": ["n1"]}
    prob_only = {"since": "2026-10-08T02:26:06Z", "target_pct": 0.0, "prob_pts": 0.025, "news_added": []}
    cards = [card("ITC", [(1, 0.44, -0.1, big), (3, 0.43, 0.0, big)]), card("TCS", [(1, 0.46, 0.1, small)]),
             card("INFY", [(1, 0.5, 0.2, prob_only)])]
    sources = {"n1": {"title": "One", "url": "https://x.example/1", "source": "Reuters", "ts": "2026-10-08T10:00:00+00:00"},
               "n2": {"title": "Two", "url": None, "source": "Mint", "ts": "2026-10-08T11:00:00+00:00"}}
    out = gather.changes(cards, sources, Statuses(), datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert [r["ticker"] for r in out["by_horizon"]["1"]] == ["ITC", "INFY"]   # TCS's moves are too small
    assert out["since"] == "2026-10-08T02:26:06Z"
    assert [(n["ticker"], n["id"], n["status"]) for n in out["news"]] == [
        ("ITC", "n2", "unverified"), ("ITC", "n1", "corroborated"), ("TCS", "n1", "corroborated")]   # newest first
    assert out["news_total"] == 3


def test_page_assets_are_self_contained_and_use_the_design_tokens():
    css, js = page.css(), page.script()
    assert css.startswith(page.tokens_css()) and "--mb-color-up" in css
    assert not re.search(r"url\(\s*['\"]?(?:https?:)?//", css)
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)[\w.]", js)   # no URL in the script but the SVG namespace
    assert not re.search(r"\b(?:fetch|XMLHttpRequest|import\()", js)
    sprite = page.icons_sprite()
    assert sprite.count("<symbol") == len(page.ICONS) and 'display:none' in sprite
    # the page's colours are token names only: every hex colour in reader.css sits in the dark-mode token set
    own = (page.ASSETS / "reader.css").read_text()
    body = own.split(':root[data-theme="dark"]{', 1)[1].split("}", 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", body)
    out = page.render("T <x>", '{"a": 1}', {"s": "</script><b>"})
    assert "<title>T &lt;x&gt;</title>" in out and "<\\/script>" in out and "__JS__" not in out
