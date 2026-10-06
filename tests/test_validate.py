"""Daily-run gates (scripts/validate.py) and the weekly spot-check sample (scripts/spotcheck.py)
on a synthetic US data tree: each check with a passing and a failing case.
Run: pytest -q tests"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
import spotcheck  # noqa: E402
import narrative_numbers as nn  # noqa: E402
import validate as v  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
MARKET = "us"
CFG = common.load_market(MARKET)
NOW = "2026-10-06T12:00:00+00:00"          # Tuesday 08:00 New York: pre-open, previous session 2026-10-05
TODAY = date(2026, 10, 6)
SESSIONS = [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2),
            date(2026, 10, 5)]
TICKERS = list(CFG["tickers"])
GOOD_NEWS_ID, OLD_NEWS_ID = "a1b2c3d4e5f60718", "0f0e0d0c0b0a0908"


def write_jsonl(root: Path, kind: str, day: date, rows: list[dict], raw: str | None = None) -> Path:
    p = root / "data" / MARKET / kind / f"{day:%Y}" / f"{day:%m}" / f"{day}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(raw if raw is not None else "".join(json.dumps(r) + "\n" for r in rows))
    return p


def write_prices(root: Path, day: date, rows: list[tuple[str, float]], collected: str):
    p = root / "data" / MARKET / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(list(common.SCHEMAS["prices"][1]))
        for t, c in rows:
            w.writerow([day, t, c, c, c, c, c, 1000, collected])


def news(nid: str, **kw) -> dict:
    r = {"id": nid, "title": "Apple shares rise 1.2% after the iPhone event", "url": f"https://news.google.com/rss/articles/{nid}",
         "source": "Reuters", "published_at": "2026-10-06T09:00:00+00:00", "first_seen_at": "2026-10-06T11:30:00+00:00",
         "feed": 'gnews:"Apple" stock', "category": "company", "tickers": ["AAPL"]}
    r.update(kw)
    return r


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A clean data tree: bars through the last completed session, today's fetches, features, regime."""
    for i, d in enumerate(SESSIONS):
        collected = NOW.replace("12:00", "11:00") if d == SESSIONS[-1] else f"{d}T22:00:00+00:00"
        write_prices(tmp_path, d, [(k, 100.0 + i) for k in [*TICKERS, *CFG["symbols"]]], collected)
    write_jsonl(tmp_path, "quotes", TODAY, [{"symbol": "ES", "yahoo": "ES=F", "ts": "2026-10-06T11:00:00+00:00",
                                             "price": 5000.0, "prev_close": 4990.0, "change_pct": 0.2,
                                             "collected_at": "2026-10-06T11:00:00+00:00"}])
    write_jsonl(tmp_path, "news", TODAY, [news(GOOD_NEWS_ID)])
    write_jsonl(tmp_path, "news", date(2026, 10, 5), [news(OLD_NEWS_ID, first_seen_at="2026-10-05T11:00:00+00:00",
                                                           published_at="2026-10-05T10:00:00+00:00")])
    write_jsonl(tmp_path, "filings", TODAY, [{"id": "0000320193-26-000001", "ticker": "AAPL", "cik": "320193",
                                              "form": "8-K", "filing_date": "2026-10-05",
                                              "accepted_at": "2026-10-05T20:00:00+00:00", "description": "8-K",
                                              "url": "https://www.sec.gov/x", "first_seen_at": "2026-10-06T11:10:00+00:00"}])
    feats = [{"id": f"2026-10-05-{t}", "as_of_date": "2026-10-05", "ticker": t, "computed_at": "2026-10-06T11:20:00+00:00",
              "close": 105.0, "quality": "BLOCKED" if t == "TSLA" else "OK",
              "days_to_earnings": 1 if t == "JPM" else 20} for t in TICKERS]
    write_jsonl(tmp_path, "features", date(2026, 10, 5), feats)
    write_jsonl(tmp_path, "regime", date(2026, 10, 5), [{"id": "2026-10-05", "as_of_date": "2026-10-05",
                                                         "session_date": "2026-10-06", "computed_at": "2026-10-06T11:20:00+00:00",
                                                         "regime": "CALM", "vol_level": 15.2}])
    (tmp_path / "work").mkdir()
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(v, "ROOT", tmp_path)
    monkeypatch.setattr(spotcheck, "ROOT", tmp_path)
    monkeypatch.setenv("MB_NOW", NOW)
    return tmp_path


