"""B11's page builders (marketbrief/warehouse/rm_watchlist.py, rm_home.py, rm_news.py) on a small synthetic US store:
the Watchlist's ranges are the reference rule strategy's newest predictions made by the cut-off (active companies),
Home's picks are those of the session being predicted made by the cut-off with their ranking and candidates, Home's
agreement is the active companies' top 5 per horizon, its "to date" rows are the head-to-head pick-rule rows over
all horizons, its end-of-day analysis carries the stored prompt version, and the News calendar spans the session
being predicted and the 7 days after it. Shared blocks of other sessions (B4, B13) are replaced by fakes here."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core import database  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import rm_common, rm_compare, rm_home, rm_news, rm_strategies, rm_watchlist  # noqa: E402
from marketbrief.warehouse.rm_registry import BuildContext  # noqa: E402

CUTOFF = datetime.fromisoformat("2026-10-07T12:00:00+00:00")
BEFORE = "2026-10-07T11:00:00+00:00"
AFTER = "2026-10-07T13:00:00+00:00"
SESSION = "2026-10-07"


def append(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / "us" / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def prediction(ticker: str, as_of: str, made_at: str, strategy: str = "rule.model_news.v1", k: int = 1) -> dict:
    return {"id": f"{strategy}:{as_of}-{ticker}-{k}d", "strategy_id": strategy, "family": "rule", "market": "us",
            "ticker": ticker, "made_at": made_at, "as_of_date": as_of, "session_date": SESSION,
            "exit_date": "2026-10-08", "horizon_days": k, "direction": "up", "prob_up": 0.57, "qualifies": True,
            "base_close": 100.0, "target_price": 101.0, "lo50": 99.0, "hi50": 102.0, "lo80": 97.0, "hi80": 104.0,
            "range_widen": 0.0, "regime": "TRENDING", "quality": "OK"}


def pick_row(pick_id: str, ticker: str, made_at: str, session: str = SESSION) -> dict:
    return {"id": pick_id, "market": "us", "ticker": ticker, "made_at": made_at, "as_of_date": "2026-10-06",
            "session_date": session, "family": "rule", "pick_rule": "best_expected_gain", "status": "picked",
            "strategy_id": "rule.model_news.v1", "strongest_basis": "all_companies",
            "ranking": [{"strategy_id": "rule.model_news.v1", "rank": 1, "basis": "all_companies",
                         "settled_trades": 0, "net_pnl": 0.0, "extra": "dropped"}],
            "horizon_days": 1, "prediction_id": "p1", "base_close": 100.0, "prob_up": 0.57, "move_pct": 1.0,
            "loss_pct": 1.0, "costs_pct": 0.2, "expected_gain_pct": -0.06,
            "candidates": [{"horizon_days": 1, "prediction_id": "p1", "prob_up": 0.57, "eligible": True,
                            "cost_viable": False, "unlisted": 1}],
            "amount": 1000.0, "currency": "USD", "method_version": "lab-v1"}


def store(root: Path) -> None:
    append(root, "strategy_predictions", "2026-10-06", [
        prediction("AAPL", "2026-10-05", "2026-10-06T11:00:00+00:00"),        # an older as-of date
    ])
    append(root, "strategy_predictions", "2026-10-07", [
        prediction("AAPL", "2026-10-06", BEFORE),
        prediction("AAPL", "2026-10-06", BEFORE, k=3),
        prediction("DAL", "2026-10-06", BEFORE),                                 # DAL is inactive
        prediction("JPM", "2026-10-06", BEFORE, strategy="rule.model_news_half.v1"),
        prediction("JPM", "2026-10-07", AFTER),                                  # made after the cut-off
    ])
    append(root, "watchlist_events", "2026-10-05", [{
        "id": "we-us-DAL-deactivate-20261005T000000Z", "market": "us", "ticker": "DAL", "event": "deactivate",
        "effective_from": "2026-10-05T11:45:00+00:00", "recorded_at": "2026-10-05T00:00:00+00:00",
        "reason": "pause airlines", "requested_by": "dashboard:owner", "channel": "dashboard"}])
    append(root, "head_to_head_picks", "2026-10-07", [
        pick_row("h2h-aapl", "AAPL", BEFORE),
        pick_row("h2h-jpm-late", "JPM", AFTER),
        pick_row("h2h-aapl-old", "AAPL", "2026-10-06T11:00:00+00:00", session="2026-10-06"),
        pick_row("h2h-dal", "DAL", BEFORE),
    ])
    append(root, "eod_analyses", "2026-10-06", [{
        "id": "eod-us-2026-10-06", "market": "us", "session_date": "2026-10-06", "settled_trades": 0,
        "results": {}, "summary": "No trades settled.", "cited_ids": [], "reason_ids": [],
        "prompt_version": "eod-v1", "created_at": "2026-10-06T22:40:00+00:00"}])


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    root = tmp_path_factory.mktemp("b11pages")
    store(root)
    saved, mp = common.ROOT, pytest.MonkeyPatch()
    common.ROOT = root
    mp.setenv("MB_NOW", CUTOFF.isoformat())
    try:
        yield BuildContext(load_market("us"), database.connect("us"), CUTOFF)
    finally:
        common.ROOT = saved
        mp.undo()


def test_watchlist_ranges_are_the_reference_strategys_newest_by_the_cutoff(ctx):
    rows = rm_watchlist.ranges(ctx)
    assert [r["id"] for r in rows] == ["rule.model_news.v1:2026-10-06-AAPL-1d", "rule.model_news.v1:2026-10-06-AAPL-3d"]
    first = rows[0]
    assert first["made_at"] == "2026-10-07T11:00:00Z" and first["as_of_date"] == "2026-10-06"
    assert (first["lo80"], first["hi80"], first["qualifies"], first["horizon_days"]) == (97.0, 104.0, True, 1)
    assert set(first) == set(rm_watchlist.RANGE_TEXT + rm_watchlist.RANGE_NUMBERS + rm_watchlist.RANGE_DATES) | {
        "made_at", "horizon_days", "qualifies"}


def test_home_picks_of_the_session_made_by_the_cutoff(ctx, monkeypatch):
    monkeypatch.setattr(rm_home, "session_date", lambda _ctx: SESSION)
    picks = rm_home.head_to_head(ctx)
    assert [p["id"] for p in picks] == ["h2h-aapl"]   # later, older-session and inactive picks left out
    only = picks[0]
    assert only["made_at"] == "2026-10-07T11:00:00Z" and only["method_version"] == "lab-v1"
    assert only["ranking"] == [{"strategy_id": "rule.model_news.v1", "rank": 1, "basis": "all_companies",
                                "settled_trades": 0, "net_pnl": 0.0}]
    assert set(only["candidates"][0]) == set(rm_compare.CANDIDATE_FIELDS)


def test_home_agreement_is_the_active_top_five(ctx, monkeypatch):
    rows = [{"ticker": t, "rank": n} for n, t in enumerate(["DAL", "AAPL", "JPM", "NVDA", "BAC", "GM", "XOM"], 1)]
    monkeypatch.setattr(rm_common, "agreement", lambda _ctx: {"1": rows, "2": []}, raising=False)
    top = rm_home.top_agreement(ctx)
    assert [r["ticker"] for r in top["1"]] == ["AAPL", "JPM", "NVDA", "BAC", "GM"] and top["2"] == []


def test_home_to_date_rows_and_eod(ctx, monkeypatch):
    base = {"market": "us", "family": "rule", "pick_rule": "best_expected_gain", "trades": 0, "net_pnl": 0.0,
            "mean_return_pct": None, "win_rate": None, "sample_badge": "too_few_to_rank", "basis": "forward",
            "as_of": "2026-10-06", "strategy_id": None, "luck_test": {}}
    rows = [{**base, "scope": "pick_rule", "view": "head_to_head", "horizon_days": "all"},
            {**base, "scope": "pick_rule", "view": "head_to_head", "horizon_days": 1},
            {**base, "scope": "strategy", "view": "accuracy", "horizon_days": "all"}]
    monkeypatch.setattr(rm_strategies, "scoreboard_rows", lambda _ctx: rows)
    to_date = rm_home.to_date(ctx)
    assert len(to_date) == 1 and set(to_date[0]) == set(rm_home.TO_DATE_FIELDS)
    eod = rm_home.newest_eod(ctx)
    assert eod["id"] == "eod-us-2026-10-06" and eod["prompt_version"] == "eod-v1"
    assert set(eod) == set(rm_home.EOD_FIELDS)


def test_news_calendar_spans_the_session_and_seven_days(ctx, monkeypatch):
    seen = {}

    def fake_calendar(_cfg, _con, cutoff, first, last, tickers):
        seen.update(first=first, last=last, tickers=tickers, cutoff=cutoff)
        return []

    monkeypatch.setattr(rm_news, "session_date", lambda _ctx: SESSION)
    monkeypatch.setattr(rm_news, "calendar_events", fake_calendar)
    rm_news.calendar(ctx)
    assert (seen["first"], seen["last"]) == (date(2026, 10, 7), date(2026, 10, 14))
    assert "DAL" not in seen["tickers"] and "AAPL" in seen["tickers"] and seen["cutoff"] == CUTOFF
