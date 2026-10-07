"""The weekly research report (docs/SPEC.md F6.2): reports/<market>/research-<iso_week>.md, assembled from the
deterministic leaders and the director's gated findings and proposals, and its `research_reviews` row. Every proposal
is stored with status `proposed`: the owner approves a diff by applying it (a judged config change); nothing here
applies one."""
from __future__ import annotations

from pathlib import Path

from marketbrief.core import paths
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.traders.constants import DIRECTOR_PROMPT_VERSION, PROPOSAL_STATUS

DISCLAIMER = ("_Research only, not investment advice. Paper trades are records, never orders. Proposals change "
              "nothing until the owner applies them._")


def leader_table(rows: list[dict]) -> list[str]:
    """A markdown table of leaders (family, strategy, trades, wins, net P&L, return %)."""
    if not rows:
        return ["No settled accuracy-view trades.", ""]
    out = ["| family | strategy | trades | wins | net P&L | return % |", "|---|---|---|---|---|---|"]
    out += [f"| {r['family']} | {r['strategy_id']} | {r['trades']} | {r['wins']} | {r['net_pnl']} | {r['return_pct']} |"
            for r in rows]
    return [*out, ""]


def leaders(facts: dict) -> list[dict]:
    """The leader per family to date: {scope, strategy_id, net_pnl, trades}."""
    best: dict[str, dict] = {}
    for row in facts["leaders_to_date"]:
        best.setdefault(row["family"], row)   # rows come ordered by family, then net P&L descending
    return [{"scope": family, "strategy_id": row["strategy_id"], "net_pnl": row["net_pnl"], "trades": row["trades"]}
            for family, row in sorted(best.items())]


def markdown(facts: dict, review: dict) -> str:
    """The report text."""
    lines = [f"# Research review {facts['market']} {facts['iso_week']} ({facts['period_start']} to "
             f"{facts['period_end']})", "", DISCLAIMER, "", "## Leaders to date (accuracy view, after costs)", "",
             *leader_table(facts["leaders_to_date"]), "## This week", "", *leader_table(facts["leaders_week"]),
             "## Findings", ""]
    lines += [f"- {f['text']} ({', '.join(f['cited_ids'])})" for f in review["findings"]] or ["- none"]
    lines += ["", "## Proposals (status: proposed; each is a diff for the owner to approve)", ""]
    if not review["proposals"]:
        lines.append("None this week.")
    for proposal in review["proposals"]:
        lines += [f"### {proposal['proposal_id']} ({proposal['kind']}, `{proposal['file']}`)", "",
                  f"{proposal['rationale']} ({', '.join(proposal['cited_ids'])})", "", "```diff",
                  proposal["diff"].rstrip("\n"), "```", ""]
    return "\n".join(lines).rstrip() + "\n"


def store(facts: dict, review: dict, written_at: str, today) -> dict:
    """Write the report and append the research_reviews row (refused when the week's row is stored)."""
    market, week = facts["market"], facts["iso_week"]
    report = Path("reports") / market / f"research-{week}.md"
    target = paths.ROOT / report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown(facts, review), encoding="utf-8")
    proposals = [{**{k: p[k] for k in ("proposal_id", "kind", "file", "diff", "rationale", "cited_ids")},
                  "status": PROPOSAL_STATUS} for p in review["proposals"]]
    row = {"id": facts["id"], "market": market, "iso_week": week, "period_start": facts["period_start"],
           "period_end": facts["period_end"], "leaders": leaders(facts),
           "findings": [{"text": f["text"], "cited_ids": f["cited_ids"]} for f in review["findings"]],
           "proposals": proposals, "report_path": report.as_posix(), "prompt_version": DIRECTOR_PROMPT_VERSION,
           "written_at": written_at}
    path = day_file(market, "research_reviews", today)
    append_jsonl(path, [row])
    return {"report": str(target), "to": str(path), "proposals": len(proposals), "findings": len(row["findings"])}
