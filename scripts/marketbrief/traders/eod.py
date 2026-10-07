"""Storing the EOD analyst's gated output (docs/SPEC.md F6.1): `trade_reasons_ai` rows (one per explained item) and
one `eod_analyses` row per market and session. Every column but the analyst's text and cited ids comes from the facts
(stored data), never from the agent's copy. `add` is all or nothing; `add --valid-only` (after the one retry) stores
the valid reasons and the analysis with its deterministic results, its summary null (withheld) when the summary failed.
A day with no settled trade needs no analyst: its summary is the fixed line "No paper trades settled on <date>."."""
from __future__ import annotations

from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.traders.constants import EOD_PROMPT_VERSION


def reason_rows(good: list[dict], facts: dict, created_at: str) -> list[dict]:
    """trade_reasons_ai rows of the valid reason lines."""
    items = {item["reason_id"]: item for item in facts["items"]}
    rows = []
    for rec in good:
        item = items[rec["id"]]
        rows.append({
            "id": item["reason_id"], "trade_id": item["trade_id"], "settlement_id": item["settlement_id"],
            "market": facts["market"], "ticker": item["ticker"], "strategy_id": item["strategy_id"],
            "session_date": facts["session_date"], "kind": item["kind"], "rank": item["rank"],
            "text": rec["text"].strip(), "cited_ids": list(rec["cited_ids"]),
            "reason_codes": list(item.get("reason_codes") or []), "prompt_version": EOD_PROMPT_VERSION,
            "created_at": created_at,
        })
    return rows


def analysis_row(facts: dict, summary: dict | None, reason_ids: list[str], created_at: str) -> dict:
    """The eod_analyses row (summary null when withheld)."""
    return {
        "id": facts["id"], "market": facts["market"], "session_date": facts["session_date"],
        "settled_trades": facts["settled_trades"], "results": facts["results"],
        "summary": summary["summary"].strip() if summary else
        (f"No paper trades settled on {facts['session_date']}." if facts["settled_trades"] == 0 else None),
        "cited_ids": list(summary["cited_ids"]) if summary else [], "reason_ids": reason_ids,
        "prompt_version": EOD_PROMPT_VERSION, "created_at": created_at,
    }


def store(facts: dict, good: list[dict], summary: dict | None, created_at: str, today) -> dict:
    """Append the reasons and (unless already stored) the analysis; a summary of what was written."""
    reasons = reason_rows(good, facts, created_at)
    market = facts["market"]
    written = {"reasons": 0, "analysis": 0, "files": []}
    if reasons:
        path = day_file(market, "trade_reasons_ai", today)
        written["reasons"] = append_jsonl(path, reasons)
        written["files"].append(str(path))
    if not facts.get("summary_stored"):
        path = day_file(market, "eod_analyses", today)
        written["analysis"] = append_jsonl(path, [analysis_row(facts, summary, [r["id"] for r in reasons],
                                                               created_at)])
        written["files"].append(str(path))
    return written
