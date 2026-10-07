"""The remaining entity files of design/catalogue/ (EXAMPLES only): lifecycle, commands, abstentions, intraday trade
checks, AI reasons, EOD analyses, news, news impact, results digests, market status, research review, portfolio."""
from __future__ import annotations

from make_examples import BARS, COMPANIES, DEFAULT_AMOUNT, SCHEMAS


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
        names.update({"INDIGO": ("InterGlobe Aviation (IndiGo)", "Transport", "INDIGO.NS"),
                      "DAL": ("Delta Air Lines", "Airlines", "DAL")})
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
            channel="dashboard", command_id="cmd-20260925T091500Z-4f1a9c2e", idempotency_key="amt-maruti-20260925",
            validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-india-INDIGO-deactivate-20261002T091800Z", market="india", ticker="INDIGO",
            event="deactivate", effective_from="2026-10-05T02:10:00Z", recorded_at="2026-10-02T09:18:00Z",
            reason="pause airlines", requested_by="slack:U07ABCD123", channel="slack",
            command_id="cmd-20261002T091800Z-9b3e11d0", idempotency_key="deact-indigo-1",
            validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-us-DAL-deactivate-20261002T200000Z", market="us", ticker="DAL",
            event="deactivate", effective_from="2026-10-05T11:45:00Z", recorded_at="2026-10-02T20:00:00Z",
            reason="pause airlines", requested_by="dashboard:owner", channel="dashboard",
            command_id="cmd-20261002T200000Z-5d6e7f80", idempotency_key="deact-dal-1",
            validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-us-MSFT-add-20261005T140200Z", market="us", ticker="MSFT", event="add",
            effective_from="2026-10-06T11:45:00Z", recorded_at="2026-10-05T14:02:00Z", name="Microsoft",
            exchange="NASDAQ", sector="Tech", yahoo="MSFT", cik="0000789019", amount=None, currency="USD",
            requested_by="slack:U07ABCD123", channel="slack", command_id="cmd-20261005T135500Z-0c7d5a21",
            idempotency_key="add-msft-7Hq2",
            onboarding={"identifiers": "ok", "not_etf": "ok", "listing": "ok", "backfill_prices": "ok",
                        "backfill_news": "ok", "collect_gate": "ok"}, validator_version="lifecycle-v1"),
        row("watchlist_events", id="we-us-MSFT-delete-20261006T080000Z", market="us", ticker="MSFT", event="delete",
            effective_from="2026-10-06T08:00:00Z", recorded_at="2026-10-06T08:00:00Z", reason="added by mistake",
            requested_by="dashboard:owner", channel="dashboard", command_id="cmd-20261006T080000Z-61aa02f4",
            idempotency_key="del-msft-confirm", validator_version="lifecycle-v1"),
    ]
    return rows


