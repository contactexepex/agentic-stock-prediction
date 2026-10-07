"""A trader's input file (docs/SPEC.md F4.1-F4.2): work/traders/<strategy_id>.md, the only file its agent reads.

It holds the run's frame (as-of date, D, the deadline, the exit date of each horizon), one table row per active
company (quality, days to earnings, whether a call is allowed, the as-of close C and the published range of each
horizon; for the combined traders also the model score per horizon), the trader's own track record by confidence
band, and the sections of the context pack (work/context.md) its inputs allow (SECTION_INPUTS: a section whose input
category the trader lacks, or that no category names, is left out; blind traders never get the model score). Sections
past the budget's max_input_kb are cut and listed as cut."""
from __future__ import annotations

import re

from marketbrief.traders import constants as c
from marketbrief.traders import track_record
from marketbrief.traders.inputs import GateInputs
from marketbrief.traders.records import horizon_id
from marketbrief.traders.registry import Trader
from marketbrief.traders.run import automatic_code, run_as_of
from marketbrief.traders.sessions import deadline, entry_session, exit_session

# context-pack section title prefix -> the input category it belongs to (config/strategies.yaml parameters.inputs)
SECTION_INPUTS: tuple[tuple[str, str], ...] = (
    ("Market regime", "regime"),
    ("Overnight cues", "cues"),
    ("Upcoming events", "events"),
    ("Sector ETFs", "sectors"),
    ("Indicators", "indicators"),
    ("Signal model", "model_score"),
    ("News activity", "news"),
    ("News events and verification status", "news"),
    ("Connections: second-order news", "news"),
    ("SEC filings", "filings"),
    ("Company announcements on NSE", "filings"),
    ("Insider and promoter trades", "filings"),
    ("Bulk and block deals", "filings"),
    ("Promoter holding and pledge", "filings"),
    ("Relationship risk flags", "filings"),
    ("Smart money", "filings"),
    ("Latest quarterly results", "results"),
    ("Fundamentals", "results"),
    ("Earnings estimates", "results"),
    ("FII/DII cash-market flows", "cues"),
    ("Macro & flows", "cues"),
    ("Short selling", "indicators"),
    ("Delivery %", "indicators"),
)
SECTION = re.compile(r"^## ", re.M)


def sections(pack: str) -> list[tuple[str, str]]:
    """(title, text) of each `## ` section of the context pack."""
    parts = SECTION.split(pack)
    return [(part.splitlines()[0].strip(), "## " + part.rstrip() + "\n") for part in parts[1:] if part.strip()]


def category(title: str) -> str | None:
    """The input category of a section title, or None (left out for every trader)."""
    return next((name for prefix, name in SECTION_INPUTS if title.startswith(prefix)), None)


def allowed_sections(pack: str, one: Trader, max_bytes: int) -> tuple[list[str], dict]:
    """The sections this trader may read within its byte budget, and what was kept, cut and left out."""
    kept, cut, left_out, used = [], [], [], 0
    for title, text in sections(pack):
        if category(title) not in one.inputs:
            left_out.append(title)
            continue
        size = len(text.encode("utf-8"))
        if used + size > max_bytes:
            cut.append(title)
            continue
        kept.append(text)
        used += size
    return kept, {"kept": len(kept), "cut": cut, "left_out": left_out}


def company_rows(one: Trader, gi: GateInputs) -> list[str]:
    """One table row per active company: the call rule, C and each horizon's published range (and score)."""
    rows = []
    for ticker in sorted(gi.active):
        feats = gi.features.get(ticker)
        code = automatic_code(gi, ticker)
        allowed = "NO CALL: " + code if code else "allowed"
        if feats is None:
            rows.append(f"| {ticker} | - | - | {allowed} | - | no snapshot |")
            continue
        cells = []
        for horizon in one.horizons:
            rid = horizon_id(feats["as_of_date"], ticker, horizon)
            rng, score = gi.ranges.get(rid), gi.scores.get(rid)
            text = (f"N+{horizon} `{rid}` 80% {rng['lo80']}-{rng['hi80']}, 50% {rng['lo50']}-{rng['hi50']}"
                    if rng else f"N+{horizon} no range (no call)")
            if one.sees_model_score:
                text += f", P(up) {score['prob_up']:.4f}" if score else ", no model score"
            cells.append(text)
        close = next((gi.ranges[horizon_id(feats["as_of_date"], ticker, h)]["base_close"] for h in one.horizons
                      if horizon_id(feats["as_of_date"], ticker, h) in gi.ranges), "-")
        rows.append(f"| {ticker} | {feats['quality']} | {feats['days_to_earnings']} | {allowed} | {close} | "
                    + "; ".join(cells) + " |")
    return rows


def frame_lines(one: Trader, gi: GateInputs) -> list[str]:
    """The run's frame: as-of date, D, deadline, exit dates, regime and the ids to cite."""
    as_of = run_as_of(gi)
    session = entry_session(gi.cfg, as_of)
    exits = ", ".join(f"N+{h} = close of {exit_session(gi.cfg, session, h)}" for h in one.horizons)
    regime = gi.regimes.get(as_of, ("unknown", None))[0]
    cite = sorted({c.CITABLE_BY_INPUT[name] for name in one.inputs if name in c.CITABLE_BY_INPUT})
    return [
        f"# Input of {one.strategy_id} ({gi.market})",
        "",
        f"- as_of_date {as_of}; D (entry at the open) {session}; {exits}",
        f"- deadline {deadline(gi.cfg, session).isoformat()} (D's open - {c.DEADLINE_MINUTES} min): "
        "records not through the gate by then are dropped and you abstain for the day",
        f"- regime {regime}; prompt_version `{one.prompt_version}`; threshold {one.threshold}",
        f"- you may cite: {', '.join(cite)} (input ids: `features:{as_of}-<TICKER>`, `regime:{as_of}`"
        + (f", `model_scores:{as_of}-<TICKER>-<k>d`" if one.sees_model_score else "") + ")",
        "",
    ]


def build(one: Trader, gi: GateInputs, pack: str) -> tuple[str, dict]:
    """(the input file's text, a summary of what went in)."""
    max_bytes = int(one.budget["max_input_kb"]) * 1024
    header = frame_lines(one, gi) + [
        "## Companies (C = as-of close; ranges from ranges.py, which you may only widen)", "",
        "| ticker | quality | days_to_earnings | call | C | horizons |", "|---|---|---|---|---|---|",
        *company_rows(one, gi), "",
        "## Your own track record by confidence band (settled paper trades; a CLOSED band refuses that confidence)",
        "", track_record.markdown(gi.track.get(one.strategy_id, {})), "",
    ]
    head = "\n".join(header) + "\n"
    kept, summary = allowed_sections(pack, one, max(0, max_bytes - len(head.encode("utf-8"))))
    if summary["cut"]:
        kept.append("## Cut by the input budget\n\n" + "\n".join(f"- {title}" for title in summary["cut"]) + "\n")
    return head + "\n".join(kept), summary
