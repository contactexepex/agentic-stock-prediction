"""Strategy-lab examples built with B2's engine code (EXAMPLES only): back-test scoreboard rows
(lab/reports.run_backtest on the stored bars, as `lab.py backtest` runs it), heatmap cells and cumulative lines
(lab/heatmaps.heatmap_data) of the example trades, and the 2026-W40 research reviews, whose leaders come from
lab/scoreboard over the trades settled by the review's writing time."""
from __future__ import annotations

from datetime import datetime, timezone

from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import heatmaps, reports
from marketbrief.lab import scoreboard as lab_scoreboard

CUTOFF = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)   # the examples' cut-off (the files' as_of)
W40_WRITTEN = {"india": "2026-10-03T04:50:00Z", "us": "2026-10-03T14:20:00Z"}   # Saturday 10:20 IST / 10:20 New York


def backtest(eurusd: float) -> tuple[list[dict], dict]:
    """F2.3 back-test rows of both markets on the bars stored by the cut-off (no history cache: it is not in the
    repository). The US has no stored EURUSD closes, so the BUX order fee is converted at the examples' assumed rate,
    which the engine labels in `eurusd`."""
    rows, runs = [], {}
    for market in ("india", "us"):
        result = reports.run_backtest(connect(market), load_market(market), CUTOFF, False,
                                      eurusd if market == "us" else None)
        assert result.get("rows"), result
        rows += result["rows"]
        runs[market] = {key: result[key] for key in ("history", "first_date", "last_date", "eurusd", "note")}
    return rows, {"runs": runs}


def heatmap(settled: list[dict]) -> dict:
    return heatmaps.heatmap_data(settled, "forward")


def leaders_w40(settled: list[dict], market: str) -> list[dict]:
    """The best rule and AI strategy (accuracy view, all horizons) over the trades settled by the W40 review, ranked as
    B3's director facts rank them (traders/director_facts.py LEADERS_SQL): net_pnl desc, trades desc, strategy_id."""
    known = [t for t in settled if t["market"] == market and t["settled_at"] <= W40_WRITTEN[market]]
    rows = lab_scoreboard.scoreboard(known, "forward", "2026-10-02")
    out = []
    for family in ("rule", "ai"):
        mine = [r for r in rows if r["scope"] == "strategy" and r["view"] == "accuracy" and r["family"] == family
                and r["horizon_days"] == "all"]
        best = min(mine, key=lambda r: (-r["net_pnl"], -r["trades"], r["strategy_id"]))   # B3 LEADERS_SQL order
        out.append({"scope": family, "strategy_id": best["strategy_id"], "net_pnl": best["net_pnl"],
                    "trades": best["trades"]})
    return out


def reviews_w40(row, settled: list[dict]) -> list[dict]:
    out = []
    for market, currency in (("us", "USD"), ("india", "INR")):
        rule, ai = leaders_w40(settled, market)
        out.append(row(
            "research_reviews", id=f"rr-{market}-2026-W40", market=market, iso_week="2026-W40",
            period_start="2026-09-28", period_end="2026-10-02", leaders=[rule, ai],
            findings=[{"text": f"First settled week: {rule['strategy_id']} {rule['net_pnl']:+,.2f} {currency} on "
                               f"{rule['trades']} trades, {ai['strategy_id']} {ai['net_pnl']:+,.2f} {currency} on "
                               f"{ai['trades']}; far too few trades to rank.",
                       "cited_ids": [rule["strategy_id"], ai["strategy_id"]]}],
            proposals=[], report_path=f"reports/{market}/research-2026-W40.md", prompt_version="director-v1",
            written_at=W40_WRITTEN[market]))
    return out
