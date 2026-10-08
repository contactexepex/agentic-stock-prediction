"""The traders' gate inputs (B3, issue #139): a snapshot recomputed after made_at keeps its first computation time,
B10's as-of readers are never read after the gate's clock, and load_inputs hands made_at to them. Offline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import duckdb
from traders_fixtures import AS_OF, NOW, PROMPTS, agent_record, inputs, published_range, score

from marketbrief.traders import inputs as trader_inputs
from marketbrief.traders.gate import check_record
from marketbrief.traders.registry import trader

NEWS, PATTERN, COMBINED, OPUS = PROMPTS
FIRST = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)
RECOMPUTED = datetime(2026, 10, 7, 11, 48, tzinfo=timezone.utc)   # after MADE_AT 11:45, before NOW 11:50


def snapshot_con():
    """features and regime of NVDA as of AS_OF, computed at 11:00 and again at 11:48."""
    con = duckdb.connect()
    con.execute("CREATE TABLE features (ticker VARCHAR, as_of_date DATE, quality VARCHAR, days_to_earnings INTEGER,"
                " computed_at TIMESTAMPTZ)")
    con.execute("CREATE TABLE regime (as_of_date DATE, regime VARCHAR, computed_at TIMESTAMPTZ)")
    for when, quality in ((FIRST, "OK"), (RECOMPUTED, "OK")):
        con.execute("INSERT INTO features VALUES ('NVDA', ?, ?, 30, ?)", [AS_OF, quality, when])
        con.execute("INSERT INTO regime VALUES (?, 'TRENDING', ?)", [AS_OF, when])
    return con


def test_recomputed_snapshot_keeps_its_first_computation_time():
    """C1: a features or regime snapshot recomputed between made_at and the gate existed by made_at."""
    con = snapshot_con()
    feats, regimes = trader_inputs.stored_features(con, NOW), trader_inputs.stored_regimes(con, NOW)
    assert feats["NVDA"]["computed_at"] == FIRST and regimes[AS_OF] == ("TRENDING", FIRST)
    gi = inputs(features=feats, regimes=regimes)
    for evidence in (f"features:{AS_OF}-NVDA", f"regime:{AS_OF}"):
        verdict = check_record(agent_record(PATTERN, evidence_ids=[evidence]), trader(PATTERN), gi, set())
        assert verdict.errors == [], evidence
    before = NOW.replace(hour=10)
    assert trader_inputs.stored_features(con, before) == {} and trader_inputs.stored_regimes(con, before) == {}


def test_as_of_readers_are_never_read_after_the_clock():
    """C2: a made_at inside the 5-minute future tolerance reads ranges and scores at the gate's clock."""
    asked = []

    def at(table):
        def read(when):
            asked.append(when)
            return table
        return read

    gi = inputs(ranges_at=at(inputs().ranges), scores_at=at(inputs().scores))
    made = (NOW + timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
    verdict = check_record(agent_record(COMBINED, made_at=made), trader(COMBINED), gi, set())
    assert verdict.errors == [] and asked and all(when == NOW for when in asked)


def test_load_inputs_hands_made_at_to_the_horizon_readers(monkeypatch):
    """C3: load_inputs wires B10's ranges_asof / scores_asof so the gate reads them at made_at."""
    asked = {"ranges": [], "scores": []}

    def reader(kind, rows):
        def read(market, when):
            assert market == "us"
            asked[kind].append(when)
            return rows
        return read

    monkeypatch.setattr(trader_inputs.horizons, "ranges_asof", reader("ranges", [published_range(1)]))
    monkeypatch.setattr(trader_inputs.horizons, "scores_asof", reader("scores", [score(1)]))
    monkeypatch.setattr(trader_inputs, "evidence_times", lambda _con: inputs().evidence)
    monkeypatch.setattr(trader_inputs, "EvidenceStatuses", lambda _con: inputs().statuses)
    monkeypatch.setattr(trader_inputs.track_record, "load", lambda _con, _now: {})
    con = snapshot_con()
    con.execute("CREATE TABLE strategy_predictions (id VARCHAR)")
    con.execute("CREATE TABLE strategy_abstentions (id VARCHAR)")
    gi = trader_inputs.load_inputs({**inputs().cfg, "active_tickers": ["NVDA"]}, NOW, con)
    for kind in asked:
        asked[kind].clear()
    rec = agent_record(COMBINED, horizon=1)
    verdict = check_record(rec, trader(COMBINED), gi, set())
    made = datetime.fromisoformat(rec["made_at"].replace("Z", "+00:00"))
    assert verdict.errors == [] and asked == {"ranges": [made], "scores": [made]}