def run(stage: str, **paths) -> dict:
    return v.run(CFG, stage, paths)


def codes(out: dict, key: str = "failures") -> dict:
    return {f["code"]: f for f in out[key]}


# ---------- collect ----------

def test_collect_clean_tree_passes(root):
    out = run("collect")
    assert out["ok"], out["failures"]
    assert out["info"]["run"]["previous_session"] == "2026-10-05"


def test_stale_and_missing_bars_block(root):
    p = root / "data" / MARKET / "prices" / "2026" / "10" / "2026-10-05.csv"
    lines = p.read_text().splitlines()
    p.write_bytes(("\r\n".join(x for x in lines if ",AAPL," not in x and ",SPY," not in x) + "\r\n").encode())
    f = codes(run("collect"))
    assert f["STALE_BARS"]["tickers"] == ["AAPL"]
    assert f["STALE_SYMBOL"]["tickers"] == ["SPY"]


def test_late_run_does_not_require_todays_bar(root, monkeypatch):
    monkeypatch.setenv("MB_NOW", "2026-10-06T21:00:00+00:00")   # after the 2026-10-06 close, no bar for it
    out = run("collect")
    assert out["info"]["run"]["late_run"] is True
    assert "STALE_BARS" not in codes(out)
    assert codes(out, "warnings")["LATE_RUN_NO_SESSION_BAR"]["tickers"] == sorted(TICKERS)   # 2026-10-06 closed
    write_prices(root, date(2026, 10, 6), [(t, 106.0) for t in TICKERS], "2026-10-06T20:30:00+00:00")
    assert "LATE_RUN_NO_SESSION_BAR" not in codes(run("collect"), "warnings")


def test_symbols_never_collected_vs_stale(root):
    for p in (root / "data" / MARKET / "prices").glob("**/*.csv"):
        lines = p.read_text().splitlines()
        keep = [x for x in lines if ",VIX," not in x and ",JETS," not in x]
        if p.stem == "2026-10-05":
            keep = [x for x in keep if ",XLF," not in x]
        p.write_bytes(("\r\n".join(keep) + "\r\n").encode())
    out = run("collect")
    assert codes(out)["MISSING_SYMBOL"]["tickers"] == ["VIX"]                 # never collected: blocks
    assert codes(out, "warnings")["MISSING_SYMBOL"]["tickers"] == ["JETS"]    # never collected: warning
    assert "STALE_SYMBOL" not in codes(out, "warnings")                       # XLF 2026-10-02 is within 7 days


def test_empty_truncated_and_bad_json_files_block(root):
    write_jsonl(root, "events", TODAY, [], raw="")
    write_jsonl(root, "options", TODAY, [], raw='{"id": "x", "ticker": "AAPL"')
    f = run("collect")["failures"]
    details = " ".join(x["detail"] for x in f if x["code"] == "BAD_FILE")
    assert "events" in details and "empty file" in details
    assert "options" in details and "truncated" in details


def test_schema_and_timestamps(root):
    write_jsonl(root, "news", TODAY, [news("1111111111111111", extra_field=1),
                                      news("2222222222222222", first_seen_at="2026-10-06 11:30:00"),
                                      news("3333333333333333", published_at="2026-10-07T09:00:00+00:00")])
    d = codes(run("collect"))["SCHEMA"]["detail"]
    assert "extra_field" in d
    assert "not an ISO 8601 UTC timestamp" in d
    assert "in the future" in d


def test_duplicate_ids_block(root):
    write_jsonl(root, "news", TODAY, [news(GOOD_NEWS_ID)])
    assert GOOD_NEWS_ID in codes(run("collect"))["DUPLICATE_ID"]["detail"]


def test_bad_close_blocks_and_big_move_warns(root):
    write_prices(root, date(2026, 10, 5), [("AAPL", 0.0)], "2026-10-06T11:05:00+00:00")
    write_prices(root, date(2026, 10, 5), [("NVDA", 300.0)], "2026-10-06T11:05:00+00:00")
    out = run("collect")
    assert "AAPL" in codes(out)["BAD_CLOSE"]["tickers"]
    assert "NVDA" in codes(out, "warnings")["BIG_MOVE"]["tickers"]


