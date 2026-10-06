"""The marketbrief package: core (paths, clock, schemas, market config, storage, database, cli) and utils.
The old flat module `common` must keep forwarding to it."""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.constants.messages import MSG_MARKET_REQUIRED  # noqa: E402
from marketbrief.core import cli, clock, database, market_config, paths, schemas, storage  # noqa: E402
from marketbrief.utils import event_dates, markdown, money, numbers, sessions, text, timefmt  # noqa: E402

REAL_CONFIG = Path(__file__).resolve().parents[1] / "config"


# ---------- the common shim ----------

def test_common_root_and_config_are_the_package_paths(monkeypatch, tmp_path):
    original_root, original_config = paths.ROOT, paths.CONFIG
    assert common.ROOT == original_root and common.CONFIG == original_config and common.CODE == paths.CODE
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "CONFIG", tmp_path / "cfg")
    assert paths.ROOT == tmp_path and paths.CONFIG == tmp_path / "cfg"
    assert common.data_dir("us") == tmp_path / "data" / "us" and paths.data_dir("us") == tmp_path / "data" / "us"
    monkeypatch.undo()
    assert paths.ROOT == original_root and paths.CONFIG == original_config


def test_common_reexports_every_name_callers_use():
    for name in ("ACCEPTED_KEYS", "FEATURE_COLS", "RELATION_SCHEMAS", "SCHEMAS", "STALE_DAYS", "FrozenClockConnection",
                 "append_jsonl", "benchmark_key", "clock", "connect", "data_dir", "day_file", "freeze_sql",
                 "load_market", "load_ranges_config", "market_arg", "market_names", "md_table", "recent_ids",
                 "require_market", "sector_etf_map", "sector_etf_problems", "symbols_by_role", "utc_now",
                 "utc_today", "vol_index_key"):
        assert hasattr(common, name), name
    assert common.STALE_DAYS == 7 and common.md_table is markdown.cursor_markdown_table


# ---------- schemas ----------

def test_schemas_join_the_three_tables_and_merge_the_relationship_kinds():
    built = schemas.build_schemas()
    assert list(built) == list(schemas.SCHEMAS)
    assert all(fmt == "jsonl" or fmt == "csv" for fmt, _ in built.values())
    us_columns = {"accession", "insider_name", "is_director"}
    india_columns = {"person", "person_category", "trade_from"}
    assert us_columns | india_columns <= set(built["insiders"][1])   # one kind, both markets' columns
    assert built["holdings"][1]["accession"] == "VARCHAR" and "promoter_pct" in built["holdings"][1]
    assert set(built["sec_times"][1]) == {"accession", "cik", "accepted_at", "json_accepted_at", "source", "checked_at"}
    assert set(schemas.ACCEPTED_KEYS) == {"filings", "insiders", "stakes", "holdings", "fundamentals"}
    assert set(schemas.ACCEPTED_KEYS) <= set(built) and "graph_runs" in built and "macro" in built


# ---------- clock ----------

def test_clock_follows_mb_now_and_needs_an_offset(monkeypatch):
    monkeypatch.setenv("MB_NOW", "2026-07-02T12:15:00Z")
    assert clock.clock() == datetime(2026, 7, 2, 12, 15, tzinfo=timezone.utc)
    assert clock.utc_now() == "2026-07-02T12:15:00+00:00" and clock.utc_today() == date(2026, 7, 2)
    monkeypatch.setenv("MB_NOW", "2026-07-02T12:15:00")
    with pytest.raises(SystemExit) as error:
        clock.clock()
    assert str(error.value) == ("MB_NOW needs a UTC offset, e.g. 2026-07-02T12:15:00+00:00 "
                                "(got '2026-07-02T12:15:00')")
    monkeypatch.delenv("MB_NOW")
    assert clock.clock().tzinfo is not None


