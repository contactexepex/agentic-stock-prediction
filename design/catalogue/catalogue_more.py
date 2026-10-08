"""The remaining entity files of design/catalogue/ (EXAMPLES only): lifecycle, commands, abstentions, intraday trade
checks, AI reasons, EOD analyses, news, news impact, results digests, market status, research review, portfolio."""
from __future__ import annotations

import math
from datetime import date, timedelta

from make_examples import BARS, COMPANIES, DEFAULT_AMOUNT, SCHEMAS, SIGMA_1D, calendar, load_market


def row(kind_name: str, /, **values) -> dict:
    out = dict.fromkeys(SCHEMAS[kind_name][1])
    unknown = set(values) - set(out)
    assert not unknown, (kind_name, unknown)
    out.update(values)
    return out


def lifecycle_events() -> list[dict]:
    seed = "2026-09-24T06:00:00Z"   # seeding time (Wave 5): recorded_at honest, effective_from = start of history
    rows = []
    for market in ("india", "us"):
        names = dict(COMPANIES[market])
        names.update({"india": {"INDIGO": ("InterGlobe Aviation (IndiGo)", "Transport", "INDIGO.NS")},
                      "us": {"DAL": ("Delta Air Lines", "Airlines", "DAL")}}[market])
        for ticker, meta in names.items():
            exchange = "NSE" if market == "india" else ("NYSE" if ticker in ("JPM", "DAL") else "NASDAQ")
            rows.append(row("watchlist_events", id=f"we-{market}-{ticker}-add-20260924T060000Z", market=market,
                            ticker=ticker, event="add", effective_from="2011-01-03T00:00:00Z", recorded_at=seed,
                            name=meta[0], exchange=exchange, sector=meta[1], yahoo=meta[2],
                            nse_symbol=ticker if market == "india" else None,
                            cik={"NVDA": "0001045810", "AAPL": "0000320193", "JPM": "0000019617",
                                 "DAL": "0000027904"}.get(ticker), amount=None,
                            currency="INR" if market == "india" else "USD", reason="seeded from config/markets",
                            requested_by="cli:session", channel="seed", idempotency_key=f"seed-{market}-{ticker}",
                            onboarding={"identifiers": "skipped", "backfill": "skipped", "collect_gate": "skipped"},
                            validator_version="lifecycle-v1"))
    rows += [
        row("watchlist_events", id="we-india-MARUTI-set_amount-20260925T091500Z", market="india", ticker="MARUTI",
            event="set_amount", effective_from="2026-09-28T02:10:00Z", recorded_at="2026-09-25T09:15:00Z",
            amount=10000.0, currency="INR", reason="smaller test amount", requested_by="dashboard:owner",
            channel="dashboard", command_id="cmd-20260925T091500Z-4e92e724", idempotency_key="amt-maruti-20260925",
            validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-india-INDIGO-deactivate-20261002T091800Z", market="india", ticker="INDIGO",
            event="deactivate", effective_from="2026-10-05T02:10:00Z", recorded_at="2026-10-02T09:18:00Z",
            reason="pause airlines", requested_by="slack:U07ABCD123", channel="slack",
            command_id="cmd-20261002T091800Z-22018a94", idempotency_key="deact-indigo-1",
            validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-us-DAL-deactivate-20261002T200000Z", market="us", ticker="DAL",
            event="deactivate", effective_from="2026-10-05T11:45:00Z", recorded_at="2026-10-02T20:00:00Z",
            reason="pause airlines", requested_by="dashboard:owner", channel="dashboard",
            command_id="cmd-20261002T200000Z-597d6a7f", idempotency_key="deact-dal-1",
            validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-us-MSFT-add-20261005T140200Z", market="us", ticker="MSFT", event="add",
            effective_from="2026-10-06T11:45:00Z", recorded_at="2026-10-05T14:02:00Z", name="Microsoft",
            exchange="NASDAQ", sector="Tech", yahoo="MSFT", cik="0000789019", amount=None, currency="USD",
            requested_by="slack:U07ABCD123", channel="slack", command_id="cmd-20261005T135500Z-052b8228",
            idempotency_key="add-msft-7Hq2",
            onboarding={"identifiers": "ok", "not_etf": "ok", "listing": "ok", "backfill_prices": "ok",
                        "backfill_news": "ok", "collect_gate": "ok"}, validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-us-MSFT-delete-20261006T150000Z", market="us", ticker="MSFT", event="delete",
            effective_from="2026-10-06T15:00:00Z", recorded_at="2026-10-06T15:00:00Z", reason="added by mistake",
            requested_by="dashboard:owner", channel="dashboard", command_id="cmd-20261006T150000Z-f7d62492",
            idempotency_key="del-msft-confirm", validator_version="lifecycle-v1"),
    ]
    return rows


