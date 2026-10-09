"""The EOD analyst's gate (docs/SPEC.md F6.1; like scripts/lessons.py validate): ids, numbers, enums, no advice.

The analyst writes work/eod_analysis.jsonl: one line per item of the facts
`{"id": "<reason_id>", "trade_id", "kind", "text", "cited_ids", "prompt_version"}` and one summary line
`{"type": "summary", "summary", "cited_ids", "prompt_version"}`. Checks:
- every item of the facts is explained exactly once with its own id and kind, and nothing else;
- a reason is 1-60 words, the summary 1-150 (one summary line, none when the facts say summary_stored);
  prompt_version is eod-v2;
- cited_ids of a reason: the trade id first, then only the trade's verified news ids; of the summary: ids of the
  day's items (trade ids, reason ids) and their news ids; every id written in a text is cited;
- every number in a reason is one of its trade's stored facts (numbers.py; signed percentages with the right
  sign); in the summary, one of the day's results or of an item's facts;
- no advice and no forecast (constants.ADVICE_WORDS)."""
from __future__ import annotations

from marketbrief.traders import constants as c
from marketbrief.traders import numbers

PCT_KEYS = ("return_pct", "target_error_pct", "max_favourable_pct", "max_adverse_pct", "move_pct", "market_pct",
            "sector_pct", "news_pct", "company_pct", "prob_up_pct")
PLAIN_KEYS = ("amount", "entry_price", "exit_price", "quantity", "gross_pnl", "costs", "net_pnl", "prob_up",
              "target_price", "lo80", "hi80", "horizon_days", "target_reached_session", "rank")


def item_facts(item: dict) -> list[tuple[float, bool, str]]:
    """The numbers a reason about this item may write."""
    enriched = {**item, "prob_up_pct": item["prob_up"] * 100 if item.get("prob_up") is not None else None}
    return numbers.facts_of(enriched, PCT_KEYS, PLAIN_KEYS)


def result_facts(facts: dict) -> list[tuple[float, bool, str]]:
    """The numbers the summary may write: the results, the counts, and every item's facts."""
    out = [(float(facts["settled_trades"]), False, "settled_trades"), (float(c.BIGGEST_COUNT), False, "count"),
           (float(len(facts["items"])), False, "items")]
    for name, cell in facts["results"].items():
        out += [(float(cell["return_pct"]), True, f"{name}.return_pct")]
        out += [(float(cell[key]), False, f"{name}.{key}") for key in ("trades", "wins", "net_pnl", "return_pct")]
    for item in facts["items"]:
        out += item_facts(item)
    return out


def text_problems(text, words: int, facts: list, extra: list[str], cited: list[str]) -> list[str]:
    """Word count, advice, ids written but not cited, numbers matching no fact."""
    count = len(text.split()) if isinstance(text, str) else 0
    if not 1 <= count <= words:
        return [c.MSG_EOD_WORDS.format(what="text", words=words, count=count)]
    out = []
    advice = c.ADVICE_WORDS.search(text)
    if advice:
        out.append(c.MSG_EOD_ADVICE.format(word=advice.group(0)))
    written = [token for token in c.ID_TOKEN.findall(text) if token.rstrip(".,;") not in cited]
    if written:
        out.append(c.MSG_EOD_TEXT_ID.format(ids=written))
    unmatched = numbers.problems(text, facts, extra + cited)
    if unmatched:
        out.append(c.MSG_EOD_NUMBER.format(numbers=unmatched))
    return out


