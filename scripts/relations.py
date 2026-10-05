#!/usr/bin/env python3
"""Relationship risk flags and context-pack sections (DESIGN.md phase 5) for markets with a
`relations:` block in their config (India: SEBI PIT trades, bulk/block deals, promoter pledges).

Flags (thresholds in the market config's `relations.flags`):
  big_deal        bulk/block deal at or above big_deal_crore, or big_deal_adv x 20-day volume
  pledge_increase promoter pledge (% of promoter holding) up >= pledge_increase_pp q/q
  pledge_created  a PIT disclosure of a new pledge;  pledge_invoked: a lender invoked a pledge
  insider_sale    promoter/director/KMP sale at or above insider_sale_crore
Used as context for the agents and, only when `relation_widen.enabled` in config/ranges.yaml,
to widen published ranges. Prints the flags as JSON."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from common import connect, load_ranges_config, market_arg, md_table, require_market, utc_today

CRORE = 1e7
DEFAULT_FLAGS = {"window_days": 5, "big_deal_crore": 250, "big_deal_adv": 0.5, "insider_sale_crore": 10,
                 "pledge_increase_pp": 1.0, "pledge_filed_days": 60}
INSIDER_ROLES = ("promoter", "director", "key managerial", "kmp")


def flag_settings(cfg: dict) -> dict | None:
    rel = cfg.get("relations")
    return {**DEFAULT_FLAGS, **(rel.get("flags") or {})} if rel else None


def risk_flags(cfg: dict, con, today: date | None = None) -> list[dict]:
    th = flag_settings(cfg)
    if th is None:
        return []
    today = today or utc_today()
    since = today - timedelta(days=int(th["window_days"]))
    tickers = list(cfg["tickers"])
    flags = []
    for t, day, kind, side, client, shares, price, crore, adv in con.execute("""
            SELECT ticker, date, deal_type, side, client, shares, price, value_crore, adv_ratio FROM deals_scored
            WHERE date >= ? AND list_contains(?, ticker) AND (value >= ? OR adv_ratio >= ?)
            ORDER BY date DESC, value DESC""",
            [since, tickers, th["big_deal_crore"] * CRORE, th["big_deal_adv"]]).fetchall():
        size = f"INR {crore:,.0f} cr" if crore is not None else "value n/a"
        flags.append({"ticker": t, "flag": "big_deal", "date": str(day),
                      "detail": f"{kind} {side or '?'} {shares:,.0f} sh @ {price or 0:,.2f} by {client} "
                                f"({size}{f', {adv:.2f}x 20d volume' if adv is not None else ''})"})
    for t, period, prev, pledged, change, filed in con.execute("""
            SELECT ticker, period_end, prev_period, pledged_pct_of_promoter, pledge_change_pp, filed_at FROM (
                SELECT * FROM pledge_changes WHERE list_contains(?, ticker)
                QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) = 1)
            WHERE pledge_change_pp >= ? AND coalesce(CAST(filed_at AS DATE), period_end + INTERVAL 60 DAY) >= ?""",
            [tickers, th["pledge_increase_pp"], today - timedelta(days=int(th["pledge_filed_days"]))]).fetchall():
        flags.append({"ticker": t, "flag": "pledge_increase", "date": str(filed.date() if filed else period),
                      "detail": f"promoter pledge {pledged:.2f}% of promoter holding at {period}, "
                                f"+{change:.2f} pp vs {prev}"})
    for t, day, person, category, txn, mode, shares, value in con.execute("""
            SELECT ticker, CAST(coalesce(disclosed_at, first_seen_at) AS DATE), person, person_category,
                   "transaction", mode, shares, value FROM insider_trades
            WHERE CAST(coalesce(disclosed_at, first_seen_at) AS DATE) >= ? AND list_contains(?, ticker)
            ORDER BY 2 DESC, value DESC NULLS LAST""", [since, tickers]).fetchall():
        txn_l, cat_l = (txn or "").lower(), (category or "").lower()
        who = f"{person} ({category})" if category else str(person)
        amount = f", INR {value / CRORE:,.1f} cr" if value else ""
        if "pledge" in txn_l and "invo" in txn_l:
            flags.append({"ticker": t, "flag": "pledge_invoked", "date": str(day),
                          "detail": f"{who}: {txn}, {shares or 0:,.0f} sh{amount}"})
        elif "pledge" in txn_l and not any(w in txn_l for w in ("revok", "release")):
            flags.append({"ticker": t, "flag": "pledge_created", "date": str(day),
                          "detail": f"{who}: {txn}, {shares or 0:,.0f} sh{amount}"})
        elif (txn_l.startswith(("sell", "sale")) and any(r in cat_l for r in INSIDER_ROLES)
              and (value or 0) >= th["insider_sale_crore"] * CRORE):
            flags.append({"ticker": t, "flag": "insider_sale", "date": str(day),
                          "detail": f"{who} sold {shares or 0:,.0f} sh{amount} ({mode or 'mode n/a'})"})
    return flags


def widen_by_ticker(cfg: dict, rc: dict, con) -> dict[str, tuple[float, str]]:
    """{ticker: (extra width, note)} from risk flags; empty unless relation_widen.enabled."""
    w = rc.get("relation_widen") or {}
    if not w.get("enabled"):
        return {}
    out: dict[str, tuple[float, set]] = {}
    for f in risk_flags(cfg, con):
        add = float(w.get(f["flag"], 0) or 0)
        if add > 0:
            total, names = out.get(f["ticker"], (0.0, set()))
            out[f["ticker"]] = (total + add if f["flag"] not in names else total, names | {f["flag"]})
    cap = float(w.get("max", 0.2))
    return {t: (round(min(x, cap), 4), f"relation flags +{min(x, cap):.0%} ({', '.join(sorted(n))})")
            for t, (x, n) in out.items() if x > 0}


def context_sections(cfg: dict, con) -> list[tuple[str, str]]:
    """(title, markdown) blocks for context.py; empty for markets without `relations:`."""
    th = flag_settings(cfg)
    if th is None:
        return []
    rel, today, tickers = cfg["relations"], utc_today(), list(cfg["tickers"])
    ins_days, deal_days = int(rel.get("insider_lookback_days", 14)), int(rel.get("deal_lookback_days", 5))
    out = [
        (f"Insider and promoter trades (SEBI PIT), disclosed in the last {ins_days} days", md_table(con.execute("""
            SELECT ticker, CAST(disclosed_at AS DATE) AS disclosed, person, person_category AS category,
                   "transaction", mode, shares, round(value / 1e7, 2) AS value_cr,
                   holding_before_pct AS before_pct, holding_after_pct AS after_pct
            FROM insider_trades
            WHERE CAST(coalesce(disclosed_at, first_seen_at) AS DATE) >= ? AND list_contains(?, ticker)
            ORDER BY disclosed DESC, value DESC NULLS LAST LIMIT 30""", [today - timedelta(days=ins_days), tickers]))),
        (f"Bulk and block deals, last {deal_days} days", md_table(con.execute("""
            SELECT ticker, date, deal_type AS type, side, client, shares, price, value_crore AS value_cr,
                   adv_ratio AS x_20d_vol
            FROM deals_scored WHERE date >= ? AND list_contains(?, ticker)
            ORDER BY date DESC, value DESC NULLS LAST LIMIT 30""", [today - timedelta(days=deal_days), tickers]))),
        ("Promoter holding and pledge (latest quarter per ticker; changes in percentage points). promoter_pct: "
         "company-filed shareholding pattern; encumbered_*: promoter shares encumbered (depository data); "
         "depo_pledged_pct: all holders' pledges as % of demat shares", md_table(con.execute("""
            SELECT ticker, period_end, promoter_pct, round(promoter_change_pp, 2) AS promoter_chg,
                   pledged_pct_of_promoter AS encumbered_of_promoter_pct, round(pledge_change_pp, 2) AS pledge_chg,
                   pledged_pct_of_total AS encumbered_of_total_pct, depository_pledged_pct AS depo_pledged_pct,
                   CAST(filed_at AS DATE) AS filed
            FROM pledge_changes WHERE list_contains(?, ticker)
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) = 1
            ORDER BY ticker""", [tickers]))),
    ]
    flags = risk_flags(cfg, con, today)
    body = ("| ticker | flag | date | detail |\n|---|---|---|---|\n" +
            "".join(f"| {f['ticker']} | {f['flag']} | {f['date']} | {f['detail'].replace('|', '/')} |\n" for f in flags)
            ) if flags else "_none_\n"
    out.append(("Relationship risk flags (big deals, pledge rises, insider sales)", body))
    return out


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    con = connect(cfg["market"])
    print(json.dumps({"market": cfg["market"], "flags": risk_flags(cfg, con),
                      "widen": {t: w for t, (w, _) in widen_by_ticker(cfg, load_ranges_config(), con).items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