def test_freeze_sql_replaces_every_clock_function():
    at = datetime(2026, 7, 2, 12, 15, tzinfo=timezone.utc)
    sql = clock.freeze_sql("SELECT current_date, CURRENT_DATE(), now(), current_timestamp, get_current_timestamp()", at)
    assert sql == ("SELECT DATE '2026-07-02', DATE '2026-07-02', TIMESTAMPTZ '2026-07-02T12:15:00+00:00', "
                   "TIMESTAMPTZ '2026-07-02T12:15:00+00:00', TIMESTAMPTZ '2026-07-02T12:15:00+00:00'")


# ---------- market config and cli ----------

def write_market(config_dir: Path, name: str, doc: dict) -> None:
    (config_dir / "markets").mkdir(parents=True, exist_ok=True)
    (config_dir / "markets" / f"{name}.yaml").write_text(yaml.safe_dump(doc))


def test_load_market_fills_defaults_and_maps_sector_etfs(monkeypatch, tmp_path):
    write_market(tmp_path, "demo", {
        "tickers": {"AAA": {"name": "A"}, "BBB": {"name": "B", "yahoo": "BBB.X"}},
        "sectors": {"tech": ["AAA"], "bank": ["BBB"]},
        "symbols": {"IDX": {"role": "benchmark"}, "VIX": {"role": "vol_index"},
                    "XLK": {"role": "sector_etf", "sectors": ["tech"]}}})
    monkeypatch.setattr(paths, "CONFIG", tmp_path)
    cfg = market_config.load_market("demo")
    assert cfg["market"] == "demo" and cfg["tickers"]["AAA"]["yahoo"] == "AAA"
    assert cfg["tickers"]["BBB"]["yahoo"] == "BBB.X" and cfg["tickers"]["AAA"]["sector"] == "tech"
    assert cfg["sector_etfs"] == {"tech": "XLK"} and cfg["tickers"]["AAA"]["sector_etf"] == "XLK"
    assert cfg["tickers"]["BBB"]["sector_etf"] is None
    assert market_config.benchmark_key(cfg) == "IDX" and market_config.vol_index_key(cfg) == "VIX"
    assert list(market_config.symbols_by_role(cfg, "sector_etf")) == ["XLK"]
    assert market_config.market_names() == ["demo"]
    with pytest.raises(SystemExit) as error:
        market_config.load_market("nope")
    assert str(error.value) == "unknown market 'nope'; available: ['demo']"


def test_sector_etf_problems_name_each_mistake():
    cfg = {"sectors": {"tech": [], "bank": []}, "symbols": {
        "A": {"role": "sector_etf", "sectors": ["tech"]}, "B": {"role": "sector_etf", "sectors": ["tech", "ghost"]},
        "C": {"role": "cue", "sectors": ["bank"]}}}
    assert market_config.sector_etf_problems(cfg) == [
        "sector 'tech' is mapped to both A and B", "symbol B: unknown sector 'ghost'",
        "symbol C: `sectors` is only for role sector_etf"]


def test_ranges_config_by_market_replaces_the_base_setting(monkeypatch, tmp_path):
    (tmp_path / "ranges.yaml").write_text(yaml.safe_dump({"factor": 1, "factor_by_market": {"us": 2}, "other": 3}))
    monkeypatch.setattr(paths, "CONFIG", tmp_path)
    assert market_config.load_ranges_config()["factor"] == 1
    assert market_config.load_ranges_config("us")["factor"] == 2
    assert market_config.load_ranges_config("india")["factor"] == 1


def test_require_market_exits_with_the_available_markets(monkeypatch):
    monkeypatch.delenv("MB_MARKET", raising=False)
    parser = cli.market_arg("demo")
    args = parser.parse_args([])
    with pytest.raises(SystemExit) as error:
        cli.require_market(args)
    assert str(error.value) == MSG_MARKET_REQUIRED.format(available=market_config.market_names())
    assert cli.require_market(parser.parse_args(["--market", "us"]))["market"] == "us"
    monkeypatch.setenv("MB_MARKET", "india")
    assert cli.market_arg().parse_args([]).market == "india"


# ---------- storage and database ----------