def test_big_move_explained_by_split_event(root):
    write_prices(root, date(2026, 10, 5), [("NVDA", 300.0)], "2026-10-06T11:05:00+00:00")
    write_jsonl(root, "events", TODAY, [{"id": "NVDA-split-2026-10-05", "date": "2026-10-05", "type": "split",
                                         "ticker": "NVDA", "name": "NVIDIA stock split", "source": "test",
                                         "first_seen_at": "2026-10-06T11:00:00+00:00"}])
    assert "BIG_MOVE" not in codes(run("collect"), "warnings")


def test_fetch_freshness_warns(root):
    p = root / "data" / MARKET / "quotes" / "2026" / "10" / "2026-10-06.jsonl"
    p.unlink()
    write_jsonl(root, "quotes", date(2026, 10, 5), [{"symbol": "ES", "ts": "2026-10-05T11:00:00+00:00", "price": 1.0,
                                                     "collected_at": "2026-10-05T11:00:00+00:00"}])
    w = codes(run("collect"), "warnings")
    assert "quotes" in w["NOT_FETCHED"]["detail"]


def test_news_source_rules(root):
    write_jsonl(root, "news", TODAY, [
        news("4444444444444444", url="http://news.google.com/rss/articles/x"),                 # not https
        news("5555555555555555", url="https://evil.example.com/a", feed="Random Blog"),        # unknown feed
        news("6666666666666666", url="https://www.bbc.co.uk/news/x", feed="BBC Business"),     # allowed link domain
        news("7777777777777777", url="https://www.example.com/x", feed="BBC Business")])        # wrong domain
    d = codes(run("collect"))["NEWS_SOURCE"]["detail"]
    assert "4444444444444444" in d and "5555555555555555" in d and "7777777777777777" in d
    assert "6666666666666666" not in d


def test_collector_summaries(root):
    steps = root / "work" / "steps"
    steps.mkdir()
    (steps / "collect_news.json").write_text(json.dumps({"collector": "news", "market": "us", "new_items": 0, "failed": []}))
    (steps / "collect_prices.json").write_text(json.dumps({"collector": "prices", "market": "us", "new_bars": 5,
                                                           "failed": [{"symbol": "AAPL", "error": "timeout"}]}))
    w = codes(run("collect"), "warnings")
    assert "news" in w["EMPTY_OUTPUT"]["detail"]
    assert w["COLLECTOR_FAILED"]["tickers"] == ["AAPL"]
    (steps / "collect_news.json").write_text(json.dumps({"collector": "news", "market": "us", "new_items": 0,
                                                         "failed": [{"feed": "x"}]}))
    assert "EMPTY_OUTPUT" not in codes(run("collect"), "warnings")


# ---------- features / context ----------

def test_features_and_regime(root):
    assert run("features")["ok"]
    assert codes(run("features"), "warnings")["QUALITY_BLOCKED"]["tickers"] == ["TSLA"]
    p = root / "data" / MARKET / "features" / "2026" / "10" / "2026-10-05.jsonl"
    p.write_text("".join(x + "\n" for x in p.read_text().splitlines() if '"AAPL"' not in x))
    (root / "data" / MARKET / "regime" / "2026" / "10" / "2026-10-05.jsonl").unlink()
    f = codes(run("features"))
    assert f["MISSING_FEATURES"]["tickers"] == ["AAPL"]
    assert "MISSING_REGIME" in f


def test_context_pack(root):
    assert "MISSING_CONTEXT" in codes(run("context"))
    pack = root / "work" / "context.md"
    pack.write_text(f"# Context pack: US, {TODAY} (UTC)\n\n## Market regime (latest)\n\n" + " ".join(TICKERS) + "\n")
    assert run("context")["ok"]
    pack.write_text(f"# Context pack: US, {TODAY} (UTC)\n\n## Market regime (latest)\n\n" + " ".join(TICKERS[1:]) + "\n")
    assert codes(run("context"))["CONTEXT_INCOMPLETE"]["tickers"] == [TICKERS[0]]


# ---------- forecast ----------

