"""Owner-approved change A: direction calls made from config/settings.yaml call_scoring.from on are scored
open_to_close (buy at the open of D, the first session after the as-of close; sell at the close of D+1 for 1-day
calls and D+4 for 5-day calls), with the same offsets as the signal model's labels (model/labels.py); older calls
stay close_to_close, stored outcomes are never rescored, and summaries never pool the two bases."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.analytics import call_basis, scoring  # noqa: E402
from marketbrief.constants.model import LABEL_CLOSE_TO_CLOSE, LABEL_OPEN_TO_CLOSE  # noqa: E402
from marketbrief.model import labels  # noqa: E402
from test_pipeline import MARKET, run, setup, weekdays  # noqa: E402

SWITCH = "2026-09-15T00:00:00+00:00"
DAYS = weekdays(date(2026, 9, 1), 15)
OPENS = [100.0 + 2 * i for i in range(15)]
CLOSES = [101.0 + 2 * i + (3 if i % 3 == 0 else -1) for i in range(15)]


def write_ohlc(root: Path, opens: list, closes: list) -> None:
    for i, day in enumerate(DAYS):
        p = root / "data" / MARKET / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = [f"{day},{t},{'' if opens[i] is None else opens[i]},{closes[i] + 1},{closes[i] - 5},{closes[i]},"
                f"{closes[i]},1000,2026-09-01T00:00:00+00:00" for t in ("AAPL", "BENCH")]
        p.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n" + "\n".join(rows) + "\n")


def call(i: int, h: int, made_at: str, direction: str = "up") -> dict:
    return {"id": f"{DAYS[i]}-AAPL-{h}d", "made_at": made_at, "as_of_date": str(DAYS[i]), "ticker": "AAPL",
            "horizon_days": h, "direction": direction, "confidence": 0.6, "rationale": "t", "evidence_ids": ["x"],
            "prompt_version": "test"}


@pytest.fixture
def market(tmp_path):
    root, cfg = setup(tmp_path)
    settings = yaml.safe_load((cfg / "settings.yaml").read_text())
    settings["call_scoring"] = {"label_basis": "open_to_close", "from": SWITCH}
    (cfg / "settings.yaml").write_text(yaml.safe_dump(settings))
    return root, cfg


def outcomes(root: Path) -> dict[str, dict]:
    return {o["prediction_id"]: o for f in sorted((root / "data" / MARKET / "outcomes").glob("**/*.jsonl"))
            for o in map(json.loads, f.read_text().splitlines())}


def test_switch_reads_settings_and_defaults_to_close_to_close():
    assert call_basis.switch({}) is None
    assert call_basis.switch({"call_scoring": {"label_basis": "open_to_close"}}) is None
    rule = call_basis.switch({"call_scoring": {"label_basis": "open_to_close", "from": SWITCH}})
    assert rule == (LABEL_OPEN_TO_CLOSE, pd.Timestamp(SWITCH))
    assert call_basis.basis_for("2026-09-14T23:59:59+00:00", rule) == LABEL_CLOSE_TO_CLOSE
    assert call_basis.basis_for(SWITCH, rule) == LABEL_OPEN_TO_CLOSE
    assert call_basis.basis_for(SWITCH, None) == LABEL_CLOSE_TO_CLOSE
    with pytest.raises(SystemExit):
        call_basis.switch({"call_scoring": {"label_basis": "weekly", "from": SWITCH}})
    # the same offsets as the model's labels
    assert [call_basis.target_offset(LABEL_OPEN_TO_CLOSE, h) for h in (1, 5)] == [2, 5]
    assert [call_basis.target_offset(LABEL_CLOSE_TO_CLOSE, h) for h in (1, 5)] == [1, 5]


def test_scoring_bases_match_the_model_labels(market):
    root, cfg = market
    write_ohlc(root, OPENS, CLOSES)
    before, after = "2026-09-02T22:00:00+00:00", "2026-09-15T22:00:00+00:00"   # each after its as-of close
    preds = [call(1, 1, before), call(1, 5, before, "down"),                  # before the switch: close_to_close
             call(9, 1, after), call(9, 5, after, "down")]                    # after: open_to_close
    p = root / "data" / MARKET / "predictions" / "2026" / "09" / "2026-09-30.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("".join(json.dumps(x) + "\n" for x in preds))
    s = run("score_predictions.py", root, cfg)
    assert s.returncode == 0, s.stderr
    summary = json.loads(s.stdout)
    assert (summary["scored"], summary["no_entry_open"]) == (4, 0)
    got = outcomes(root)
    frame = pd.DataFrame({"open": OPENS, "close": CLOSES}, index=pd.to_datetime(DAYS))
    positions = pd.Series(range(len(DAYS)), index=pd.to_datetime(DAYS))
    for x in preds:
        h, i = x["horizon_days"], DAYS.index(date.fromisoformat(x["as_of_date"]))
        basis = LABEL_OPEN_TO_CLOSE if x["made_at"] == after else LABEL_CLOSE_TO_CLOSE
        lab = labels.forward_labels(frame, positions, h)
        ret_col, end_col = labels.label_columns(basis, h)
        o = got[x["id"]]
        assert o["label_basis"] == basis
        assert o["actual_return"] == round(lab[ret_col].iloc[i], 6), x["id"]
        assert o["target_date"] == str(lab[end_col].iloc[i].date())
        assert o["hit"] == ((o["actual_return"] > 0) == (x["direction"] == "up"))
        if basis == LABEL_OPEN_TO_CLOSE:
            assert (o["entry_date"], o["entry_open"]) == (str(DAYS[i + 1]), OPENS[i + 1])
            assert o["target_close"] == CLOSES[i + (2 if h == 1 else 5)]
        else:
            assert "entry_open" not in o and o["base_close"] == CLOSES[i]
    # stored outcomes are never rescored; the summary keeps the bases apart
    again = json.loads(run("score_predictions.py", root, cfg).stdout)
    assert again["scored"] == 0 and set(again["scores"]["calls"]) == {LABEL_CLOSE_TO_CLOSE, LABEL_OPEN_TO_CLOSE}
    assert again["scores"]["calls"][LABEL_OPEN_TO_CLOSE]["all"]["n"] == 2


def test_no_entry_open_no_score_and_old_rows_read_as_close_to_close(market, monkeypatch):
    root, cfg = market
    opens = list(OPENS)
    opens[10] = None                                                        # the entry session has no open
    write_ohlc(root, opens, CLOSES)
    after = "2026-09-15T22:00:00+00:00"
    p = root / "data" / MARKET / "predictions" / "2026" / "09" / "2026-09-30.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(call(9, 1, after)) + "\n" + json.dumps(call(2, 1, "2026-09-03T22:00:00+00:00")) + "\n")
    old = root / "data" / MARKET / "outcomes" / "2026" / "09" / "2026-09-05.jsonl"   # stored before label_basis
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"prediction_id": f"{DAYS[2]}-AAPL-1d", "scored_at": "2026-09-05T00:00:00+00:00",
                               "base_date": str(DAYS[2]), "base_close": CLOSES[2], "target_date": str(DAYS[3]),
                               "target_close": CLOSES[3], "actual_return": 0.01, "hit": True}) + "\n")
    before = old.read_bytes()
    s = json.loads(run("score_predictions.py", root, cfg).stdout)
    assert (s["scored"], s["no_entry_open"], s["still_open"]) == (0, 1, 1)
    assert old.read_bytes() == before and set(outcomes(root)) == {f"{DAYS[2]}-AAPL-1d"}
    import common
    from marketbrief.core.database import connect
    monkeypatch.setattr(common, "ROOT", root)
    rows = connect(MARKET).execute("SELECT id, label_basis FROM track_record").fetchall()
    assert rows == [(f"{DAYS[2]}-AAPL-1d", LABEL_CLOSE_TO_CLOSE)]


def test_markdown_shows_each_basis_apart():
    calls = pd.DataFrame({"label_basis": ["close_to_close"] * 3 + ["open_to_close"] * 2,
                          "horizon_days": [1, 1, 5, 1, 1], "confidence": [0.6, 0.7, 0.6, 0.8, 0.8],
                          "hit": [True, False, True, True, True]})
    out = {"calls": {}, "ranges": {}}
    for basis, group in calls.groupby("label_basis"):
        out["calls"][basis] = {"all": {**scoring.call_scores(group),
                                       "reliability": scoring.reliability(group["confidence"], group["hit"])}}
    text = scoring.markdown(out)
    assert "| close→close | all | 3 |" in text and "| open→close | all | 2 |" in text
    assert "never pooled" in text and "| basis | bin | n |" in text


def test_html_view_reads_the_track_record_as_of_made_at_per_basis():
    """Issue #26 and change A: the HTML view's track record holds only outcomes scored by the day's made_at, and
    its confidence bands are split by basis."""
    import duckdb
    import view_data

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("""CREATE TABLE track_record AS SELECT * FROM (VALUES
        ('a', 0.65, true, 'close_to_close', TIMESTAMPTZ '2026-10-01 10:00:00+00'),
        ('b', 0.65, false, 'open_to_close', TIMESTAMPTZ '2026-10-02 10:00:00+00'),
        ('c', 0.65, true, 'open_to_close', TIMESTAMPTZ '2026-10-09 10:00:00+00'))
        t(id, confidence, hit, label_basis, scored_at)""")
    src = view_data.asof_source(con, "track_record", pd.Timestamp("2026-10-05T12:00:00Z"))
    bands = con.execute(view_data.BANDS_SQL.format(src=src)).fetchall()
    assert [(band, basis, n) for band, basis, n, _, _ in bands] == [
        ("60-69%", "close_to_close", 1), ("60-69%", "open_to_close", 1)]          # 'c' was scored later
    assert view_data.asof_source(con, "track_record", pd.NaT) == "track_record"
    scored = con.execute(view_data.SCORED_CALLS_SQL.format(src=src), ["open_to_close"]).fetchall()
    assert [(float(conf), hit) for conf, hit in scored] == [(0.65, False)]


def test_report_and_slack_name_the_basis():
    from marketbrief.presentation.report.report_parts import track_record_rows
    from marketbrief.presentation.report.slack_text import calls_by_basis

    empty = pd.DataFrame()
    day = {"scorecard": empty, "by_regime": empty, "calibration": empty,
           "direction": pd.DataFrame([{"h": 1, "label_basis": "close_to_close", "win": "since start", "n": 3,
                                       "hit": 0.5, "up": 0.6},
                                      {"h": 1, "label_basis": "open_to_close", "win": "since start", "n": 2,
                                       "hit": 1.0, "up": 0.5}]),
           "conf_bands": pd.DataFrame([{"band": "0.60-0.69", "label_basis": "open_to_close", "n": 2, "conf": 0.65,
                                        "hit": 1.0}])}
    band_rows, _, _, dir_rows, _, _, _ = track_record_rows(day, pd.DataFrame({"quality": []}))
    assert [row[0] for row in dir_rows] == ["1d · close→close", "1d · open→close"]
    assert band_rows == [["0.60-0.69 · open→close", 2, "65%", "100%"]]
    scored = pd.DataFrame({"label_basis": ["open_to_close", "close_to_close", "close_to_close"],
                           "hit": [True, False, True]})
    assert calls_by_basis(scored) == "1/2 close→close, 1/1 open→close"