def commands() -> list[dict]:
    return [
        row("command_log", id="cmd-20261005T135500Z-052b8228", market="us", received_at="2026-10-05T13:55:00Z",
            channel="slack", actor="slack:U07ABCD123", agent="slack-gateway", tool="add_company", kind="write",
            arguments={"market": "us", "symbol": "MSFT"}, idempotency_key="add-msft-7Hq2", result="accepted",
            message="Microsoft (NASDAQ, Tech, CIK 0000789019), $1,000 per trade - confirmed",
            record_ids=["we-us-MSFT-add-20261005T140200Z"], budget_left=19, completed_at="2026-10-05T14:02:00Z"),
        row("command_log", id="cmd-20261005T140500Z-73abce0f", market="us", received_at="2026-10-05T14:05:00Z",
            channel="slack", actor="slack:U07ABCD123", agent="slack-gateway", tool="add_company", kind="write",
            arguments={"market": "us", "symbol": "SPY"}, idempotency_key="add-spy-1", result="refused",
            refusal_code="validation_failed", message="SPY is an ETF; only common stocks can be added",
            record_ids=[], budget_left=18, completed_at="2026-10-05T14:05:02Z"),
        row("command_log", id="cmd-20261006T150000Z-99c9b960", market="india", received_at="2026-10-06T15:00:00Z",
            channel="claude_app", actor="github:owner", agent="claude-app", tool="get_scoreboard", kind="read",
            arguments={"market": "india", "view": "accuracy"}, idempotency_key=None, result="accepted",
            record_ids=[], budget_left=None, completed_at="2026-10-06T15:00:01Z"),
        row("command_log", id="cmd-20261006T151000Z-3ffb1995", market="us", received_at="2026-10-06T15:10:00Z",
            channel="slack", actor="slack:U07ABCD123", agent="slack-gateway", tool="delete_company", kind="write",
            arguments={"market": "us", "ticker": "DAL"}, idempotency_key="del-dal-x", result="refused",
            refusal_code="not_allowed_in_channel", message="Delete is only available on the dashboard",
            record_ids=[], budget_left=17, completed_at="2026-10-06T15:10:00Z"),
    ]


def abstentions() -> list[dict]:
    return [
        row("strategy_abstentions", id="ai.pattern_mood.sonnet.v1:2026-10-06-HDFCBANK",
            strategy_id="ai.pattern_mood.sonnet.v1", family="ai", market="india", ticker="HDFCBANK",
            made_at="2026-10-07T02:10:00Z", as_of_date="2026-10-06", session_date="2026-10-07", horizons=[1, 3, 5],
            reason_code="abstained", reason="Price pattern is mixed: a gap up reversed within two sessions; no edge.",
            gate_codes=[], attempts=1, prompt_version="trader-v1"),
        row("strategy_abstentions", id="ai.news_results.sonnet.v1:2026-10-06-JPM",
            strategy_id="ai.news_results.sonnet.v1", family="ai", market="us", ticker="JPM",
            made_at="2026-10-07T11:45:00Z", as_of_date="2026-10-06", session_date="2026-10-07", horizons=[1, 3, 5],
            reason_code="gate_failed", reason=None, gate_codes=["NEWS_STATUS_MAIN"], attempts=2,
            prompt_version="trader-v1"),
    ]


CHECKS = {"india": ("ic-india-2026-10-07T05:43Z", "2026-10-07T05:43:00Z", "2026-10-07T05:35:00Z", 118 / 375),
          "us": ("ic-us-2026-10-07T16:27Z", "2026-10-07T16:27:00Z", "2026-10-07T16:20:00Z", 177 / 390)}
# check_id as B9 writes it (intraday/settings.check_id); last_time = the newest complete 5-minute bar's start;
# elapsed share of today's session: India 09:15-15:30 IST (05:43 UTC = 118 of 375 min), US 09:30-16:00 New York
# (16:27 UTC = 177 of 390 min). B9's thresholds (config/intraday.yaml): target_z 2.0, against_call_z 1.0.
TARGET_Z, AGAINST_Z = 2.0, 1.0