def call(ticker="AAPL", h=5, **kw) -> dict:
    r = {"id": f"2026-10-05-{ticker}-{h}d", "made_at": "2026-10-06T11:45:00+00:00", "as_of_date": "2026-10-05",
         "ticker": ticker, "horizon_days": h, "direction": "up", "confidence": 0.6, "rationale": "Event coverage.",
         "evidence_ids": [GOOD_NEWS_ID], "prompt_version": "forecast-v8", "range_widen": None}
    r.update(kw)
    return r


def forecast(root, rows) -> dict:
    (root / "work" / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return run("forecast")


def test_forecast_valid_and_absent(root):
    assert run("forecast")["ok"]                                   # no file: abstained
    out = forecast(root, [call(), call(h=1, evidence_ids=["0000320193-26-000001"], direction="down")])
    assert out["ok"], out["failures"]
    assert out["info"]["forecast"] == {"records": 2, "valid": 2}


@pytest.mark.parametrize("rec,word", [
    (call(id="2026-10-05-AAPL-5"), "id must be"),
    (call(direction="flat"), "direction"),
    (call(h=3, id="2026-10-05-AAPL-3d"), "horizon_days"),
    (call(confidence=0.95), "confidence"),
    (call(confidence=0.45), "confidence"),
    (call(range_widen=0.6), "range_widen"),
    (call(as_of_date="2026-10-02", id="2026-10-02-AAPL-5d"), "latest price date"),
    (call(evidence_ids=["ffffffffffffffff"]), "not in the stored"),
    (call(evidence_ids=[GOOD_NEWS_ID], made_at="2026-10-06T08:00:00+00:00"), "published after made_at"),
    (call(ticker="TSLA"), "BLOCKED"),
    (call(ticker="JPM"), "earnings within 1 day"),
    (call(prompt_version=None), "missing prompt_version"),
    (call(made_at=None), "missing made_at"),
    (call(made_at="2026-10-07T11:45:00+00:00"), "in the future"),
])
def test_forecast_rule_violations(root, rec, word):
    f = codes(forecast(root, [rec]))
    assert word in f["FORECAST_RULE"]["detail"], f


def test_forecast_already_stored_and_duplicate_in_file(root):
    write_jsonl(root, "predictions", date(2026, 10, 5), [call(h=1)])
    out = forecast(root, [call(h=1), call(), call()])
    d = " | ".join(x["detail"] for x in out["failures"])
    assert d.count("already recorded") == 2                       # stored before, and repeated in the file


@pytest.mark.parametrize("now,why", [("2026-10-06T21:00:00+00:00", "late run"), ("2026-10-06T14:00:00+00:00", "mid-session run")])
def test_no_calls_on_late_or_mid_session_run(root, monkeypatch, now, why):
    monkeypatch.setenv("MB_NOW", now)
    assert why in codes(forecast(root, [call()]))["CALLS_NOT_ALLOWED"]["detail"]


# ---------- numbers in narrative ----------

ENTS = nn.Entities(CFG)
NAMES = ENTS.mask_names


def nums(text: str) -> list[str]:
    return [n["token"] for n in nn.numbers(text, NAMES, 10)]


def test_number_extraction_skips_dates_ids_and_names():
    text = ("On Oct 5 (2026-10-05) the S&P 500 rose; see a1b2c3d4e5f60718 and nse-ann-12345, "
            "5d range, Q2 results, 2026-W40, at 09:30, item 3 of 4. AAPL 1.2% and $1,310.60.")
    assert nums(text) == ["1.2%", "$1,310.60"]


def test_years_are_ignored_but_amounts_in_the_year_band_are_checked():
    assert nums("ITC fell Rs 1915.85") == ["Rs 1915.85"]
    assert nums("TCS rose 2050.3%") == ["2050.3%"]
    assert nums("a 1950 crore order") == ["1950 crore"]
    assert nums("₹1915.85, $2050 and 1999.5") == ["₹1915.85", "$2050", "1999.5"]
    assert nums("in 2026, FY2026 guidance, on 2026-10-05, by 2030") == []
    pool = pool_of(AAPL=[("plain", 1915.85)])
    assert passes(pool, "AAPL fell to Rs 1915.85 in 2026.")
    assert not passes(pool, "AAPL fell to Rs 1916.85 in 2026.")       # an invented amount in the year band
    assert not passes(pool, "AAPL won a 1950 crore order.")


def pool_of(**scoped) -> nn.Pool:
    """A pool from {scope: [(kind, value), ...]}; scope "market" = market level (None)."""
    pool = nn.Pool(ENTS)
    for scope, vals in scoped.items():
        for kind, val in vals:
            pool.add(None if scope == "market" else scope, kind, val)
    return pool


def passes(pool: nn.Pool, sentence: str) -> bool:
    return not nn.unmatched([sentence], pool, 10)


def test_number_matcher_formatting_variants():
    pool = pool_of(AAPL=[("plain", 1310.6), ("pct", 1.234), ("plain", 35860.0), ("plain", 358600000.0), ("pct", -0.84)],
                   market=[("plain", 22555.75), ("pct", 0.25), ("plain", 101.39), ("plain", 14.71)])
    for text in ["AAPL ₹1,310.60", "AAPL $1,310.6", "AAPL rose 1.2%", "AAPL -1.23%", "AAPL Rs 35.86 cr", "AAPL 35,860", "AAPL fell 0.84%", "22,556", "22,555.75", "a 25 bp hike", "101.4", "14.7"]:
        assert passes(pool, text), text
    for text in ["14.73", "7.77%", "AAPL ₹1,311.60", "AAPL 35,861"]:   # invented or over-precise numbers
        assert not passes(pool, text), text


def test_number_kind_must_match():
    pool = pool_of(AAPL=[("plain", 12.3), ("pct", 105.0)], market=[("plain", 24.8)])
    assert not passes(pool, "AAPL revenue rose 12.3%.")     # a plain 12.3 is not 12.3%
    assert not passes(pool, "AAPL trades at 105.")          # a 105% is not a price of 105
    assert not passes(pool, "Margins were 24.8%.")
    assert passes(pool, "AAPL trades at 12.3.") and passes(pool, "AAPL is up 105%.")


def test_number_scope_follows_the_names_in_the_sentence():
    pool = pool_of(NVDA=[("pct", 12.3)], AAPL=[("pct", 1.2)], market=[("pct", 0.6)])
    assert passes(pool, "NVDA rose 12.3%.") and passes(pool, "Nvidia rose 12.3%.")
    assert not passes(pool, "AAPL rose 12.3%.")              # another company's number
    assert not passes(pool, "Revenue rose 12.3%.")           # names nothing: market level only
    assert passes(pool, "AAPL rose 1.2% while the index rose 0.6%.")
    assert passes(pool, "AAPL rose 1.2%. NVDA rose 12.3%.")  # each sentence its own scope
    assert not passes(pool, "AAPL rose 1.2%; it rose 12.3% last week.")   # line names only AAPL


def test_news_numbers_count_only_for_cited_ids():
    pool = nn.Pool(ENTS)
    pool.add_text("Apple to buy back 4.5% of its shares", scope_by_line=False, scope=("id", GOOD_NEWS_ID))
    assert passes(pool, f"AAPL plans a 4.5% buyback ({GOOD_NEWS_ID}).")
    assert not passes(pool, "AAPL plans a 4.5% buyback.")
    assert not passes(pool, f"AAPL plans a 4.5% buyback ({OLD_NEWS_ID}).")


def test_collector_summaries_are_sources_but_validate_outputs_are_not(root):
    steps = root / "work" / "steps"
    steps.mkdir()
    (steps / "validate_report.json").write_text(json.dumps({"failures": [{"detail": "31 feeds"}], "n": 31}))
    pool = v.build_pool(CFG, common.connect(MARKET), v.load_config(), TODAY, [])
    assert not passes(pool, "News: 31 feeds.")
    (steps / "collect_news.json").write_text(json.dumps({"collector": "news", "feeds": 31, "new_items": 72}))
    pool = v.build_pool(CFG, common.connect(MARKET), v.load_config(), TODAY, [])
    assert passes(pool, "News: 31 feeds, 72 new items.")
    assert passes(pool, "Quotes 15/15, news 31 feeds with 72 new items.")       # the real India lines
    assert not passes(pool, "News: 47 feeds.")
    (steps / "collect_quotes.json").write_text("{not json")
    pool = v.build_pool(CFG, common.connect(MARKET), v.load_config(), TODAY, [])
    assert any("collect_quotes.json" in n for n in pool.notes)                  # noted, not swallowed


def test_planted_invented_percentages_are_caught(root):
    """Realistic invented numbers against real-shaped stored rows (newest features, quotes)."""
    feats = {"AAPL": {"ret_1d": 0.0123, "ret_3d": 0.0177, "ret_5d": -0.0281, "ret_20d": 0.0645, "roc_10": 0.0302,
                      "atr_pct": 0.0187, "realized_vol_10d": 0.214, "ewma_vol": 0.226, "bb_width": 0.0812,
                      "rel_sector_5d": -0.0105, "cue_change_pct": 0.0042, "price_vs_20d_high": 0.9713,
                      "rsi_14": 58.3, "atr_14": 4.12, "beta_1y": 1.21, "volume_ratio_20d": 1.34, "close": 226.4},
             "NVDA": {"ret_1d": 0.123, "atr_pct": 0.035, "ret_5d": 0.091, "realized_vol_10d": 0.248, "close": 181.2}}
    write_jsonl(root, "features", date(2026, 10, 5), [
        {"id": f"2026-10-05-{t}", "as_of_date": "2026-10-05", "ticker": t, "computed_at": "2026-10-06T11:25:00+00:00",
         "quality": "OK", "days_to_earnings": 20, **f} for t, f in feats.items()])
    write_jsonl(root, "quotes", TODAY, [{"symbol": "WTI", "yahoo": "CL=F", "ts": "2026-10-06T11:00:00+00:00",
                                         "price": 61.42, "prev_close": 60.93, "change_pct": 0.0081,
                                         "collected_at": "2026-10-06T11:05:00+00:00"}])
    pool = v.build_pool(CFG, common.connect(MARKET), v.load_config(), TODAY, [])
    invented = ["Apple revenue rose 12.3% in the quarter.", "AAPL's margin was 24.8%.", "Apple guided 3.5% growth.",
                "AAPL profit was up 9.1%.", "AAPL fell 2.7% on the news.", "WTI rose 4.6% overnight.",
                "AAPL gained 1.25%.", "AAPL dropped 18%.", "Revenue rose 12.3% in the quarter.", "Margins were 24.8%."]
    caught = [s for s in invented if not passes(pool, s)]
    assert caught == invented
    real = ["AAPL rose 1.2% and fell 2.8% over five days; its 20-day return is 6.5%.",
            "Apple's RSI is 58.3, beta 1.21, and it trades at 226.40 with volume 1.34x average.",
            "WTI rose 0.8% to 61.42.", "NVDA rose 12.3% (vol 24.8%)."]
    for s in real:
        assert passes(pool, s), s


def test_report_stage_flags_planted_number(root):
    rng = []
    for t in TICKERS:
        for h in (1, 5):
            rng.append({"id": f"2026-10-05-{t}-{h}d", "made_at": "2026-10-06T11:50:00+00:00", "as_of_date": "2026-10-05",
                        "session_date": "2026-10-06", "target_date": "2026-10-06", "ticker": t, "horizon_days": h,
                        "base_close": 105.0, "lo80": 101.5, "hi80": 108.25})
    write_jsonl(root, "ranges", date(2026, 10, 5), rng)
    (root / "work" / "context.md").write_text(f"# Context pack: US, {TODAY} (UTC)\n\n| AAPL | 105.00 | +1.23% |\n")
    skel = "# Brief\n<!-- report-data: as_of=2026-10-05 regime=CALM -->\n## Headline\n<!-- AGENT:headline -->\n| AAPL | $105.00 |\n"
    (root / "work" / "report_us_2026-10-06.skeleton.md").write_text(skel)
    (root / "work" / "slack_us.skeleton.md").write_text("*Brief*\n<!-- AGENT:top3 -->\nCalls today: none.\n")
    (root / "work" / "slack_us.md").write_text("*Brief*\n• AAPL up 1.2% on the iPhone event\nCalls today: none.\n")
    rp = root / "reports" / "us" / "2026-10-06.md"
    rp.parent.mkdir(parents=True)
    good = skel.replace("<!-- AGENT:headline -->", f"AAPL rose 1.2% ({GOOD_NEWS_ID}) to $105.00, inside 101.5-108.25.")
    rp.write_text(good)
    out = run("report")
    assert out["ok"], out["failures"]
    rp.write_text(good.replace("inside", "with a target of $187.40, inside"))
    f = codes(run("report"))
    assert "'$187.40'" in f["UNMATCHED_NUMBER"]["detail"] and f["UNMATCHED_NUMBER"]["tickers"] == ["AAPL"]
    rp.write_text(skel)
    assert "AGENT_MARKERS" in codes(run("report"))


def test_missing_range_blocks_unless_calendar_explains(root, monkeypatch):
    (root / "reports" / "us").mkdir(parents=True)
    f = codes(run("report"))
    assert "MISSING_RANGE" in f and set(f["MISSING_RANGE"]["tickers"]) <= set(TICKERS)
    monkeypatch.setenv("MB_NOW", "2026-10-06T21:00:00+00:00")       # late run: the 1d target closed
    out = run("report")
    d = codes(out)["MISSING_RANGE"]["detail"]
    assert " 5d" in d and " 1d" not in d                             # only the 5-day ranges are unexplained
    assert out["info"]["ranges_skipped"] == {"1d: target 2026-10-06 closed (late run)": len(TICKERS)}


def test_cli_exit_code(root):
    p = root / "data" / MARKET / "prices" / "2026" / "10" / "2026-10-05.csv"
    p.unlink()
    env = {**os.environ, "MB_ROOT": str(root), "MB_NOW": NOW}
    r = subprocess.run([sys.executable, str(SCRIPTS / "validate.py"), "--market", MARKET, "--stage", "collect"],
                       cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is False and "STALE_BARS" in {f["code"] for f in out["failures"]}


# ---------- weekly spot-check ----------

def test_spotcheck_sample_is_deterministic_and_in_week(root):
    calls = [call(ticker=t, made_at=f"2026-09-{d:02d}T11:45:00+00:00", as_of_date=f"2026-09-{d - 1:02d}",
                  id=f"2026-09-{d - 1:02d}-{t}-5d") for d in (29, 30) for t in TICKERS[:4]]
    calls.append(call(ticker="AAPL", made_at="2026-10-06T11:45:00+00:00"))          # outside the week
    write_jsonl(root, "predictions", date(2026, 9, 29), calls)
    for d in ("2026-09-29", "2026-09-30"):
        (root / "reports" / "us").mkdir(parents=True, exist_ok=True)
        (root / "reports" / "us" / f"{d}.md").write_text("# filled\n")
    (root / "reports" / "us" / "2026-10-01.md").write_text("<!-- AGENT:headline -->\n")   # unfilled: never sampled
    a = spotcheck.sample(CFG, "2026-W40")
    b = spotcheck.sample(CFG, "2026-W40")
    assert a == b
    assert len(a["calls"]) == 2 and a["n_calls_in_week"] == 8
    assert all(c["made_at"].startswith("2026-09-") for c in a["calls"])
    assert a["calls"][0]["evidence"][0]["id"] == GOOD_NEWS_ID
    assert len(a["reports"]) == 1 and a["reports"][0] in ("reports/us/2026-09-29.md", "reports/us/2026-09-30.md")
    picks = {tuple(c["id"] for c in spotcheck.sample(CFG, w)["calls"]) for w in ("2026-W40",)}
    assert len(picks) == 1
    assert spotcheck.seed("us", "2026-W40") != spotcheck.seed("us", "2026-W41")


def test_spotcheck_if_due(root):
    env = {**os.environ, "MB_ROOT": str(root), "MB_NOW": NOW}
    cmd = [sys.executable, str(SCRIPTS / "spotcheck.py"), "--market", MARKET, "--if-due"]
    out = json.loads(subprocess.run(cmd, cwd=SCRIPTS, env=env, capture_output=True, text=True, check=True).stdout)
    assert out["due"] is True and out["week"] == "2026-W40" and out["empty"] is True
    assert out["record"]["agent"] == "spotcheck" and "-spotcheck-2026-W40-" in out["record"]["id"]
    write_jsonl(root, "judgments", TODAY, [{**out["record"], "verdict": "SKIP"}])
    out = json.loads(subprocess.run(cmd, cwd=SCRIPTS, env=env, capture_output=True, text=True, check=True).stdout)
    assert out == {"step": "spotcheck", "market": MARKET, "week": "2026-W40", "due": False}
