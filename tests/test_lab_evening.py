"""B2: the evening preview `lab.py predict --evening` (option C with B17 and B10) on a synthetic data root (offline).
After Friday's close it writes the rows the Monday pre-open predict will write (same ids, same D) from B10's evening
ranges (ranges_asof run="evening", monkeypatched: B10's signature is not on main yet) to
strategy_predictions_evening only; no cost_views, abstentions or picks; settle and pick never read them."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from test_lab_db import horizon_rows, root, stored_trades, write_jsonl  # noqa: F401  (root is a fixture)

from marketbrief.contracts import horizons as horizons_contract
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import cli, registry, run, settle_run

EVENING = "2026-10-02T23:00:00+00:00"      # Friday after the close (the 2 Oct bar is stored at 22:30)
PRE_OPEN = "2026-10-05T11:45:00+00:00"     # Monday before the open: D = 5 Oct for both runs
EXITS = ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12"]
EVENING_KIND = "strategy_predictions_evening"


def evening_inputs(root_dir, monkeypatch) -> list[dict]:
    """Store the evening scores (computed before the evening clock) and the pre-open scores and ranges (Monday
    10:00); B10's ranges_asof is replaced by one that takes `run` and returns the evening bands for run="evening"
    (hi80 = 110 + k, made in the evening). Returns the list of `run` arguments each call passed."""
    rows = [horizon_rows(k, day) for k, day in zip(range(1, 6), EXITS)]
    evening_scores = [{**score, "prob_up": 0.62, "prob_model": 0.62, "computed_at": "2026-10-02T22:45:00+00:00"}
                      for score, _ in rows]
    write_jsonl(root_dir, "us", "model_scores", "2026-10-02", evening_scores)
    write_jsonl(root_dir, "us", "model_scores", "2026-10-05", [score for score, _ in rows])
    write_jsonl(root_dir, "us", "ranges", "2026-10-05", [band for _, band in rows])
    evening_bands = [{**band, "made_at": "2026-10-02T22:50:00+00:00", "hi80": 110.0 + band["horizon_days"]}
                     for _, band in rows]
    real, calls = horizons_contract.ranges_asof, []

    def ranges_asof(market, as_of, horizon_days=None, **kwargs):
        calls.append(kwargs.get("run"))
        if kwargs.get("run") == "evening":
            return [b for b in evening_bands if horizon_days in (None, b["horizon_days"])]
        return real(market, as_of, horizon_days)

    monkeypatch.setattr(horizons_contract, "ranges_asof", ranges_asof)
    return calls


def lab(capsys, *args) -> tuple[int, dict]:
    code = cli.main(["--market", "us", *args])
    return code, json.loads(capsys.readouterr().out)


def table(kind: str, columns: str = "*") -> list[dict]:
    return connect("us").execute(f"SELECT {columns} FROM {kind} ORDER BY id").df().to_dict("records")


def test_evening_preview_writes_only_its_kind_and_the_pre_open_ids(root, capsys, monkeypatch):  # noqa: F811
    calls = evening_inputs(root, monkeypatch)
    monkeypatch.setenv("MB_NOW", EVENING)
    code, out = lab(capsys, "predict", "--evening")
    # 10 strategies x 5 horizons; the global strategy abstains (no cross-market scores): counted, never stored
    assert code == 0 and out == {"ok": True, "run": "evening", "session_date": "2026-10-05", "rows": 50,
                                 "abstained_not_stored": 1, "predictions": 50}
    evening = {p["id"]: p for p in table(EVENING_KIND)}
    assert len(evening) == 50 and {p["run"] for p in evening.values()} == {"evening"}
    ref = evening["rule.model_news.v1:2026-10-02-AAPL-3d"]
    assert (ref["prob_up"], ref["hi80"], str(ref["session_date"])[:10], str(ref["made_at"])[:16]) == (
        0.62, 113.0, "2026-10-05", "2026-10-02 23:00")
    for kind in ("strategy_predictions", "strategy_abstentions", "cost_views", "head_to_head_picks"):
        assert table(kind, "id") == [], kind
    assert lab(capsys, "predict", "--evening") == (0, {"ok": True, "run": "evening", "session_date": "2026-10-05",
                                                       "rows": 50, "abstained_not_stored": 1, "predictions": 0})
    assert len(table(EVENING_KIND, "id")) == 50                                          # idempotent rerun
    # Monday's pre-open predict: unchanged (ranges_asof called without `run`), the evening ids do not block it
    monkeypatch.setenv("MB_NOW", PRE_OPEN)
    code, out = lab(capsys, "predict")
    trading = [p for p in table("strategy_predictions") if p["qualifies"]]
    assert code == 0 and out == {"ok": True, "predictions": 50, "abstentions": 1, "cost_views": len(trading)}
    pre_open = {p["id"]: p for p in table("strategy_predictions")}
    assert set(pre_open) == set(evening) and "run" not in pre_open[ref["id"]]
    assert (pre_open[ref["id"]]["prob_up"], pre_open[ref["id"]]["hi80"]) == (0.6, 109.0)   # the revision of record
    assert calls == ["evening", "evening", None]


def test_settle_and_pick_never_read_evening_rows(root, capsys, monkeypatch):  # noqa: F811
    evening_inputs(root, monkeypatch)
    monkeypatch.setenv("MB_NOW", EVENING)
    assert lab(capsys, "predict", "--evening")[1]["predictions"] == 50
    cfg = load_market("us")
    pick = run.pick_day(connect("us"), cfg, datetime(2026, 10, 5, 12, tzinfo=timezone.utc), registry.strategies(),
                        "2026-10-05")
    assert (pick["picks"], pick["written"], pick["cost_views"]) == (0, 0, 0)
    settled = settle_run.settle_due(connect("us"), cfg, datetime(2026, 10, 13, 23, tzinfo=timezone.utc), betas={})
    assert settled["written"] == 0 and stored_trades() == []
    assert table("head_to_head_picks", "id") == [] and table("cost_views", "id") == []


def test_evening_refuses_clearly_until_b10s_ranges_asof_takes_run(root, capsys, monkeypatch):  # noqa: F811
    def ranges_asof_without_run(market, as_of, horizon_days=None):  # noqa: ARG001 (main's signature, no `run`)
        return []

    monkeypatch.setattr(horizons_contract, "ranges_asof", ranges_asof_without_run)
    monkeypatch.setenv("MB_NOW", EVENING)
    code, out = lab(capsys, "predict", "--evening")
    assert code == 2 and out["ok"] is False and out["run"] == "evening"
    assert 'ranges_asof(..., run="evening")' in out["message"] and "B10" in out["message"]
    assert not (root / "data" / "us" / EVENING_KIND).exists()
