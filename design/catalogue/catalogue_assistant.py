"""Assistant answers (F11, the `explain` tool's `answer` of mcp/tools.yaml) and the track-record page payload
(rm.track_record) as EXAMPLES. Every answer text is composed from the catalogue's own example records (paper_trade,
eod_analysis, news_item), so a page never shows words the records do not back. The track record is the dashboard's
payload as of the cut-off (presentation/dashboard: skill status, walk-forward back-test, ranges and replay, all stored
data; no call is scored yet), with an example `calls` block computed by the same code (track.calls_by_basis) from the
example ai.combined.opus.v1 calls, scored close-to-close as config/settings.yaml call_scoring requires for calls made
before 2026-10-08."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.presentation.dashboard import track
from marketbrief.presentation.dashboard.assemble import gather_dashboard
from marketbrief.warehouse import rm_track_record

HERE = Path(__file__).resolve().parent
CUTOFF = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
AS_OF = "2026-10-07T12:00:00Z"
FORECASTER = "ai.combined.opus.v1"   # the forecaster's calls are this trader's predictions (docs/SPEC.md section 4)
CURRENCY = {"india": "₹", "us": "$"}


def records(name: str) -> list[dict]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))["records"]


def example_calls(settled: list[dict], market: str) -> pd.DataFrame:
    """The forecaster's example calls (all up) scored close-to-close as score_predictions scores them: the as-of
    close to the close h stored bars later, scored at the next pre-open run after that session."""
    from make_examples import BARS, MADE_AT, PREV_CLOSE_0929, calendar

    cfg, rows = load_market(market), []
    for trade in settled:
        if (trade["market"], trade["strategy_id"], trade["view"], trade["status"]) != (market, FORECASTER, "accuracy",
                                                                                       "settled"):
            continue
        ticker, horizon = trade["ticker"], trade["horizon_days"]
        later = sorted(day for day in BARS[ticker] if day > "2026-09-29")
        exit_day = later[horizon - 1]
        actual = BARS[ticker][exit_day][3] / PREV_CLOSE_0929[ticker] - 1
        scored = calendar.next_session(cfg, date.fromisoformat(exit_day), include=False)
        rows.append({"id": trade["prediction_id"], "scored_at": pd.Timestamp(f"{scored}{MADE_AT[market]}"),
                     "target_date": pd.Timestamp(exit_day),
                     "hit": actual > 0, "label_basis": "close_to_close", "horizon_label": "legacy_cc",
                     "horizon_days": horizon, "confidence": trade["prob_up"], "actual_return": actual})
    return pd.DataFrame(rows)


def track_records(settled: list[dict]) -> list[dict]:
    out = []
    for market in ("india", "us"):
        data = gather_dashboard(load_market(market), connect(market), CUTOFF)
        con = duckdb.connect()
        con.register("calls", example_calls(settled, market))
        con.execute("CREATE TABLE track_record AS SELECT * FROM calls")
        out.append({"market": market, "as_of": str(data["as_of"]), "skill": data["skill"],
                    "calls": track.calls_by_basis(con, CUTOFF), "ranges": data["track"]["ranges"],
                    "replay": data["track"]["replay"], "min_sample": data["track"]["min_sample"],
                    "backtest": data["backtest"], "example_parts": ["calls", "weekly"],
                    "weekly": rm_track_record.weekly_series(con, CUTOFF)})
    return out


MINUS = "\u2212"
STATUS_WORDS = {"confirmed_primary": "confirmed by a filing", "corroborated": "confirmed by independent outlets"}
REASON_WORDS = {"market_up": "the market rose", "market_down": "the market fell", "sector_lift": "its sector rose",
                "sector_drag": "its sector fell", "news_positive": "positive news", "news_negative": "negative news",
                "company_specific": "a company-specific move"}
FAMILY_WORDS = {"rule": "Rule strategies", "ai": "AI traders", "baseline": "Baselines"}


def signed(value: float) -> str:
    """A number with its sign, a proper minus for negatives."""
    return f"{MINUS if value < 0 else '+'}{abs(value):.2f}"


def money(market: str, value: float) -> str:
    return f"{MINUS if value < 0 else ''}{CURRENCY[market]}{abs(value):,.2f}"


def cite(record: dict, kind: str, at: str) -> dict:
    return {"id": record["id"], "kind": kind, "as_of": record[at]}


def trade_answer(market: str, ticker: str, horizon: int) -> tuple[str, str, list[dict]]:
    trade = next(t for t in records("paper_trade.json")
                 if (t["market"], t["ticker"], t["horizon_days"], t["strategy_id"], t["view"])
                 == (market, ticker, horizon, "rule.model_news.v1", "accuracy"))
    news = next(n for n in records("news_item.json") if n["id"] == trade["news_ids"][0])
    question = f"Why did the N+{horizon} paper trade in {ticker} bought on {trade['entry_date']} end as it did?"
    text = (f"The rule strategy rule.model_news.v1 bought {ticker} at the {trade['entry_date']} open and sold at the "
            f"{trade['exit_date_actual']} close: {signed(trade['return_pct'])} % after market costs "
            f"({money(market, trade['net_pnl'])}). Of the {signed(trade['move_pct'])} % move, the market gave "
            f"{signed(trade['market_pct'])}, the sector {signed(trade['sector_pct'])}, verified news "
            f"{signed(trade['news_pct'])} (\"{news['title']}\", {STATUS_WORDS[news['status']]}) and the company itself "
            f"{signed(trade['company_pct'])}. Main reason: {REASON_WORDS[trade['reason_code']]}. Paper trade only.")
    return question, text, [cite(trade, "paper_trades_settled", "settled_at"), cite(news, "news", "first_seen_at")]


def rule_vs_ai_answer(market: str) -> tuple[str, str, list[dict]]:
    eod = next(e for e in records("eod_analysis.json") if e["market"] == market)
    results = eod["results"]
    parts = [f"{FAMILY_WORDS[family]}: {results[family]['trades']} trades, {results[family]['wins']} won, "
             f"{money(market, results[family]['net_pnl'])}" for family in ("rule", "ai", "baseline")]
    question = f"Rule or AI: who did better on {eod['session_date']}?"
    text = (f"Paper trades settled on {eod['session_date']}, after market costs. " + "; ".join(parts) +
            ". One day decides nothing; the scoreboard ranks strategies over at least 20 trades.")
    return question, text, [cite(eod, "eod_analyses", "created_at")]


def answer(market: str, number: int, asked_at: str, content: tuple[str, str, list[dict]],
           flags: dict | None = None) -> dict:
    """One answer of the `explain` tool, reading the data as of the moment it was asked (as_of = asked_at, both
    before the examples' cut-off); flags: not_in_data (default false), declined (default none)."""
    question, text, cited = content
    flags = flags or {}
    return {"id": f"ask-{market}-{asked_at[:10]}-{number}", "market": market, "channel": "dashboard",
            "asked_at": asked_at, "question": question, "text": text, "cited_ids": [c["id"] for c in cited],
            "cited": cited, "as_of": asked_at, "not_in_data": flags.get("not_in_data", False),
            "declined": flags.get("declined")}


def assistant_answers() -> list[dict]:
    advice = ("Should I buy NVDA tomorrow with real money?",
              "I can't advise real trades: this is a research tool and every signal here is a paper record. I can "
              "show NVDA's paper predictions and how its strategies have done.", [])
    past = ("What did Reliance close at on 8 Oct?",
            "Not in the data: the stored prices end with the 6 Oct close, as of 7 Oct 11:55 UTC.", [])
    return [
        answer("us", 1, "2026-10-07T11:40:00Z", trade_answer("us", "NVDA", 3)),
        answer("us", 2, "2026-10-07T11:42:00Z", rule_vs_ai_answer("us")),
        answer("us", 3, "2026-10-07T11:45:00Z", advice, {"declined": "advice"}),
        answer("india", 1, "2026-10-07T11:50:00Z", trade_answer("india", "RELIANCE", 3)),
        answer("india", 2, "2026-10-07T11:52:00Z", rule_vs_ai_answer("india")),
        answer("india", 3, "2026-10-07T11:55:00Z", past, {"not_in_data": True}),
    ]
