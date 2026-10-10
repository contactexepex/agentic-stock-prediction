"""The weekly report as its own post (SPEC F9 (4)): the research director's stored review (`research_reviews`,
F6.2): leaders per family, findings with their ids, and proposals, each waiting for the owner's approval."""
from __future__ import annotations

from marketbrief.alerts import text as fmt
from marketbrief.alerts.constants import FAMILY_LABELS, LABEL_PAPER_ONLY, MSG_FOOTER


def build_weekly(market: str, review: dict, names: dict | None = None, currency: str | None = None,
                 links: dict | None = None) -> str:
    """The weekly post of one stored research review. `links`: `repo` (the repo's blob base, e.g.
    https://github.com/o/r/blob/main) for the report file, `app` (config/settings.yaml slack_link_url) for the
    market page."""
    links = links or {}
    names = names or {}
    currency = currency or fmt.MARKET_CURRENCY.get(market, "")
    lines = [f"*{fmt.market_label(market)} — weekly research report {review['iso_week']}*"
             f" ({review.get('period_start')} to {review.get('period_end')})", LABEL_PAPER_ONLY, "*Who leads*"]
    for lead in review.get("leaders") or []:
        sid = lead.get("strategy_id")
        lines.append(f"• {FAMILY_LABELS.get(lead.get('scope'), lead.get('scope'))}: {fmt.who(sid, names)},"
                     f" net {fmt.signed_money(currency, lead.get('net_pnl'))} on {lead.get('trades')} paper trades")
    if not review.get("leaders"):
        lines.append("• No leaders yet.")
    lines.append("*Findings*")
    for finding in review.get("findings") or []:
        cited = ", ".join(finding.get("cited_ids") or [])
        lines.append(f"• {finding.get('text')}" + (f" [{cited}]" if cited else ""))
    if not review.get("findings"):
        lines.append("• No findings this week.")
    lines.append("*Proposals (nothing changes until the owner approves)*")
    for prop in review.get("proposals") or []:
        lines.append(f"• {prop.get('proposal_id')} ({prop.get('kind')}, {prop.get('file')}, {prop.get('status')}):"
                     f" {prop.get('rationale')}")
    if not review.get("proposals"):
        lines.append("• No proposals this week.")
    if review.get("report_path"):
        repo, path = links.get("repo"), review["report_path"]
        lines.append(f"Full report: {repo.rstrip('/') + '/' + path if repo else path}")
    if links.get("app"):
        lines.append(f"Market page: {links['app'].rstrip('/')}/{market}")
    lines.append(MSG_FOOTER)
    return "\n".join(lines) + "\n"
