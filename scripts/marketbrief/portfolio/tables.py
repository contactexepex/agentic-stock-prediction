"""Short readable tables of the portfolio outputs (printed to stderr by the CLI; stdout carries the JSON)."""
from __future__ import annotations


def table(rows: list[dict], columns: list[str]) -> str:
    """A plain fixed-width table of `columns` over `rows` ('-' for a missing value)."""
    if not rows:
        return "(none)"
    cells = [[("-" if row.get(c) is None else str(row.get(c))) for c in columns] for row in rows]
    widths = [max(len(c), *(len(line[i]) for line in cells)) for i, c in enumerate(columns)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(columns, widths))]
    lines += ["  ".join(v.ljust(w) for v, w in zip(line, widths)) for line in cells]
    return "\n".join(lines)


def head(result: dict) -> str:
    """The first line: market and label."""
    return f"[{result.get('market')}] {result.get('label', '')}".strip()


def stored_trade(result: dict) -> str:
    """A stored trade or cancellation."""
    return f"{head(result)}\nstored {result['trade']['id']} in {result['path']}\n" + table(
        [result["trade"]], ["ticker", "side", "quantity", "price", "price_basis", "trade_date", "supersedes"])


def stored_request(result: dict) -> str:
    """A stored watchlist request."""
    return f"stored {result['request']['id']} in {result['path']} (status requested; config is a human change)"


def positions(result: dict) -> str:
    """Open positions."""
    return head(result) + "\n" + table(result["positions"], ["ticker", "quantity", "avg_price", "mark", "mark_date",
                                                             "market_value"])


def pnl(result: dict) -> str:
    """Per-trade P&L and the totals."""
    trades = table(result["trades"], ["id", "ticker", "side", "quantity", "price", "cost", "realised_net",
                                      "open_quantity", "unrealised_net"])
    return f"{head(result)}\n{trades}\ntotals: {result['totals']}"


def listing(result: dict) -> str:
    """Every stored trade row with its state, and the requests."""
    trades = table(result["trades"], ["id", "ticker", "side", "quantity", "price", "trade_date", "state"])
    return f"{head(result)}\n{trades}\nrequests:\n" + table(result["requests"], ["id", "ticker", "name", "status"])


def tiers(result: dict) -> str:
    """The tiers, the proof status and the Paper candidates."""
    lines = [f"[{result['market']}] as of {result['as_of_date']} proof: {result['proof']['status']} — "
             f"{result['label']}", result["headline"] or f"{result['strong_count']} strong signal(s)",
             table(result["tiers"], ["ticker", "horizon_days", "tier", "model_prob", "final_prob", "band"])]
    if result["candidates"]:
        lines.append("Paper candidates:\n" + table(result["candidates"], ["ticker", "horizon_days", "direction",
                                                                         "model_prob", "distance"]))
    return "\n".join(lines)


def follow(result: dict) -> str:
    """The simulated paper-follow per side."""
    late = f" ({result['late_scores']} score ids left out: computed at or after the open of D)"
    return f"{result['label']}{late}\n" + table([{"side": k, **v} for k, v in result["sides"].items()],
                                                ["side", "positions", "scored", "hit_rate", "mean_net_pct",
                                                 "mean_net_per_date_pct"])


def api_shape(result: dict) -> str:
    """An api/openapi.yaml shape: a one-line summary (the JSON is the content)."""
    if "paper_candidates" in result:
        return f"{result['headline']}: {len(result['strong'])} strong, {len(result['paper_candidates'])} paper"
    return f"[{result['market']}] {result['label']}: {len(result['positions'])} open lot(s)"


def imported(result: dict) -> str:
    """One line per imported inbox request."""
    return f"[{result['market']}] imported {result['imported']} request(s)\n" + table(
        result["results"], ["inbox_id", "result", "refusal_code", "trade_ids"])


RENDERERS = {"add-trade": stored_trade, "cancel-trade": stored_trade, "request-company": stored_request,
             "positions": positions, "pnl": pnl, "list": listing, "signals": tiers, "paper-follow": follow,
             "api-signals": api_shape, "api-portfolio": api_shape, "import-inbox": imported}


def render(command: str, result: dict) -> str:
    """The readable table of a command's result (the errors when it was rejected)."""
    if result.get("ok") is False:
        return "REJECTED:\n" + "\n".join(f"- {e}" for e in result["errors"])
    return RENDERERS[command](result)
