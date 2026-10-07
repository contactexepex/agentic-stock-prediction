"""The WS4 payloads in the shapes of wave 0's api/openapi.yaml (branch build/wave0, read 2026-10-07):
`SignalTiers` / `SignalCandidate` (signal_tiers) and `PaperPortfolio` (paper_portfolio). The differences that
remain between the contract and the stored kinds are listed in docs/ws/ws4.md ("Alignment with api/openapi.yaml")."""
from __future__ import annotations

from datetime import date

import pandas as pd

from marketbrief.core.calendar import next_session
from marketbrief.lab.timing import exit_session
from marketbrief.portfolio import service
from marketbrief.portfolio.constants import TIER_STRONG_BUY, TIER_STRONG_SELL
from marketbrief.portfolio.horizons import resolved_label, sessions_after_d

API_TIERS = {TIER_STRONG_BUY: "strong_buy", TIER_STRONG_SELL: "strong_sell"}
PAPER_TIERS = {"up": "paper_up", "down": "paper_down"}


def entry_exit(cfg: dict, as_of: str | None, horizon: int, label: str) -> tuple[str | None, str | None]:
    """(D, the exit session): the open of D and the close of the k-th session after D for N+k (decision 37); a
    legacy_5d_d4 score exits at D+4 (issue #94; portfolio/horizons.sessions_after_d)."""
    if as_of is None:
        return None, None
    first = next_session(cfg, date.fromisoformat(as_of), include=False)
    return first.isoformat(), exit_session(cfg, first, sessions_after_d(horizon, label)).isoformat()


def candidate(cfg: dict, as_of: str | None, row: dict, tier: str) -> dict:
    """One SignalCandidate."""
    label = resolved_label(row["horizon_days"], row.get("horizon_label"), None)
    entry, exit_ = entry_exit(cfg, as_of, row["horizon_days"], label)
    meta = cfg["tickers"].get(row["ticker"]) or {}
    return {"ticker": row["ticker"], "name": meta.get("name"), "h": row["horizon_days"], "tier": tier,
            "model_prob": row["model_prob"], "prediction_id": row["id"] if row.get("has_call") else None,
            "direction": row.get("direction"), "confidence": row.get("confidence"), "entry": entry, "exit": exit_,
            "label": row["label"]}


def signal_tiers(payload: dict, cfg: dict) -> dict:
    """SignalTiers from signals.cockpit_payload: strong rows (only when proven) or the Paper candidates."""
    as_of = payload["as_of_date"]
    strong = [candidate(cfg, as_of, row, API_TIERS[row["tier"]])
              for row in payload["tiers"] if row["tier"] in API_TIERS]
    tiers = {row["id"]: row for row in payload["tiers"]}
    paper = [candidate(cfg, as_of, {**tiers[c["id"]], "direction": c["direction"], "label": c["label"]},
                       PAPER_TIERS[c["direction"]]) for c in payload["candidates"]]
    return {"headline": payload["headline"] or f"{payload['strong_count']} proven strong signal(s)",
            "rule": payload["proof"]["rule"], "strong": strong, "paper_candidates": paper}


def paper_portfolio(ctx: service.Context) -> dict:
    """PaperPortfolio: one position per open buy lot (marked to the latest stored close) and the active trades."""
    pnl = service.pnl_report(ctx)
    listed = {row["id"]: row for row in service.list_report(ctx)["trades"]}
    positions = []
    for row in pnl["trades"]:
        if row["side"] != "buy" or not row.get("open_quantity"):
            continue
        mark = row.get("mark")
        positions.append({"ticker": row["ticker"], "quantity": row["open_quantity"], "entry_date": row["trade_date"],
                          "entry_price": row["price"], "price_basis": row["price_basis"], "mark_close": mark,
                          "mark_date": row.get("mark_date"),
                          "unrealized_return": None if mark is None else round(mark / row["price"] - 1, 6),
                          "trade_id": row["id"]})
    trades = [{"id": row["id"], "ticker": row["ticker"], "side": row["side"], "quantity": row["quantity"],
               "price": row["price"], "date": row["trade_date"], "source": listed[row["id"]]["source"],
               "recorded_at": pd.Timestamp(listed[row["id"]]["entered_at"]).isoformat()} for row in pnl["trades"]]
    return {"market": ctx.market, "as_of": ctx.clock.date().isoformat(), "label": pnl["label"],
            "positions": positions, "trades": trades, "totals": pnl["totals"], "pending": []}
