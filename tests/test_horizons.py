"""Horizons N+1..N+5 (docs/SPEC.md F2.7, decision 37; session B10): the horizon list from config/strategies.yaml,
the N+k window through the market calendar, legacy labels on read, and the per-horizon records as of a time
(marketbrief/contracts/horizons.py)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from marketbrief.contracts import horizons as contract  # noqa: E402
from marketbrief.core import horizons as hz  # noqa: E402
from marketbrief.core import paths  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_ranges_config  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.model import context_section, daily_scores  # noqa: E402
from test_pipeline import MARKET, setup  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
US = {"market": "us", "calendar": "XNYS", "timezone": "America/New_York"}
INDIA = {"market": "india", "calendar": "XBOM", "timezone": "Asia/Kolkata"}


# ---------- the horizon list ----------

def test_horizon_list_comes_from_the_strategy_registry():
    registry = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    assert hz.horizons() == tuple(registry["horizons"]) == (1, 2, 3, 4, 5)
    assert hz.ai_horizons() == tuple(registry["ai_horizons"])
    assert contract.horizons() == hz.horizons()
    # config/ranges.yaml no longer sets its own list; the loader fills it from strategies.yaml
    assert "horizons" not in yaml.safe_load((REPO / "config" / "ranges.yaml").read_text())
    assert load_ranges_config("us")["horizons"] == list(hz.horizons())


def test_horizon_list_is_a_setting(tmp_path, monkeypatch):
    """Adding N+10 is a config change: the list is read at call time from the current config folder."""
    (tmp_path / "strategies.yaml").write_text("horizons: [1, 5, 10]\nai_horizons: [1, 10]\n")
    (tmp_path / "ranges.yaml").write_text((REPO / "config" / "ranges.yaml").read_text())
    monkeypatch.setattr(paths, "CONFIG", tmp_path)
    assert hz.horizons() == (1, 5, 10) and hz.ai_horizons() == (1, 10)
    assert load_ranges_config()["horizons"] == [1, 5, 10]
    (tmp_path / "ranges.yaml").write_text("horizons: [1]\n")                # a test config may pin its own list
    assert load_ranges_config()["horizons"] == [1]
    for bad in ("horizons: [5, 1]", "horizons: [1, 1]", "horizons: [0, 1]", "horizons: []", "horizons: [1.5]",
                "horizons: [true]", "other: 1"):
        (tmp_path / "strategies.yaml").write_text(bad + "\n")
        with pytest.raises(SystemExit):
            hz.horizons()


# ---------- the N+k window ----------

@pytest.mark.parametrize("cfg, as_of, entry, exits", [
    # as of Thu 2026-10-08: D = Fri 10-09, N+1 = Mon 10-12 (bought Friday, N+1 = Monday's close; decision 37)
    (US, date(2026, 10, 8), "2026-10-09", ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]),
    # as of Wed 2026-11-25: Thanksgiving skipped, D = Fri 11-27
    (US, date(2026, 11, 25), "2026-11-27", ["2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04"]),
    # India as of Thu 2026-10-01: Gandhi Jayanti (Fri 10-02) skipped, D = Mon 10-05
    (INDIA, date(2026, 10, 1), "2026-10-05", ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
                                               "2026-10-12"]),
])
def test_entry_and_exit_follow_the_market_calendar(cfg, as_of, entry, exits):
    for k, exit_day in zip(hz.horizons(), exits, strict=True):
        assert tuple(map(str, hz.entry_exit(cfg, as_of, k))) == (entry, exit_day)
        assert hz.exit_offset(k) == hz.window_sessions(k) == k + 1


def test_legacy_labels_and_summary_keys():
    assert hz.legacy_label("ranges", 1) == hz.legacy_label("ranges", 5) == "legacy_cc"
    assert hz.legacy_label("model_scores", 1) == "n_plus_k"                    # open of D -> close of D+1 = N+1
    assert hz.legacy_label("model_scores", 5) == "legacy_5d_d4"
    assert hz.legacy_label("outcomes", 5, "close_to_close") == hz.legacy_label("outcomes", 1) == "legacy_cc"
    assert hz.legacy_label("outcomes", 1, "open_to_close") == "n_plus_k"
    assert hz.legacy_label("outcomes", 5, "open_to_close") == "legacy_5d_d4"
    assert hz.horizon_key(3, "n_plus_k") == hz.horizon_key(3) == "3d"
    assert hz.horizon_key(1, "legacy_cc") == "1d legacy_cc"
    assert contract.HORIZON_LABELS == ("n_plus_k", "legacy_cc", "legacy_5d_d4")


def test_new_columns_are_in_the_schemas():
    for kind in ("model_scores", "ranges"):
        assert {"horizon_label", "entry_date", "exit_date"} <= set(SCHEMAS[kind][1])
    for kind in ("outcomes", "calibration", "model_versions"):
        assert "horizon_label" in SCHEMAS[kind][1]
    assert {"decision_2d", "decision_3d", "decision_4d"} <= set(SCHEMAS["agent_reasoning"][1])


def test_n_plus_5_never_reuses_a_stored_d_plus_4_fit():
    """The stored 5-day fits of the old label carry ids with open_to_close; N+5 fits get n_plus_k ids, N+1 keeps
    its id (same label as before)."""
    assert daily_scores.version_id("us", 1, "logit-v1", "2026-10-01") == "us-1d-open_to_close-logit-v1-2026-10-01"
    assert daily_scores.version_id("us", 5, "logit-v1", "2026-10-01") == "us-5d-n_plus_k-logit-v1-2026-10-01"
    assert daily_scores.version_id("us", 3, "logit-v1", "2026-10-01") == "us-3d-n_plus_k-logit-v1-2026-10-01"


# ---------- labels on read and the records as of a time ----------

def jsonl(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    p = root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def score(as_of: str, h: int, prob: float, computed_at: str, **extra) -> dict:
    return {"id": f"{as_of}-AAPL-{h}d", "as_of_date": as_of, "ticker": "AAPL", "horizon_days": h,
            "label_convention": "open_to_close", "prob_up": prob, "prob_model": prob, "calibrated": False,
            "base_rate": 0.5, "news_score": 0.0, "news_logit": 0.0, "contributions": {"up": [], "down": []},
            "model_version": "logit-v1", "model_id": "m", "trained_until": "2026-10-01", "computed_at": computed_at,
            **extra}


def rng(as_of: str, h: int, made_at: str, target: str, **extra) -> dict:
    return {"id": f"{as_of}-AAPL-{h}d", "made_at": made_at, "as_of_date": as_of, "session_date": as_of,
            "target_date": target, "ticker": "AAPL", "horizon_days": h, "base_close": 100.0, "center": 0.0,
            "sigma_h": 0.02, "lo50": 99.0, "hi50": 101.0, "lo80": 97.0, "hi80": 103.0, "regime": "CALM",
            "notes": [], "inputs": [], **extra}


@pytest.fixture
def market(tmp_path, monkeypatch):
    root, cfg = setup(tmp_path)
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.setattr(common, "CONFIG", cfg)
    new = {"horizon_label": "n_plus_k"}
    # before B10 (no label): a 1-day score (N+1 already), a 5-day score (D+4) and two old ranges
    jsonl(root, "model_scores", "2026-10-06", [score("2026-10-05", 1, 0.51, "2026-10-06T11:00:00+00:00"),
                                               score("2026-10-05", 5, 0.52, "2026-10-06T11:00:00+00:00")])
    jsonl(root, "ranges", "2026-10-06", [rng("2026-10-05", 1, "2026-10-06T11:30:00+00:00", "2026-10-06"),
                                         rng("2026-10-05", 5, "2026-10-06T11:30:00+00:00", "2026-10-12")])
    # from B10 on
    jsonl(root, "model_scores", "2026-10-07", [
        score("2026-10-06", h, 0.5 + h / 100, "2026-10-07T11:00:00+00:00", **new,
              entry_date="2026-10-07", exit_date=str(hz.entry_exit(US, date(2026, 10, 6), h)[1])) for h in (1, 3, 5)])
    jsonl(root, "model_scores", "2026-10-07", [score("2026-10-06", 3, 0.6, "2026-10-07T12:00:00+00:00", **new,
                                                     entry_date="2026-10-07", exit_date="2026-10-09")])
    jsonl(root, "ranges", "2026-10-07", [rng("2026-10-06", h, "2026-10-07T11:30:00+00:00",
                                             str(hz.entry_exit(US, date(2026, 10, 6), h)[1]), **new,
                                             entry_date="2026-10-07", exit_date=str(hz.entry_exit(US, date(2026, 10, 6),
                                                                                                  h)[1]))
                                         for h in (1, 5)])
    return root


@pytest.mark.usefixtures("market")
def test_views_label_rows_written_before_b10():
    con = connect(MARKET)
    scores = dict(con.execute("SELECT id, horizon_label FROM model_scores_latest").fetchall())
    assert scores["2026-10-05-AAPL-1d"] == "n_plus_k" and scores["2026-10-05-AAPL-5d"] == "legacy_5d_d4"
    assert scores["2026-10-06-AAPL-5d"] == "n_plus_k"
    ranges = dict(con.execute("SELECT id, horizon_label FROM ranges_latest").fetchall())
    assert ranges["2026-10-05-AAPL-1d"] == ranges["2026-10-05-AAPL-5d"] == "legacy_cc"
    assert ranges["2026-10-06-AAPL-1d"] == "n_plus_k"
    assert con.execute("SELECT count(*) FROM open_ranges WHERE horizon_label IS NULL").fetchone()[0] == 0


@pytest.mark.usefixtures("market")
def test_scores_asof_newest_n_plus_k_only_and_no_look_ahead():
    before = contract.scores_asof(MARKET, "2026-10-06T23:00:00+00:00")       # only the pre-B10 rows exist
    assert [(r["horizon_days"], r["horizon_label"]) for r in before] == [(1, "n_plus_k")]   # the D+4 one is left out
    assert (str(before[0]["entry_date"]), str(before[0]["exit_date"])) == ("2026-10-06", "2026-10-07")
    at_11 = {r["horizon_days"]: r for r in contract.scores_asof(MARKET, "2026-10-07T11:30:00+00:00")}
    assert sorted(at_11) == [1, 3, 5] and at_11[3]["prob_up"] == 0.53                 # the 12:00 rerun not known yet
    assert str(at_11[5]["exit_date"]) == "2026-10-14" and at_11[5]["horizon_label"] == "n_plus_k"
    assert isinstance(at_11[5]["contributions"], dict)
    later = {r["horizon_days"]: r for r in contract.scores_asof(MARKET, "2026-10-07T13:00:00+00:00")}
    assert later[3]["prob_up"] == 0.6
    assert [r["horizon_days"] for r in contract.scores_asof(MARKET, "2026-10-07T13:00:00+00:00", 5)] == [5]


@pytest.mark.usefixtures("market")
def test_ranges_asof_first_published_n_plus_k_of_the_newest_as_of_date():
    assert contract.ranges_asof(MARKET, "2026-10-06T23:00:00+00:00") == []      # legacy ranges are never offered
    rows = contract.ranges_asof(MARKET, "2026-10-07T12:00:00+00:00")
    assert [(r["id"], str(r["exit_date"])) for r in rows] == [("2026-10-06-AAPL-1d", "2026-10-08"),
                                                              ("2026-10-06-AAPL-5d", "2026-10-14")]
    assert all(str(r["target_date"]) == str(r["exit_date"]) for r in rows)
    assert contract.ranges_asof(MARKET, "2026-10-07T11:00:00+00:00") == []      # made after the time asked


def test_scores_asof_reads_one_model_variant(market):
    """The cross_market variant (every cross-market group on; stored in model_variant_scores, ids end in
    -cross_market) is read only on request; model_scores and its view never hold it; an unknown variant exits."""
    root = market
    jsonl(root, "model_variant_scores", "2026-10-07", [
        {**score("2026-10-06", 1, 0.7, "2026-10-07T11:00:00+00:00", horizon_label="n_plus_k",
                 model_variant="cross_market", entry_date="2026-10-07", exit_date="2026-10-08"),
         "id": "2026-10-06-AAPL-1d-cross_market"}])
    base = {r["horizon_days"]: r for r in contract.scores_asof(MARKET, "2026-10-07T12:00:00+00:00")}
    cross = contract.scores_asof(MARKET, "2026-10-07T12:00:00+00:00", variant="cross_market")
    assert base[1]["prob_up"] == 0.51 and base[1]["id"] == "2026-10-06-AAPL-1d"
    assert [(r["id"], r["prob_up"]) for r in cross] == [("2026-10-06-AAPL-1d-cross_market", 0.7)]
    ids = {r[0] for r in connect(MARKET).execute("SELECT id FROM model_scores_latest").fetchall()}
    assert "2026-10-06-AAPL-1d-cross_market" not in ids
    with pytest.raises(SystemExit):
        contract.scores_asof(MARKET, "2026-10-07T12:00:00+00:00", variant="nope")


def test_context_section_shows_n_plus_k_scores_only(market):
    """A legacy_5d_d4 score (old D+4 exit) newer than every N+k row never reaches the context pack, where it would
    read like an N+5 one (issue #95): the section shows the newest as-of date of the N+k rows."""
    jsonl(market, "model_scores", "2026-10-08", [score("2026-10-07", 5, 0.9, "2026-10-08T11:00:00+00:00")])
    con = connect(MARKET)
    assert con.execute("SELECT horizon_label FROM model_scores_latest WHERE id = '2026-10-07-AAPL-5d'").fetchone() == (
        "legacy_5d_d4",)
    body = context_section.context_section(con)[1]
    assert "2026-10-07-AAPL-5d" not in body and "0.9000" not in body
    assert all(f"| 2026-10-06-AAPL-{h}d |" in body for h in (1, 3, 5))
