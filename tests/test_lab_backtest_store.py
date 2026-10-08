"""B2: the stored F2.3 back-test (`lab.py backtest --store` -> lab_backtests, lab/backtest_store.py) and the model
strategies without news on B10's walk-forward probabilities (lab/backtest_probs.py), on a synthetic data root
(offline): exact columns, ids, idempotent store, nothing stored without --store, the signal mask on the given
probabilities, and no probability from after the clock."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import common
from marketbrief.constants.kinds import KIND_LAB_BACKTESTS
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import backtest_probs, backtest_store, cli, reports

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)      # last complete US session: Tue 6 Oct
BARS = {"AAPL": {"2026-10-02": (100, 101.5, 99, 101), "2026-10-05": (101, 102.5, 100, 102),
                 "2026-10-06": (102, 103.5, 101, 103)},
        "SPY": {"2026-10-02": (500, 501, 499, 500), "2026-10-05": (502, 506, 501, 505),
                "2026-10-06": (505, 506, 504, 505), "2026-10-07": (505, 507, 504, 506)},   # 7 Oct: after the clock
        "EURUSD": {"2026-10-02": (1.1, 1.1, 1.1, 1.10), "2026-10-05": (1.2, 1.2, 1.2, 1.20),
                   "2026-10-06": (1.2, 1.2, 1.2, 1.20)}}
RUN_FIELDS = ("id", "run_id", "market", "computed_at", "as_of_date", "history", "splice", "eurusd_source",
              "probs_source", "note", "data_first_date", "data_last_date", "method_version")
ROW_FIELDS = ("strategy_id", "family", "horizon", "trades", "net_pnl", "mean_return_pct", "win_rate",
              "worst_losing_streak", "max_drawdown", "your_net_pnl", "your_mean_return_pct", "luck_test",
              "sample_badge", "first_entry", "last_exit")


def write_bars(root: Path, bars: dict) -> None:
    for ticker, days in bars.items():
        for day, (o, h, low, c) in days.items():
            path = root / "data" / "us" / "prices" / day[:4] / day[5:7] / f"{day}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            head = "" if path.exists() else "date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
            with path.open("a") as handle:
                handle.write(f"{head}{day},{ticker},{o},{h},{low},{c},{c},1000,{day}T22:30:00+00:00\n")


@pytest.fixture
def root(tmp_path, monkeypatch):
    shutil.copytree(REPO / "config", tmp_path / "config")
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "CONFIG", tmp_path / "config")
    monkeypatch.setenv("MB_NOW", NOW.isoformat())
    write_bars(tmp_path, BARS)
    return tmp_path


def stored_rows() -> list[dict]:
    return connect("us").execute(f"SELECT * FROM {KIND_LAB_BACKTESTS} ORDER BY id").df().to_dict("records")


def test_schema_has_the_promised_columns_and_types():
    columns = SCHEMAS[KIND_LAB_BACKTESTS][1]
    assert list(columns) == [*RUN_FIELDS, *ROW_FIELDS]
    assert (columns["computed_at"], columns["as_of_date"], columns["history"], columns["splice"],
            columns["horizon"], columns["trades"], columns["luck_test"], columns["note"]) == (
        "TIMESTAMPTZ", "DATE", "BOOLEAN", "JSON", "VARCHAR", "INTEGER", "JSON", "VARCHAR")


def test_run_id_and_id_format():
    assert backtest_store.run_id("india", "2026-10-07", False) == "india-2026-10-07-stored"
    assert backtest_store.run_id("us", "2026-10-06", True) == "us-2026-10-06-history"
    assert backtest_store.row_id("us-2026-10-06-history", "base.always_up.v1", "all") == \
        "bt:us-2026-10-06-history:base.always_up.v1:all"


def test_store_writes_the_rows_once(root, capsys):
    assert cli.main(["--market", "us", "backtest", "--store"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["as_of_date"] == "2026-10-06" and out["stored"]["written"] == out["stored"]["rows"] == len(out["rows"])
    rows = stored_rows()
    assert set(rows[0]) == set(RUN_FIELDS) | set(ROW_FIELDS) and len(rows) == len(out["rows"])
    always = next(r for r in rows if r["id"] == "bt:us-2026-10-06-stored:base.always_up.v1:1")
    source = next(r for r in out["rows"] if (r["strategy_id"], r["horizon_days"]) == ("base.always_up.v1", 1))
    assert (always["run_id"], always["horizon"], always["trades"], always["net_pnl"]) == (
        "us-2026-10-06-stored", "1", source["trades"], source["net_pnl"])
    assert (always["your_net_pnl"], always["your_mean_return_pct"]) == (source["your_cost"]["net_pnl"],
                                                                        source["your_cost"]["mean_return_pct"])
    assert always["as_of_date"] == pd.Timestamp("2026-10-06") and not always["history"]
    assert always["probs_source"] is None and always["note"] == out["note"] and "model-only not run" in out["note"]
    assert always["data_last_date"] == pd.Timestamp("2026-10-06") and always["eurusd_source"] == "stored EURUSD closes"
    assert {r["horizon"] for r in rows} == {"1", "all"}          # 3 sessions: only N+1 trades fit
    files = sorted((root / "data" / "us" / KIND_LAB_BACKTESTS).rglob("*.jsonl"))
    assert [f.name for f in files] == ["2026-10-06.jsonl"]       # the day file of computed_at
    before = files[0].read_text()
    assert cli.main(["--market", "us", "backtest", "--store"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["stored"] == {"rows": len(out["rows"]), "written": 0} and files[0].read_text() == before


def test_no_store_without_the_flag(root, capsys):
    assert cli.main(["--market", "us", "backtest"]) == 0
    assert "stored" not in json.loads(capsys.readouterr().out)
    assert not (root / "data" / "us" / KIND_LAB_BACKTESTS).exists() and stored_rows() == []


def probs_on(day: str, p: float) -> dict:
    return {("AAPL", 1): pd.Series([p], index=pd.DatetimeIndex([day]))}


@pytest.mark.usefixtures("root")
def test_model_only_rows_use_the_given_probabilities(monkeypatch):
    cfg = load_market("us")
    monkeypatch.setattr(backtest_probs, "model_probs",
                        lambda *_a: (probs_on("2026-10-02", 0.60), "walk_forward:logit-v1", None))
    out = reports.run_backtest(connect("us"), cfg, NOW, history=False)
    assert (out["probs_source"], out["note"]) == ("walk_forward:logit-v1", None)
    by = {(r["strategy_id"], r["horizon_days"]): r for r in out["rows"]}
    model = by[("base.model_only.v1", 1)]
    assert (model["trades"], model["first_entry"], model["last_exit"]) == (1, "2026-10-05", "2026-10-06")
    assert not any(sid.startswith("rule.") for sid, _ in by)    # every rule strategy needs news
    monkeypatch.setattr(backtest_probs, "model_probs",
                        lambda *_a: (probs_on("2026-10-02", 0.54), "walk_forward:logit-v1", None))
    low = reports.run_backtest(connect("us"), cfg, NOW, history=False)
    assert next(r for r in low["rows"] if (r["strategy_id"], r["horizon_days"]) == ("base.model_only.v1", 1))[
        "trades"] == 0                                          # below the 0.55 threshold: no trade


@pytest.mark.usefixtures("root")
def test_walk_forward_probabilities_stop_at_the_clock(monkeypatch):
    cfg = load_market("us")
    seen = {}

    def fake_panel(_cfg, inputs, _warmup, _groups):
        seen["last_bar"] = inputs["bars"]["SPY"].index.max()
        return pd.DataFrame({"date": pd.to_datetime(["2026-10-05"]), "ticker": ["AAPL"]})

    def fake_walk_forward(_panel, spec, _settings, until=None):
        seen.setdefault("until", set()).add(until)
        seen.setdefault("spec", set()).add(spec[:2])
        days = pd.to_datetime(["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"])
        return pd.DataFrame({"date": days, "ticker": ["AAPL"] * 4, "prob": [0.6, 0.7, 0.8, 0.9]}), []

    monkeypatch.setattr(backtest_probs, "build_panel", fake_panel)
    monkeypatch.setattr(backtest_probs, "walk_forward", fake_walk_forward)
    probs, source, note = backtest_probs.model_probs(connect("us"), cfg, NOW)
    assert seen["last_bar"] == pd.Timestamp("2026-10-06")         # the 7 Oct bar is after the clock: cut
    assert seen["until"] == {pd.Timestamp("2026-10-06")} and seen["spec"] == {("us", "open_to_close")}
    assert sorted(k for _, k in probs) == [1, 2, 3, 4, 5] and (source, note) == ("walk_forward:logit-v1", None)
    assert list(probs[("AAPL", 1)].index) == list(pd.to_datetime(["2026-10-02", "2026-10-05", "2026-10-06"]))


@pytest.mark.usefixtures("root")
def test_no_fit_gives_no_probabilities_and_a_note():
    probs, source, note = backtest_probs.model_probs(connect("us"), load_market("us"), NOW)
    assert (probs, source) == ({}, None) and note == backtest_probs.MSG_NO_MODEL_FIT.format(need=100)