def test_storage_appends_never_rewrites_and_reads_recent_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    first = storage.day_file("us", "news", date(2026, 10, 5))
    assert first == tmp_path / "data" / "us" / "news" / "2026" / "10" / "2026-10-05.jsonl" and first.parent.is_dir()
    assert storage.append_jsonl(first, [{"id": "a", "n": 1}, {"id": "b", "n": "é"}]) == 2
    assert storage.append_jsonl(first, []) == 0
    storage.append_jsonl(first, [{"id": "c"}])
    assert [json.loads(line)["id"] for line in first.read_text(encoding="utf-8").splitlines()] == ["a", "b", "c"]
    assert storage.recent_ids("us", "news", days=7) == {"a", "b", "c"}
    assert storage.day_file("us", "prices", date(2026, 10, 5)).suffix == ".csv"
    assert storage.day_file("us", "prices", date(2026, 10, 5), ext="x").suffix == ".x"
    assert storage.recent_ids("us", "filings", days=7) == set()


def test_connect_builds_empty_tables_and_views_over_stored_files(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "CONFIG", REAL_CONFIG)
    storage.append_jsonl(storage.day_file("us", "sec_times", date(2026, 10, 5)), [
        {"accession": "0001-26-000001", "cik": "1", "accepted_at": "2026-10-05T13:00:00Z",
         "json_accepted_at": "2026-10-05T17:00:00Z", "source": "t", "checked_at": "2026-10-05T20:00:00Z"}])
    storage.append_jsonl(storage.day_file("us", "filings", date(2026, 10, 5)), [
        {"id": "0001-26-000001", "ticker": "AAA", "accepted_at": "2026-10-05T17:00:00Z"},
        {"id": "0001-26-000002", "ticker": "AAA", "accepted_at": "2026-10-05T18:00:00Z"}])
    con = database.connect("us")
    rows = con.execute("SELECT id, strftime(accepted_at, '%H:%M') FROM filings ORDER BY id").fetchall()
    assert rows == [("0001-26-000001", "13:00"), ("0001-26-000002", "18:00")]   # the header's time where checked
    assert con.execute("SELECT count(*) FROM insiders").fetchone() == (0,)      # no files: an empty table
    assert con.execute("SELECT count(*) FROM news").fetchone() == (0,)


def test_connect_without_a_market_config_keeps_stored_news_tags(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "CONFIG", REAL_CONFIG)
    storage.append_jsonl(storage.day_file("nomarket", "news", date(2026, 10, 5)), [
        {"id": "n1", "title": "t", "url": "u", "source": "s", "tickers": ["AAA"],
         "first_seen_at": "2026-10-05T10:00:00Z",
         "primary_tickers": ["AAA"], "mentioned_tickers": [], "tag_confidence": "high"}])
    con = database.connect("nomarket")
    assert con.execute("SELECT id, tickers FROM news").fetchall() == [("n1", ["AAA"])]


# ---------- utils ----------

def test_the_number_parsers_differ_where_the_sources_differ():
    assert numbers.parse_nse_number("1,234.5") == 1234.5 and numbers.parse_nse_number("12%") == 12.0
    assert numbers.parse_nse_number("0") == 0.0 and numbers.parse_nse_number("-") is None
    assert numbers.parse_nse_number(True) is None and numbers.parse_nse_number(3) == 3.0
    assert numbers.parse_amount_with_accounting_negatives("(12.5)") == -12.5
    assert numbers.parse_amount_with_accounting_negatives("Rs. 1,000") == 1000.0
    assert numbers.parse_amount_with_accounting_negatives("12%") is None
    assert numbers.parse_amount_with_accounting_negatives(".") is None
    assert numbers.parse_amount_with_accounting_negatives(True) is None
    assert numbers.parse_sec_number("1,234.5") == 1234.5 and numbers.parse_sec_number("") is None
    assert numbers.parse_sec_number(None) is None and numbers.parse_sec_number("abc") is None
    assert numbers.json_safe_float(float("nan")) is None and numbers.json_safe_float(None) is None
    assert numbers.json_safe_float(2.34567, 2) == 2.35 and numbers.json_safe_float(pd.NA) is None