def trade_check(trade: dict, last: float) -> dict:
    """One trade_checks row (B9's rules, docs/ws/b9.md Contract) for an open trade; no split, so basis_factor 1."""
    check_id, check_at, last_time, elapsed = CHECKS[trade["market"]]
    ticker, entry = trade["ticker"], trade["entry_price"]
    held_bars = [BARS[ticker][d] for d in BARS[ticker] if d >= trade["entry_date"]]
    session_number = len(held_bars) + 1
    cfg = load_market(trade["market"])
    left = sum(1 for d in sessions_from(cfg, "2026-10-07", trade["exit_date"])) - elapsed
    held = session_number - 1 + elapsed
    sigma = SIGMA_1D[ticker]
    ret = last / entry - 1
    z_since = ret / (sigma * math.sqrt(held))
    target_z = (trade["target_price"] / last - 1) / (sigma * math.sqrt(left))
    highs = [bar[1] for bar in held_bars] + [last]
    reached = [i + 1 for i, high in enumerate(highs) if high >= trade["target_price"]]
    lo80, lo50, hi50, hi80 = trade["lo80"], trade["lo50"], trade["hi50"], trade["hi80"]
    band = ("below80" if last < lo80 else "below50" if last < lo50 else "inside50" if last <= hi50
            else "above50" if last <= hi80 else "above80")
    flags = ["outside_range"] if band in ("below80", "above80") else []
    flags += ["far_from_target"] if not reached and target_z >= TARGET_Z else []
    flags += ["against_prediction"] if z_since <= -AGAINST_Z else []
    return row("trade_checks", id=f"{check_id}-{trade['trade_id']}", check_id=check_id,
               check_row_id=f"{check_id}-{ticker}", check_at=check_at, session_date="2026-10-07",
               market=trade["market"], ticker=ticker, trade_id=trade["trade_id"],
               prediction_id=trade["prediction_id"], strategy_id=trade["strategy_id"], view=trade["view"],
               horizon_days=trade["horizon_days"], entry_date=trade["entry_date"], exit_date=trade["exit_date"],
               session_number=session_number, entry_price=entry, last_price=last,
               ret_since_entry_pct=round(ret * 100, 4), target_price=trade["target_price"],
               to_target_pct=round((trade["target_price"] / last - 1) * 100, 4), lo80=lo80, lo50=lo50, hi50=hi50,
               hi80=hi80, band=band, target_z=round(target_z, 3), flags=flags, flagged=bool(flags),
               method_version="tc-v1", computed_at=check_at, family=trade["family"],
               pick_rule=trade["trade_id"].split(":")[1] if trade["view"] == "head_to_head" else None,
               quality="ok", entry_source="stored_open", basis_factor=1.0, entry_adj=entry,
               target_adj=trade["target_price"], lo80_adj=lo80, lo50_adj=lo50, hi50_adj=hi50, hi80_adj=hi80,
               last_time=last_time, sigma_1d=round(sigma, 6), elapsed_fraction=round(elapsed, 4),
               sessions_held=round(held, 4), sessions_left=round(left, 4), z_since_entry=round(z_since, 3),
               target_reached=bool(reached), target_reached_session=reached[0] if reached else None,
               high_since_entry_pct=round((max(highs) / entry - 1) * 100, 4),
               low_since_entry_pct=round((min([bar[2] for bar in held_bars] + [last]) / entry - 1) * 100, 4),
               notes=[])


def sessions_from(cfg: dict, first: str, last: str) -> list[date]:
    """The market's sessions from first to last, both included."""
    day, out = date.fromisoformat(first), []
    while day <= date.fromisoformat(last):
        if calendar.is_session(cfg, day):
            out.append(day)
        day += timedelta(days=1)
    return out


def trade_checks(opens: list[dict]) -> list[dict]:
    prices = {"NVDA": 241.10, "RELIANCE": 1224.6, "HDFCBANK": 708.9, "JPM": 330.20, "AAPL": 334.95}
    seen: dict[str, int] = {}
    rows = []
    for trade in opens:
        if trade["ticker"] in prices and seen.get(trade["ticker"], 0) < 2:
            seen[trade["ticker"]] = seen.get(trade["ticker"], 0) + 1
            rows.append(trade_check(trade, prices[trade["ticker"]]))
    return rows


