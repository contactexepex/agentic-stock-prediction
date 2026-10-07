"""Close results in the day's thread (SPEC F9 (3)): each paper trade settled today, and rule vs AI for the day
(accuracy view per family, head-to-head view per family and pick rule). Every number is a stored
`paper_trades_settled` value or a sum of them; the EOD analyst's gated summary is quoted when it exists."""
from __future__ import annotations

from marketbrief.alerts import text as fmt
from marketbrief.alerts.constants import (
    FAMILY_LABELS,
    LABEL_PAPER_ONLY,
    MSG_FOOTER,
    MSG_NO_SETTLED,
    PAPER,
    PICK_RULE_LABELS,
    STATUS_TEXT,
)

VIEW_ORDER = {"head_to_head": 0, "accuracy": 1}


def tally(rows: list[dict]) -> dict:
    """Trades, wins (net profit > 0) and net profit of settled rows (no_entry and skipped rows are not trades)."""
    done = [r for r in rows if r.get("status") == "settled"]
    return {"trades": len(done), "wins": sum((r.get("net_pnl") or 0) > 0 for r in done),
            "net_pnl": round(sum(r.get("net_pnl") or 0 for r in done), 2)}


def tally_text(t: dict, currency: str) -> str:
    """'3 trades, 2 wins, net +$12.40'."""
    return f"{t['trades']} trade{'s' if t['trades'] != 1 else ''}, {t['wins']} win{'s' if t['wins'] != 1 else ''}, " \
           f"net {fmt.signed_money(currency, t['net_pnl'])}"


def rule_vs_ai_lines(rows: list[dict], currency: str) -> list[str]:
    """Rule vs AI today: the accuracy view per family, the head-to-head view per family and pick rule."""
    acc = [r for r in rows if r.get("view") == "accuracy"]
    h2h = [r for r in rows if r.get("view") == "head_to_head"]
    lines = ["*Rule vs AI today*",
             "Accuracy view: " + "; ".join(
                 f"{FAMILY_LABELS[f]} {tally_text(tally([r for r in acc if r.get('family') == f]), currency)}"
                 for f in ("rule", "ai", "baseline"))]
    if h2h:
        lines.append("Head-to-head: " + "; ".join(
            f"{FAMILY_LABELS[f]}, {PICK_RULE_LABELS[p]}: "
            f"{tally_text(tally([r for r in h2h if r.get('family') == f and r.get('pick_rule') == p]), currency)}"
            for f in ("rule", "ai") for p in ("best_expected_gain", "highest_probability")))
    else:
        lines.append("Head-to-head: no head-to-head trades settled today.")
    return lines


def trade_line(row: dict, names: dict, currency: str) -> str:
    """One settled trade: who, horizon, entry -> exit, net profit, target and range outcome."""
    who = fmt.who(row["strategy_id"], names)
    view = ("head-to-head, " + PICK_RULE_LABELS.get(row.get("pick_rule"), str(row.get("pick_rule")))
            if row.get("view") == "head_to_head" else "accuracy")
    head = f"• *{row['ticker']}* {fmt.horizon(row['horizon_days'])}, {who} ({view})"
    if row.get("status") != "settled":
        return f"{head}: {STATUS_TEXT.get(row.get('status'), row.get('status'))}. {PAPER}"
    target = "target reached" if row.get("target_reached") else "target not reached"
    rng = "closed inside its 80% range" if row.get("range_hit") else "closed outside its 80% range"
    flags = f" Flags: {', '.join(row['flags'])}." if row.get("flags") else ""
    return (f"{head}: bought {fmt.money(currency, row.get('entry_price'))} on {row.get('entry_date')}, sold"
            f" {fmt.money(currency, row.get('exit_price'))} on {row.get('exit_date_actual') or row.get('exit_date')};"
            f" net {fmt.signed_money(currency, row.get('net_pnl'))} ({fmt.pct(row.get('return_pct'))}) after"
            f" {fmt.money(currency, row.get('costs'))} costs; {target}, {rng}; main reason"
            f" {row.get('reason_code') or 'none'}.{flags} {PAPER}")


def build_close(market: str, session_date: str, rows: list[dict], eod: dict | None = None,
                names: dict | None = None, currency: str | None = None) -> str:
    """The close message: rule vs AI, the analyst's note, then each trade settled today (head-to-head first)."""
    names = names or {}
    currency = currency or fmt.MARKET_CURRENCY.get(market, "")
    lines = [f"*{fmt.market_label(market)} — close results for {fmt.day_label(session_date)}*", LABEL_PAPER_ONLY]
    if not rows:
        lines += [MSG_NO_SETTLED, MSG_FOOTER]
        return "\n".join(lines) + "\n"
    lines += rule_vs_ai_lines(rows, currency)
    if eod and eod.get("summary"):
        lines.append(f"Analyst note ({eod.get('id')}): {eod['summary']}")
    lines.append(f"*Settled today ({len(rows)} row{'s' if len(rows) != 1 else ''})*")
    order = sorted(rows, key=lambda r: (VIEW_ORDER.get(r.get("view"), 9), r["ticker"], r["horizon_days"],
                                        r["strategy_id"], str(r.get("pick_rule"))))
    lines += [trade_line(r, names, currency) for r in order]
    lines.append(MSG_FOOTER)
    return "\n".join(lines) + "\n"
