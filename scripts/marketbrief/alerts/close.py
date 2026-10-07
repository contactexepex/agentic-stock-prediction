"""Close results in the day's thread (SPEC F9 (3)): rule vs AI for the day over every row settled today (accuracy
view per family, head-to-head view per family and pick rule), then every head-to-head trade and the 10 biggest wins
and 10 biggest losses of the other rows, with the count of the rest (owner, 2026-10-07). Every number is a stored
`paper_trades_settled` value or a sum of them; the EOD analyst's gated summary is quoted when it exists."""
from __future__ import annotations

from marketbrief.alerts import costs
from marketbrief.alerts import text as fmt
from marketbrief.alerts.constants import (
    CLOSE_TOP_LOSSES,
    CLOSE_TOP_WINS,
    FAMILY_LABELS,
    LABEL_PAPER_ONLY,
    MSG_FOOTER,
    MSG_MORE_ON_DASHBOARD,
    MSG_NO_SETTLED,
    PAPER,
    PICK_RULE_LABELS,
    STATUS_TEXT,
)

def tally(rows: list[dict]) -> dict:
    """Trades, wins (net profit > 0) and net profit of settled rows (no_entry and skipped rows are not trades)."""
    done = [r for r in rows if r.get("status") == "settled"]
    return {"trades": len(done), "wins": sum((r.get("net_pnl") or 0) > 0 for r in done),
            "net_pnl": round(sum(r.get("net_pnl") or 0 for r in done), 2), "your_net_pnl": costs.your_net_total(done)}


def tally_text(t: dict, currency: str) -> str:
    """'3 trades, 2 wins, net +$12.40' (plus ' (after your costs +$9.10)' when the rows have the owner's costs)."""
    yours = (f" (after your costs {fmt.signed_money(currency, t['your_net_pnl'])})"
             if t.get("your_net_pnl") is not None else "")
    return (f"{t['trades']} trade{'s' if t['trades'] != 1 else ''}, {t['wins']} win{'s' if t['wins'] != 1 else ''}, "
            f"net {fmt.signed_money(currency, t['net_pnl'])}{yours}")


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


def key(row: dict) -> tuple:
    """A stable order: ticker, horizon, strategy, pick rule."""
    return row["ticker"], row["horizon_days"], row["strategy_id"], str(row.get("pick_rule"))


def listed_rows(rows: list[dict]) -> list[dict]:
    """The rows the message lists: every head-to-head row, then the biggest wins (net profit > 0, largest first)
    and the biggest losses (net profit < 0, largest loss first) of the other settled rows."""
    h2h = sorted((r for r in rows if r.get("view") == "head_to_head"), key=key)
    other = [r for r in rows if r.get("view") != "head_to_head" and r.get("status") == "settled"]
    wins = sorted((r for r in other if (r.get("net_pnl") or 0) > 0), key=lambda r: (-r["net_pnl"], key(r)))
    losses = sorted((r for r in other if (r.get("net_pnl") or 0) < 0), key=lambda r: (r["net_pnl"], key(r)))
    return h2h + wins[:CLOSE_TOP_WINS] + losses[:CLOSE_TOP_LOSSES]


def trade_head(row: dict, names: dict) -> str:
    """'*NVDA* N+1, Model + news (rule.model_news.v1) (accuracy)'."""
    view = ("head-to-head, " + PICK_RULE_LABELS.get(row.get("pick_rule"), str(row.get("pick_rule")))
            if row.get("view") == "head_to_head" else "accuracy")
    return f"*{row['ticker']}* {fmt.horizon(row['horizon_days'])}, {fmt.who(row['strategy_id'], names)} ({view})"


def trade_line(row: dict, names: dict, currency: str) -> str:
    """One settled trade: who, horizon, entry -> exit, net profit, target and range outcome."""
    head = "• " + trade_head(row, names)
    if row.get("status") != "settled":
        return f"{head}: {STATUS_TEXT.get(row.get('status'), row.get('status'))}. {PAPER}"
    target = "target reached" if row.get("target_reached") else "target not reached"
    rng = "closed inside its 80% range" if row.get("range_hit") else "closed outside its 80% range"
    flags = f" Flags: {', '.join(row['flags'])}." if row.get("flags") else ""
    return (f"{head}: bought {fmt.money(currency, row.get('entry_price'))} on {row.get('entry_date')}, sold"
            f" {fmt.money(currency, row.get('exit_price'))} on {row.get('exit_date_actual') or row.get('exit_date')};"
            f" net {fmt.signed_money(currency, row.get('net_pnl'))} ({fmt.pct(row.get('return_pct'))}) after"
            f" {fmt.money(currency, row.get('costs'))} market costs{costs.trade_cost_text(row, currency)};"
            f" {target}, {rng}; main reason"
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
    shown = listed_rows(rows)
    lines += [trade_line(r, names, currency) for r in shown]
    rest = len(rows) - len(shown)
    if rest:
        lines.append(MSG_MORE_ON_DASHBOARD.format(count=rest, s="s" if rest != 1 else ""))
    lines.append(MSG_FOOTER)
    return "\n".join(lines) + "\n"
