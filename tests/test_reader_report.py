"""The reader's daily report (C2, presentation/reader/): the lean and plain-language "why" built from a stored
model score, the flags, the 20-second glance and "what changed" summaries, and the page's self-contained assets."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.constants import reader as text  # noqa: E402
from marketbrief.presentation.reader import gather, page, why  # noqa: E402


def score(prob, groups, base=0.48, items=None):
    return {"prob_up": prob, "base_rate": base,
            "contributions": {"groups": groups, "news": {"items": items, "ids": []}}}


def test_lean_thresholds():
    assert why.lean(None) == ("none", "none")
    assert why.lean(0.5) == why.lean(0.519) == why.lean(0.481) == ("none", "none")
    assert why.lean(0.52) == ("up", "slight") and why.lean(0.48) == ("down", "slight")
    assert why.lean(0.55) == ("up", "clear") and why.lean(0.4499) == ("down", "clear")


def test_why_line_names_the_strongest_push_each_way():
    s = score(0.56, {"baseline": -0.1, "news": 1.4, "regime": -0.09, "volume": 0.01}, items=27)
    assert why.why_line(s) == ("Leans up mainly because recent verified news (27 items) pushes the chance up; "
                               "on the other side, the model's market-mood signals push the chance down.")
    one = score(0.47, {"baseline": -0.2, "momentum": -0.3}, items=1)
    assert why.why_line(one) == "Leans slightly down mainly because the model's price-trend signals push the chance down."
    # a group's points are its push on the estimate, not the market's state: UAL's falling price (10-day rate of change
    # -3.4%) gave momentum +0.11 points, so the line names the push and never claims "the trend points up"
    ual = score(0.56, {"baseline": -0.07, "momentum": 0.11, "relative strength": 0.05})
    line = why.why_line(ual)
    assert line == ("Leans up mainly because the model's price-trend signals push the chance up.")
    assert "trend points" not in line and "better than its sector" not in line


def test_why_line_baseline_and_no_signal():
    # the usual odds (the model's baseline) push the lean more than any signal: say so
    s = score(0.47, {"baseline": -0.45, "news": -0.2}, base=0.4756, items=6)
    assert why.why_line(s) == ("Leans slightly down, mostly from the usual odds (in the past 48% of such cases went "
                               "up); also recent verified news (6 items) pushes the chance down.")
    flat = score(0.49, {"baseline": -0.45, "news": 0.0}, base=0.4756)
    assert why.why_line(flat) == "No strong signal: the model stays close to the usual odds (48% of past cases went up)."
    assert why.why_line(None) == why.why_line({"prob_up": None}) == text.WHY_NO_SCORE
    unknown = score(0.6, {"cross market": 0.3})
    assert why.why_line(unknown) == "Leans up mainly because the model's cross market signals push the chance up."
    assert why.why_line(score(0.6, {"cross: fx": 0.3})) == "Leans up mainly because the model's cross-market fx signals push the chance up."


def test_flags():
    assert why.flags("OK", None, False) == []
    assert why.flags("OK", 9, False) == []
    assert [f["text"] for f in why.flags("BLOCKED", 3, True)] == [
        "Results in 3 days: prices can jump", "Data problem: no forecast is trusted today",
        "Some recent news was contradicted by other sources"]
    assert why.flags("OK", 1, False)[0]["text"] == text.EARNINGS_TODAY


def card(ticker, rows):
    return {"ticker": ticker, "forecasts": [
        {"h": h, "prob_up": p, "lean": why.lean(p)[0], "move_pct": m, "change": c} for h, p, m, c in rows]}


def test_glance_counts_and_biggest_moves():
    cards = [card("A", [(1, 0.6, 1.5, None)]), card("B", [(1, 0.4, -2.0, None)]), card("C", [(1, 0.5, 0.0, None)]),
             card("D", [(1, None, 0.7, None)]), card("E", [])]
    g = gather.glance(cards)["1"]
    assert (g["up"], g["down"], g["none"], g["no_score"]) == (1, 1, 1, 2)
    assert g["moves"] == ["B", "A", "D"]                 # by size of the move; a 0% move is never listed
    assert gather.glance(cards)["3"]["no_score"] == 5


class Statuses:
    def of(self, nid, ticker, when):
        return "corroborated" if nid == "n1" else "unverified"


def test_changes_lists_big_moves_and_newly_counted_news():
    big = {"since": "2026-10-08T02:26:06Z", "target_pct": -4.06, "prob_pts": -0.0337, "news_added": ["n1", "n2"]}
    small = {"since": "2026-10-08T02:26:06Z", "target_pct": 0.1, "prob_pts": 0.001, "news_added": ["n1"]}
    prob_only = {"since": "2026-10-08T02:26:06Z", "target_pct": 0.0, "prob_pts": 0.025, "news_added": []}
    cards = [card("ITC", [(1, 0.44, -0.1, big), (3, 0.43, 0.0, big)]), card("TCS", [(1, 0.46, 0.1, small)]),
             card("INFY", [(1, 0.5, 0.2, prob_only)])]
    sources = {"n1": {"title": "One", "url": "https://x.example/1", "source": "Reuters", "ts": "2026-10-08T10:00:00+00:00"},
               "n2": {"title": "Two", "url": None, "source": "Mint", "ts": "2026-10-08T11:00:00+00:00"}}
    out = gather.changes(cards, sources, Statuses(), datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert [r["ticker"] for r in out["by_horizon"]["1"]] == ["ITC", "INFY"]   # TCS's moves are too small
    assert out["since"] == "2026-10-08T02:26:06Z"
    assert [(n["ticker"], n["id"], n["status"]) for n in out["news"]] == [
        ("ITC", "n2", "unverified"), ("ITC", "n1", "corroborated"), ("TCS", "n1", "corroborated")]   # newest first
    assert out["news_total"] == 3


def test_page_assets_are_self_contained_and_use_the_design_tokens():
    css, js = page.css(), page.script()
    assert css.startswith(page.tokens_css()) and "--mb-color-up" in css
    assert not re.search(r"url\(\s*['\"]?(?:https?:)?//", css)
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)[\w.]", js)   # no URL in the script but the SVG namespace
    assert not re.search(r"\b(?:fetch|XMLHttpRequest|import\()", js)
    sprite = page.icons_sprite()
    assert sprite.count("<symbol") == len(page.ICONS) and 'display:none' in sprite
    # light and dark come from B7's token files; the page's own CSS names tokens only (no colour of its own)
    assert ':root[data-theme="dark"]' in css and "prefers-color-scheme: dark" in css
    own = (page.ASSETS / "reader.css").read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", own)
    out = page.render("T <x>", '{"a": 1}', {"s": "</script><b>"})
    assert "<title>T &lt;x&gt;</title>" in out and "<\\/script>" in out and "__JS__" not in out


def test_noscript_fallback_shows_the_numbers_without_javascript():
    from marketbrief.presentation.reader import static
    row = {"h": 1, "exit_label": "Mon 12 Oct", "base_close": 692.25, "target": 690.2143, "lo50": 680.96, "hi50": 697.53,
           "lo80": 672.79, "hi80": 706.37, "move_pct": -0.29, "prob_up": 0.4696, "lean": "down", "strength": "slight",
           "why": "Leans <slightly> down."}
    data = {"symbol": "₹", "companies": [{"ticker": "HDFCBANK", "name": "HDFC Bank", "close": 692.25}],
            "reader": {"default_horizon": 1, "paper_label": "Paper only — no proven edge yet",
                       "mood": {"word": "Calm"}, "benchmark": {"name": "Nifty 50", "change_pct": -1.64, "close_date": "2026-10-08"},
                       "glance": {"1": {"up": 0, "down": 1, "none": 0, "moves": ["HDFCBANK"]}},
                       "companies": [{"ticker": "HDFCBANK", "forecasts": [row],
                                      "flags": [{"code": "earnings", "text": "Results in 3 days: prices can jump"}]}]}}
    out = static.noscript_html(data)
    for needle in ("Market mood: <b>Calm</b>", "Nifty 50: <b>−1.64%</b>", "0 lean up · 0 no clear lean · 1 lean down",
                   "HDFC Bank −0.3% to ₹690.21 by Mon 12 Oct", "HDFC Bank (HDFCBANK): slight lean down",
                   "<td>680.96–697.53</td>", "<td>672.79–706.37</td>", "<td>47%</td>", "Leans &lt;slightly&gt; down.",
                   "Results in 3 days", "Paper only — no proven edge yet"):
        assert needle in out, needle
    assert static.noscript_html({"reader": {}}).startswith("<p>Open this file")


def test_contradicted_tickers_reads_the_status_as_of_the_cutoff():
    import duckdb
    from types import SimpleNamespace
    con = duckdb.connect()
    con.execute("CREATE TABLE s AS SELECT * FROM (VALUES ('n1','ITC','contradicted', TIMESTAMPTZ '2026-10-08 10:00:00+00'),"
                " ('n2','TCS','contradicted', TIMESTAMPTZ '2026-10-09 05:00:00+00'),"   # status set after the cut-off
                " ('n3','INFY','corroborated', TIMESTAMPTZ '2026-10-08 10:00:00+00'),"
                " ('n4','SBIN','contradicted', TIMESTAMPTZ '2026-10-08 10:00:00+00')) t(news_id, ticker, status, as_of)")
    con.execute("CREATE TABLE n AS SELECT * FROM (VALUES ('n1', TIMESTAMPTZ '2026-10-08 09:00:00+00'),"
                " ('n2', TIMESTAMPTZ '2026-10-08 09:00:00+00'), ('n3', TIMESTAMPTZ '2026-10-08 09:00:00+00'),"
                " ('n4', TIMESTAMPTZ '2026-10-01 09:00:00+00')) t(id, first_seen_at)")       # n4: older than 4 days
    con.execute("CREATE MACRO news_status_ids_asof(t) AS TABLE SELECT * FROM s WHERE as_of <= t")
    con.execute("CREATE MACRO news_asof(t) AS TABLE SELECT * FROM n WHERE first_seen_at <= t")
    cutoff = datetime(2026, 10, 9, 3, 30, tzinfo=timezone.utc)
    ctx = SimpleNamespace(con=con, cutoff_time=cutoff, cutoff=cutoff.isoformat())
    assert gather.contradicted_tickers(ctx) == {"ITC"}


def test_change_record_compares_with_the_previous_days_last_runs():
    from marketbrief.presentation.reader import forecasts
    rng = {"target_price": 690.2143}
    sc = {"prob_up": 0.4696, "contributions": {"news": {"ids": ["a", "b", "c"]}}}
    previous = {"ranges": {"target_price": 699.3, "made_at": "2026-10-08T02:26:06Z"},
                "scores": {"prob_up": 0.4706, "news_ids": ["a"], "computed_at": "2026-10-08T02:20:00Z"}}
    out = forecasts.change_record(rng, sc, previous, {"a": {}, "b": {}})
    assert out == {"since": "2026-10-08T02:26:06Z", "target_pct": -1.3, "prob_pts": -0.001, "news_added": ["b"]}
    assert forecasts.change_record(rng, sc, None, {}) is None
    only_score = forecasts.change_record(rng, sc, {"scores": previous["scores"]}, {})
    assert only_score["target_pct"] is None and only_score["since"] == "2026-10-08T02:20:00Z"


def test_previous_day_runs_keeps_the_last_run_per_horizon(monkeypatch):
    from types import SimpleNamespace
    from marketbrief.presentation.reader import forecasts

    class Con:
        def execute(self, sql, params):
            assert params == ["2026-10-09T03:30:00+00:00", "2026-10-08"]
            return SimpleNamespace(fetchone=lambda: ["2026-10-07"])
    seen = {}

    def history(ctx, first, last):
        seen["window"] = (first, last)
        return {"ITC": {"ranges": [{"horizon_days": 1, "made_at": "early"}, {"horizon_days": 1, "made_at": "late"}],
                        "scores": [{"horizon_days": 1, "computed_at": "s1"}]}}
    monkeypatch.setattr(forecasts.company_history, "forecast_history", history)
    ctx = SimpleNamespace(con=Con(), cutoff="2026-10-09T03:30:00+00:00")
    out = forecasts.previous_day_runs(ctx, "2026-10-08")
    assert seen["window"] == ("2026-10-07", "2026-10-07")
    assert out[("ITC", 1)]["ranges"]["made_at"] == "late" and out[("ITC", 1)]["scores"]["computed_at"] == "s1"


def test_paper_status_before_and_after_go_live(monkeypatch):
    from types import SimpleNamespace
    from marketbrief.presentation.reader import paper
    specs = [{"id": "rule.a", "name": "Rule A", "live_from": "2026-10-12"}, {"id": "ai.b", "name": "AI B", "live_from": None}]
    monkeypatch.setattr(paper.registry, "strategies", lambda: specs)
    monkeypatch.setattr(paper.registry, "is_live", lambda spec, day: spec["live_from"] is not None and day >= spec["live_from"])
    ctx = SimpleNamespace(con=None, cutoff_time=None, market="india")
    before = paper.paper_status(ctx, "2026-10-09", {"ITC", "TCS"})
    assert before == {"live": False, "live_from": "2026-10-12", "label": "SIMULATED",
                      "note": "Paper trading (simulated, no real money) starts on Mon 12 Oct."}
    monkeypatch.setattr(paper.registry, "strategies", lambda: [{**specs[0], "live_from": None}])
    assert paper.paper_status(ctx, "2026-10-09", {"ITC"})["note"] == text.PAPER_NO_START
    monkeypatch.setattr(paper.registry, "strategies", lambda: specs)
    trades = [{"ticker": "ITC", "strategy_id": "rule.a", "unrealised_pct": 1.5},
              {"ticker": "ITC", "strategy_id": "rule.a", "unrealised_pct": -0.5},
              {"ticker": "DEL", "strategy_id": "rule.a", "unrealised_pct": 9.0}]          # not active: left out
    monkeypatch.setattr(paper.rm_common, "open_trades", lambda c: trades)
    tiers = {"tiers": [{"ticker": "ITC", "horizon_days": 1, "tier": "Strong Buy"},
                       {"ticker": "ITC", "horizon_days": 3, "tier": "Hold/No call"},
                       {"ticker": "ITC", "horizon_days": 2, "tier": "Sell"},          # N+2 is not shown
                       {"ticker": "TCS", "horizon_days": 5, "tier": "Strong Sell"}]}
    monkeypatch.setattr(paper.signals, "cockpit_payload", lambda *a: tiers)
    monkeypatch.setattr(paper, "load_portfolio_config", lambda: {})
    after = paper.paper_status(ctx, "2026-10-12", {"ITC", "TCS"})
    assert after["live"] is True and after["note"] is None
    assert after["open"] == {"n": 2, "avg_pct": 0.5, "best": 1.5, "worst": -0.5}
    assert after["by_ticker"] == {"ITC": {"n": 2, "avg_pct": 0.5, "best": 1.5, "worst": -0.5}}
    assert after["by_strategy"] == [{"id": "rule.a", "name": "Rule A", "n": 2, "avg_pct": 0.5, "best": 1.5, "worst": -0.5}]
    assert after["tiers"] == {"ITC": {"1": "Strong lean up", "3": "No lean"}, "TCS": {"5": "Strong lean down"}}
    assert not any(w in str(after).lower() for w in ("buy", "sell"))


def test_view_reads_are_bounded_by_the_frozen_clock():
    """view_data.gather_view's stored-row reads (presentation/view_sql.py) see only rows stored by now(), which
    core.database.connect freezes to MB_NOW: a page rebuilt as of a past time shows that time's as-of date."""
    import duckdb
    from marketbrief.core.clock import FrozenClockConnection
    from marketbrief.presentation import view_sql
    raw = duckdb.connect()
    raw.execute("CREATE TABLE ranges_latest AS SELECT * FROM (VALUES ('a', DATE '2026-10-07', TIMESTAMPTZ '2026-10-08 02:26:00+00'),"
                " ('b', DATE '2026-10-08', TIMESTAMPTZ '2026-10-09 02:26:00+00')) t(id, as_of_date, made_at)")
    raw.execute("CREATE TABLE regime AS SELECT * FROM (VALUES (DATE '2026-10-07', 'CALM', TIMESTAMPTZ '2026-10-08 02:00:00+00'),"
                " (DATE '2026-10-08', 'UNSTABLE', TIMESTAMPTZ '2026-10-09 02:00:00+00')) t(as_of_date, regime, computed_at)")
    raw.execute("CREATE TABLE features AS SELECT * FROM (VALUES ('ITC', DATE '2026-10-07', 'OK', TIMESTAMPTZ '2026-10-08 02:00:00+00'),"
                " ('ITC', DATE '2026-10-07', 'BLOCKED', TIMESTAMPTZ '2026-10-09 02:00:00+00')) t(ticker, as_of_date, quality, computed_at)")
    con = FrozenClockConnection(raw, datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc))
    assert con.execute(view_sql.RANGES_SQL).fetchall() == raw.execute("SELECT * FROM ranges_latest WHERE id = 'a'").fetchall()
    assert con.execute(view_sql.REGIME_SQL).fetchall()[0][1] == "CALM"
    assert con.execute(view_sql.FEATURES_SQL, ["2026-10-07"]).fetchall()[0][2] == "OK"   # the later recompute is not seen
    raw.execute("CREATE TABLE predictions AS SELECT * FROM (VALUES ('p1', DATE '2026-10-07', TIMESTAMPTZ '2026-10-08 02:30:00+00'),"
                " ('p2', DATE '2026-10-07', TIMESTAMPTZ '2026-10-09 02:30:00+00')) t(id, as_of_date, made_at)")
    raw.execute("CREATE TABLE filings AS SELECT * FROM (VALUES ('f1', 'ITC', '8-K', 'u', NULL, 'd', TIMESTAMPTZ '2026-10-08 00:00:00+00'),"
                " ('f2', 'ITC', '8-K', 'u', NULL, 'd', TIMESTAMPTZ '2026-10-09 02:00:00+00'))"
                " t(id, ticker, form, url, accepted_at, description, first_seen_at)")
    raw.execute("CREATE TABLE announcements_latest AS SELECT * FROM (VALUES ('a1', 'ITC', 's', 'u', NULL, 'NSE', TIMESTAMPTZ '2026-10-08 00:00:00+00'),"
                " ('a2', 'ITC', 's', 'u', NULL, 'NSE', TIMESTAMPTZ '2026-10-09 02:00:00+00'))"
                " t(id, ticker, subject, url, published_at, source, first_seen_at)")
    raw.execute("CREATE TABLE events AS SELECT * FROM (VALUES"
                " ('e1', DATE '2026-10-12', 'earnings', 'ITC', 'Q2 results', 'nse', TIMESTAMPTZ '2026-10-08 00:00:00+00', NULL),"
                " ('e2', DATE '2026-10-13', 'earnings', 'ITC', 'Q2 results moved', 'nse', TIMESTAMPTZ '2026-10-09 02:00:00+00', NULL),"
                " ('e3', DATE '2026-10-14', 'earnings', 'TCS', 'Q2 results', 'nse', TIMESTAMPTZ '2026-10-09 02:00:00+00', NULL))"
                " t(id, date, type, ticker, name, source, first_seen_at, amount)")
    assert [r[0] for r in con.execute(view_sql.PREDICTIONS_SQL, ["2026-10-07"]).fetchall()] == ["p1"]
    assert [r[0] for r in con.execute(view_sql.FILINGS_SQL).fetchall()] == ["f1"]
    assert [r[0] for r in con.execute(view_sql.ANNOUNCEMENTS_SQL).fetchall()] == ["a1"]
    # the event row first seen by the clock: ITC's earlier date, TCS's event not yet known
    assert con.execute(view_sql.COMPANY_EVENTS_SQL, ["2026-10-08", "2026-10-30"]).fetchall() == [
        (__import__("datetime").date(2026, 10, 12), "earnings", "ITC", "Q2 results", None)]