def reason_problems(rec: dict, item: dict | None, seen: set[str]) -> list[str]:
    """One reason line against its item."""
    out = [c.MSG_UNKNOWN_FIELD.format(field=k) for k in rec if k not in c.EOD_REASON_FIELDS]
    if item is None:
        return out + [c.MSG_EOD_UNKNOWN_TRADE.format(trade_id=rec.get("trade_id"), kind=rec.get("kind"))]
    if rec.get("kind") not in (c.KIND_HEAD_TO_HEAD, c.KIND_WIN, c.KIND_MISS):
        out.append(c.MSG_EOD_ENUM.format(field="kind", value=rec.get("kind"),
                                         allowed=[c.KIND_HEAD_TO_HEAD, c.KIND_WIN, c.KIND_MISS]))
    if rec.get("id") != item["reason_id"]:
        out.append(c.MSG_EOD_ID.format(got=rec.get("id"), want=item["reason_id"]))
    if item["reason_id"] in seen:
        out.append(c.MSG_EOD_TWICE.format(trade_id=item["trade_id"], kind=item["kind"]))
    seen.add(item["reason_id"])
    if rec.get("prompt_version") != c.EOD_PROMPT_VERSION:
        out.append(c.MSG_EOD_PROMPT.format(want=c.EOD_PROMPT_VERSION))
    cited = rec.get("cited_ids")
    if not isinstance(cited, list) or not cited or cited[0] != item["trade_id"]:
        return out + [c.MSG_EOD_CITE_TRADE.format(trade_id=item["trade_id"])]
    unknown = [i for i in cited[1:] if i not in (item.get("news_ids") or [])]
    if unknown:
        out.append(c.MSG_EOD_CITE_UNKNOWN.format(ids=unknown))
    extra = [item["ticker"], item["settlement_id"], item["reason_id"], item["strategy_id"], *(item.get("flags") or [])]
    return out + text_problems(rec.get("text"), c.REASON_WORDS, item_facts(item), extra, cited)


def summary_problems(rec: dict, facts: dict) -> list[str]:
    """The summary line against the day's results and items."""
    out = [c.MSG_UNKNOWN_FIELD.format(field=k) for k in rec if k not in c.EOD_SUMMARY_FIELDS]
    if rec.get("prompt_version") != c.EOD_PROMPT_VERSION:
        out.append(c.MSG_EOD_PROMPT.format(want=c.EOD_PROMPT_VERSION))
    known = set()
    for item in facts["items"]:
        known |= {item["trade_id"], item["reason_id"], *(item.get("news_ids") or [])}
    cited = rec.get("cited_ids")
    if not isinstance(cited, list):
        return out + [c.MSG_EOD_CITE_UNKNOWN.format(ids=cited)]
    unknown = [i for i in cited if i not in known]
    if unknown:
        out.append(c.MSG_EOD_CITE_UNKNOWN.format(ids=unknown))
    extra = [item["ticker"] for item in facts["items"]] + [item["strategy_id"] for item in facts["items"]]
    return out + text_problems(rec.get("summary"), c.EOD_SUMMARY_WORDS, result_facts(facts), extra, cited)


def validate(lines: list, facts: dict) -> tuple[list[dict], dict | None, list[dict]]:
    """(valid reason lines, the valid summary line or None, errors [{line, id, errors}])."""
    by_key = {(item["trade_id"], item["kind"]): item for item in facts["items"]}
    good, summary, errors, seen = [], None, [], set()
    summaries = [rec for rec in lines if isinstance(rec, dict) and rec.get("type") == c.TYPE_SUMMARY]
    if facts.get("summary_stored") and summaries:
        errors.append({"line": None, "id": "summary",
                       "errors": [c.MSG_EOD_SUMMARY_STORED.format(count=len(summaries))]})
    elif not facts.get("summary_stored") and (len(summaries) > 1 or (facts["settled_trades"] > 0 and not summaries)):
        errors.append({"line": None, "id": "summary", "errors": [c.MSG_EOD_SUMMARY.format(count=len(summaries))]})
    for number, rec in enumerate(lines, 1):
        if not isinstance(rec, dict):
            errors.append({"line": number, "id": None, "errors": ["not a JSON object"]})
            continue
        if rec.get("type") == c.TYPE_SUMMARY:
            found = summary_problems(rec, facts)
            summary = None if found else rec
        else:
            found = reason_problems(rec, by_key.get((rec.get("trade_id"), rec.get("kind"))), seen)
            if not found:
                good.append(rec)
        if found:
            errors.append({"line": number, "id": rec.get("id", rec.get("type")), "errors": found})
    for item in facts["items"]:
        if item["reason_id"] not in seen:
            errors.append({"line": None, "id": item["reason_id"],
                           "errors": [c.MSG_EOD_MISSING.format(trade_id=item["trade_id"], kind=item["kind"])]})
    return good, summary, errors