def test_rounding_and_percent_text_helpers():
    assert numbers.round_finite_or_none(1.23456) == 1.2346 and numbers.round_finite_or_none(1.23456, 1) == 1.2
    assert numbers.round_finite_or_none(None) is None and numbers.round_finite_or_none(math.inf) is None
    assert numbers.round_finite_or_none(float("nan")) is None and numbers.round_finite_or_none(3) == 3.0
    assert numbers.share_percent_text(0.625, 0) == "62%" and numbers.share_percent_text(0.625, 1) == "62.5%"
    assert numbers.share_percent_text(None, 1) == "n/a"


def test_replay_and_ai_replay_keep_their_percent_defaults():
    import ai_replay
    import replay
    assert replay.pct(0.456) == "46%" and replay.pct(0.456, 1) == "45.6%" and replay.pct(None) == "n/a"
    assert ai_replay.pct(0.456) == "45.6%" and ai_replay.pct(0.456, 0) == "46%" and ai_replay._f(0.456) == "45.6%"


def test_text_markdown_and_money_helpers():
    assert text.slugify("Hello, World & Co.!") == "hello-world-co" and text.slugify("***") == ""
    assert text.slugify_with_unknown_fallback(None) == "unknown"
    assert text.slugify_with_unknown_fallback("***") == "unknown"
    assert text.slugify_with_unknown_fallback("A b") == "a-b"
    assert markdown.markdown_table(["A", "B"], [[1, None]]) == "| A | B |\n|---|---|\n| 1 | None |\n"
    assert markdown.markdown_table(["A"], []) == "_none_\n"
    assert money.format_money("USD", 1234.5) == "$1,234.50" and money.format_money("INR", 2) == "₹2.00"
    assert money.format_money("EUR", 1) == "1.00" and money.format_money("USD", None) == "–"
    assert money.format_money("USD", float("nan")) == "–"


def test_major_event_between_is_after_the_as_of_day_and_up_to_the_target():
    majors = [date(2026, 10, 2), date(2026, 10, 12)]
    assert not event_dates.major_event_between(majors, date(2026, 10, 2), date(2026, 10, 9))   # on the as-of day: known
    assert event_dates.major_event_between(majors, date(2026, 10, 1), date(2026, 10, 2))       # on the target day
    assert not event_dates.major_event_between(majors, date(2026, 10, 3), date(2026, 10, 11))
    assert not event_dates.major_event_between([], date(2026, 9, 25), date(2026, 10, 1))


def test_timestamp_helpers():
    assert timefmt.as_utc_timestamp("2026-10-05T10:00:00") == pd.Timestamp("2026-10-05T10:00:00", tz="UTC")
    assert timefmt.as_utc_timestamp("2026-10-05T10:00:00+05:30") == pd.Timestamp("2026-10-05T04:30:00", tz="UTC")
    assert timefmt.as_utc_timestamp("") is None and timefmt.as_utc_timestamp("junk") is None
    assert timefmt.as_utc_timestamp(None) is None and timefmt.as_utc_timestamp(pd.NaT) is None
    instant = timefmt.parse_utc_z("2026-07-14T10:30:38.000Z")
    assert instant == datetime(2026, 7, 14, 10, 30, 38, tzinfo=timezone.utc)
    assert timefmt.format_utc_z(instant) == "2026-07-14T10:30:38.000Z"


def test_session_lists_answer_different_questions():
    cfg = market_config.load_market("us")
    assert sessions.last_completed_sessions(cfg, date(2026, 10, 6), 3) == [date(2026, 10, 1), date(2026, 10, 2),
                                                                           date(2026, 10, 5)]
    assert sessions.sessions_in_window(cfg, date(2026, 10, 6), 5) == [date(2026, 10, 1), date(2026, 10, 2),
                                                                      date(2026, 10, 5), date(2026, 10, 6)]