def commands() -> list[dict]:
    return [
        row("command_log", id="cmd-20261005T135500Z-0c7d5a21", market="us", received_at="2026-10-05T13:55:00Z",
            channel="slack", actor="slack:U07ABCD123", agent="slack-gateway", tool="add_company", kind="write",
            arguments={"market": "us", "symbol": "MSFT"}, idempotency_key="add-msft-7Hq2", result="accepted",
            message="Microsoft (NASDAQ, Tech, CIK 0000789019), $1,000 per trade - confirmed",
            record_ids=["we-us-MSFT-add-20261005T140200Z"], budget_left=19, completed_at="2026-10-05T14:02:00Z"),
        row("command_log", id="cmd-20261005T140500Z-a2c4e6f8", market="us", received_at="2026-10-05T14:05:00Z",
            channel="slack", actor="slack:U07ABCD123", agent="slack-gateway", tool="add_company", kind="write",
            arguments={"market": "us", "symbol": "SPY"}, idempotency_key="add-spy-1", result="refused",
            refusal_code="validation_failed", message="SPY is an ETF; only common stocks can be added",
            record_ids=[], budget_left=18, completed_at="2026-10-05T14:05:02Z"),
        row("command_log", id="cmd-20261006T150000Z-77d0be13", market="india", received_at="2026-10-06T15:00:00Z",
            channel="claude_app", actor="github:owner", agent="claude-app", tool="get_scoreboard", kind="read",
            arguments={"market": "india", "view": "accuracy"}, idempotency_key=None, result="accepted",
            record_ids=[], budget_left=None, completed_at="2026-10-06T15:00:01Z"),
        row("command_log", id="cmd-20261006T151000Z-3e9f0a77", market="us", received_at="2026-10-06T15:10:00Z",
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


def trade_checks(opens: list[dict]) -> list[dict]:
    rows = []
    prices = {"NVDA": 241.10, "RELIANCE": 1224.6, "HDFCBANK": 708.9, "JPM": 330.20, "AAPL": 334.95}
    checks = {"india": ("ic-india-202610070543", "2026-10-07T05:43:00Z"),
              "us": ("ic-us-202610071627", "2026-10-07T16:27:00Z")}
    seen: dict[str, int] = {}
    chosen = []
    for trade in opens:
        if trade["ticker"] in prices and seen.get(trade["ticker"], 0) < 2:
            seen[trade["ticker"]] = seen.get(trade["ticker"], 0) + 1
            chosen.append(trade)
    for trade in chosen:
        check_id, check_at = checks[trade["market"]]
        last = prices[trade["ticker"]]
        ret = (last / trade["entry_price"] - 1) * 100
        lo80, lo50, hi50, hi80 = trade["lo80"], trade["lo50"], trade["hi50"], trade["hi80"]
        band = ("below80" if last < lo80 else "below50" if last < lo50 else "inside50" if last <= hi50
                else "above50" if last <= hi80 else "above80")
        flags = ["outside_range"] if band in ("below80", "above80") else []
        flags += ["against_prediction"] if ret < 0 else []
        rows.append(row("trade_checks", id=f"{check_id}-{trade['trade_id']}", check_id=check_id,
                        check_row_id=f"{check_id}-{trade['ticker']}", check_at=check_at, session_date="2026-10-07",
                        market=trade["market"], ticker=trade["ticker"], trade_id=trade["trade_id"],
                        prediction_id=trade["prediction_id"], strategy_id=trade["strategy_id"], view="accuracy",
                        horizon_days=trade["horizon_days"], entry_date=trade["entry_date"],
                        exit_date=trade["exit_date"],
                        session_number=sum(d >= trade["entry_date"] for d in BARS[trade["ticker"]]) + 1,
                        entry_price=trade["entry_price"], last_price=last,
                        ret_since_entry_pct=round(ret, 2), target_price=trade["target_price"],
                        to_target_pct=round((trade["target_price"] / last - 1) * 100, 2), lo80=lo80, lo50=lo50,
                        hi50=hi50, hi80=hi80, band=band, target_z=None, flags=flags, flagged=bool(flags),
                        method_version="tc-v1", computed_at=check_at))
    return rows


def reasons(settled: list[dict]) -> tuple[list[dict], list[dict]]:
    texts, eods = [], []
    for market in ("india", "us"):
        day = "2026-10-06"
        today = [t for t in settled if t["market"] == market and t["exit_date"] == day and t["status"] == "settled"]
        wins = sorted((t for t in today if t["net_pnl"] > 0), key=lambda t: -t["return_pct"])[:5]
        misses = sorted((t for t in today if t["net_pnl"] <= 0), key=lambda t: t["return_pct"])[:5]
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
    from catalogue_news import market_status, news_impact, news_items, portfolio, research_review, results_digests

    write("lifecycle_event.json", "lifecycle_event", "watchlist_events", lifecycle_events())
    write("command_log.json", "command", "command_log", commands())
    write("abstention.json", "abstention", "strategy_abstentions", abstentions())
    write("trade_check.json", "trade_check", "trade_checks", trade_checks(opens))
    ai_reasons, eods = reasons(settled)
    write("reason_ai.json", "ai_reason", "trade_reasons_ai", ai_reasons)
    write("eod_analysis.json", "eod_analysis", "eod_analyses", eods)
    write("news_item.json", "news_item", None, news_items())
    write("news_impact.json", "news_impact_row", "news_impact", news_impact(row))
    write("results_digest.json", "results_digest", "results_digests", results_digests(row))
    write("market_status.json", "market_status", None, market_status())
    write("research_review.json", "research_review", "research_reviews", research_review(row))
    write("portfolio.json", "portfolio", None, [portfolio(eurusd, r2, DEFAULT_AMOUNT)])