def reasons(settled: list[dict]) -> tuple[list[dict], list[dict]]:
    texts, eods = [], []
    for market in ("india", "us"):
        day = "2026-10-06"
        today = [t for t in settled if t["market"] == market and t["exit_date"] == day and t["status"] == "settled"]
        accuracy = [t for t in today if t["view"] == "accuracy"]   # a head-to-head trade repeats an accuracy trade
        wins = sorted((t for t in accuracy if t["net_pnl"] > 0), key=lambda t: -t["return_pct"])[:5]
        misses = sorted((t for t in accuracy if t["net_pnl"] <= 0), key=lambda t: t["return_pct"])[:5]
        chosen = [("head_to_head", None, t) for t in today if t["view"] == "head_to_head"]
        chosen += [("biggest_win", n + 1, t) for n, t in enumerate(wins)]
        chosen += [("biggest_miss", n + 1, t) for n, t in enumerate(misses)]
        ids = []
        for kind, rank, t in chosen:
            rid = f"tra:{t['trade_id']}" + ("" if kind == "head_to_head" else f":{kind}")
            ids.append(rid)
            news = (f" Verified news {t['news_ids'][0]} added about {t['news_pct']:+.2f} points."
                    if t["news_ids"] else "")
            reached = "reached" if t["target_reached"] else "not reached"
            texts.append(row(
                "trade_reasons_ai", id=rid, trade_id=t["trade_id"], settlement_id=t["id"], market=market,
                ticker=t["ticker"], strategy_id=t["strategy_id"], session_date=day, kind=kind, rank=rank,
                text=(f"{t['ticker']} moved {t['move_pct']:+.2f}% from entry: the market explains "
                      f"{t['market_pct']:+.2f} points and the sector {t['sector_pct']:+.2f}.{news} "
                      f"Net {t['return_pct']:+.2f}% after costs; target {reached}."),
                cited_ids=[t["trade_id"], *t["news_ids"]], reason_codes=t["reason_codes"], prompt_version="eod-v1",
                created_at="2026-10-06T12:40:00Z" if market == "india" else "2026-10-06T22:40:00Z"))
        results = {}
        for family in ("rule", "baseline", "ai"):
            mine = [t for t in today if t["family"] == family and t["view"] == "accuracy"]
            results[family] = {"trades": len(mine), "wins": sum(t["net_pnl"] > 0 for t in mine),
                               "net_pnl": round(sum(t["net_pnl"] for t in mine), 2)}
        for rule in ("best_expected_gain", "highest_probability"):
            mine = [t for t in today if t["pick_rule"] == rule]
            results[rule] = {"trades": len(mine), "net_pnl": round(sum(t["net_pnl"] for t in mine), 2)}
        eods.append(row("eod_analyses", id=f"eod-{market}-{day}", market=market, session_date=day,
                        settled_trades=len(today), results=results,
                        summary=(f"{len(today)} paper trades settled today. Rule strategies: net "
                                 f"{results['rule']['net_pnl']:+.2f}; AI traders: net {results['ai']['net_pnl']:+.2f} "
                                 f"({'INR' if market == 'india' else 'USD'}). The broad market set the direction; see "
                                 "each trade's reason."),
                        cited_ids=[t["trade_id"] for t in today][:5], reason_ids=ids, prompt_version="eod-v1",
                        created_at="2026-10-06T12:40:00Z" if market == "india" else "2026-10-06T22:40:00Z"))
    return texts, eods


def build_rest(write, settled, opens, eurusd, r2) -> None:
    from catalogue_bars import bar_rows
    from catalogue_calendar import calendar_events
    from catalogue_lab import backtest, heatmap, reviews_w40
    from catalogue_news import market_status, news_impact, news_items, portfolio, research_review, results_digests

    write("lifecycle_event.json", "lifecycle_event", "watchlist_events", lifecycle_events())
    write("command_log.json", "command", "command_log", commands())
    write("abstention.json", "abstention", "strategy_abstentions", abstentions())
    write("trade_check.json", "trade_check", "trade_checks", trade_checks(opens))
    ai_reasons, eods = reasons(settled)
    write("reason_ai.json", "ai_reason", "trade_reasons_ai", ai_reasons)
    write("eod_analysis.json", "eod_analysis", "eod_analyses", eods)
    from catalogue_newsfeed import news_page_items

    write("news_item.json", "news_item", None, news_page_items(news_items()))
    write("news_impact.json", "news_impact_row", "news_impact", news_impact(row))
    write("results_digest.json", "results_digest", "results_digests", results_digests(row))
    write("market_status.json", "market_status", None, market_status())
    write("calendar_event.json", "calendar_event", None, calendar_events())
    write("bar.json", "bar", None, bar_rows())
    write("research_review.json", "research_review", "research_reviews",
          research_review(row) + reviews_w40(row, settled))
    backtest_rows, backtest_runs = backtest(eurusd)
    write("scoreboard_backtest_row.json", "scoreboard_row", None, backtest_rows, backtest_runs)
    maps = heatmap(settled)
    write("heatmap_cell.json", "heatmap_cell", None, maps["cells"])
    write("cumulative_line.json", "cumulative_line", None, maps["lines"])
    write("portfolio.json", "portfolio", None, [portfolio(eurusd, r2, DEFAULT_AMOUNT)])
    from catalogue_assistant import assistant_answers, track_records

    write("track_record.json", "track_record", None, track_records(settled))
    write("assistant_answer.json", "assistant_answer", None, assistant_answers())
