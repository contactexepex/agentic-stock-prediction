"""B2 end to end on a synthetic data root (offline): settle_due reads the stored predictions, picks, bars, splits and
EUR/USD as of the clock, appends paper_trades_settled once (idempotent), refuses a prediction made after D's open,
re-settles a trade as a new row when its split record is corrected, and pick_day writes both pick rules per family;
plus the owner portfolio's EUR view and the lab CLI."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml
from lab_fixtures import INDIA_RATES, US_RATES, prediction

import common
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import cli, registry, reports, run, settle_run, sizing, timing
from marketbrief.lab.constants import MSG_NO_CROSS_SCORE
from marketbrief.portfolio import service
from marketbrief.portfolio.eur_view import lot_view

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)
US_BARS = {"AAPL": {"2026-10-02": (100, 101.5, 99, 101), "2026-10-05": (101, 102.5, 100, 102),
                    "2026-10-06": (102, 103.5, 101, 103)},
           "SPY": {"2026-10-02": (500, 501, 499, 500), "2026-10-05": (502, 506, 501, 505),
                   "2026-10-06": (505, 506, 504, 505)},
           "EURUSD": {"2026-10-01": (1.1, 1.1, 1.1, 1.10), "2026-10-02": (1.1, 1.1, 1.1, 1.10),
                      "2026-10-05": (1.2, 1.2, 1.2, 1.20),
                      "2026-10-06": (1.2, 1.2, 1.2, 1.20)}}


LIVE_FROM = "2026-01-02"     # every fixture session is on or after it: all strategies trade


def set_live_from(config: Path, live_from: str | None, ids: tuple[str, ...] | None = None) -> None:
    """Set `live_from` of the strategies (all, or `ids`) in a config copy's strategies.yaml."""
    path = config / "strategies.yaml"
    reg = yaml.safe_load(path.read_text())
    for spec in reg["strategies"]:
        if ids is None or spec["id"] in ids:
            spec["live_from"] = live_from
    path.write_text(yaml.safe_dump(reg, sort_keys=False))


def write_jsonl(root: Path, market: str, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / market / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)


def write_bars(root: Path, market: str, bars: dict) -> None:
    for ticker, days in bars.items():
        for day, (o, h, low, c) in days.items():
            path = root / "data" / market / "prices" / day[:4] / day[5:7] / f"{day}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            head = "" if path.exists() else "date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
            with path.open("a") as handle:
                handle.write(f"{head}{day},{ticker},{o},{h},{low},{c},{c},1000,{day}T22:30:00+00:00\n")


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A data root with the US fixture bars and a config copy whose costs are the fixture's rates and whose
    strategies are all live from LIVE_FROM (the go-live switch; tests of the switch itself override it)."""
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
    set_live_from(config, LIVE_FROM)
    costs = yaml.safe_load((config / "costs.yaml").read_text())
    costs["us"].update({k: v for k, v in US_RATES.items() if k != "order_fee_eur"})
    costs["broker"]["us"]["order_fee_eur"] = US_RATES["order_fee_eur"]
    costs["india"].update({k: v for k, v in INDIA_RATES.items() if not k.startswith(("brokerage", "dp_"))})
    (config / "costs.yaml").write_text(yaml.safe_dump(costs))
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "CONFIG", config)
    monkeypatch.setenv("MB_NOW", NOW.isoformat())
    write_bars(tmp_path, "us", US_BARS)
    return tmp_path


def stored_trades(market: str = "us") -> list[dict]:
    return connect(market).execute("SELECT * FROM paper_trades_settled ORDER BY settled_at, id").df().to_dict("records")


def test_settle_due_end_to_end(root):
    cfg = load_market("us")
    good = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0)
    late = prediction("us", "AAPL", 2, made_at="2026-10-02T13:31:00+00:00")       # after the open: refused
    down = prediction("us", "AAPL", 3, direction="down", qualifies=False)          # never a trade
    write_jsonl(root, "us", "strategy_predictions", "2026-10-02", [good, late, down])
    out = settle_run.settle_due(connect("us"), cfg, NOW, betas={})
    assert out["written"] == 1 and out["refused_not_locked"] == [late["id"]]
    row = stored_trades()[0]
    # qty 10; EUR 0.99 x (1.10 + 1.20) = 2.277 -> 2.28, SEC 0.02 -> costs 2.30, net 17.70 (as test_lab_engine)
    assert (row["trade_id"], row["status"], row["net_pnl"], row["costs"]) == (f"acc:{good['id']}", "settled", 17.7,
                                                                            2.3)
    # its your-cost view: + FX .0075 x 2020 = 15.15 + portfolio fee .002 x 1000 x 3 / 365 = 0.02 -> 17.47
    view = connect("us").execute("SELECT record_kind, record_id, your_costs, net_pnl_your FROM cost_views").fetchall()
    assert view == [("settlement", row["id"], 17.47, 2.53)]
    assert settle_run.settle_due(connect("us"), cfg, NOW, betas={})["written"] == 0     # idempotent
    # a 2:1 split recorded later inside the window: the trade is re-settled as a new row
    split = {"id": "adj-AAPL-2026-10-05", "ticker": "AAPL", "ex_date": "2026-10-05", "factor": 0.5,
             "detected_at": "2026-10-06T22:00:00+00:00"}
    write_jsonl(root, "us", "adjustments", "2026-10-06", [split])
    out = settle_run.settle_due(connect("us"), cfg, NOW + timedelta(days=1), betas={})
    rows = stored_trades()
    assert out["written"] == 1 and len(rows) == 2
    assert rows[1]["supersedes"] == rows[0]["id"] and list(rows[1]["flags"]) == ["split_in_window", "resettled"]
    assert rows[1]["exit_quantity"] == 20.0
    # the split was wrong: a correcting record (supersedes, factor 1) re-settles the trade again
    write_jsonl(root, "us", "adjustments", "2026-10-07", [{"id": "adj-AAPL-2026-10-05-fix", "ticker": "AAPL",
                                                           "ex_date": "2026-10-05", "factor": 1.0,
                                                           "supersedes": split["id"],
                                                           "detected_at": "2026-10-07T22:00:00+00:00"}])
    out = settle_run.settle_due(connect("us"), cfg, NOW + timedelta(days=2), betas={})
    rows = stored_trades()
    assert out["written"] == 1 and rows[2]["supersedes"] == rows[1]["id"] and rows[2]["exit_quantity"] == 10.0
    assert list(rows[2]["adjustment_ids"]) == ["adj-AAPL-2026-10-05-fix"] and rows[2]["net_pnl"] == 17.7


def test_pick_day_end_to_end(root):
    cfg = load_market("us")
    rule = prediction("us", "AAPL", 1, target_price=101.0, lo80=98.0, hi80=104.0, base_close=100.0)
    ai = prediction("us", "AAPL", 3, target_price=101.0, lo80=96.0, hi80=106.0, base_close=100.0,
                    id="ai.combined.opus.v1:2026-10-01-AAPL-3d", strategy_id="ai.combined.opus.v1", family="ai")
    write_jsonl(root, "us", "strategy_predictions", "2026-10-02", [rule, ai])
    when = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    out = run.pick_day(connect("us"), cfg, when, registry.strategies(), "2026-10-02")
    assert (out["picks"], out["written"], out["no_candidate"]) == (4, 4, 0)
    picks = connect("us").execute("SELECT family, pick_rule, strategy_id, horizon_days FROM head_to_head_picks "
                                  "ORDER BY family, pick_rule").fetchall()
    assert picks == [("ai", "best_expected_gain", "ai.combined.opus.v1", 3),
                     ("ai", "highest_probability", "ai.combined.opus.v1", 3),
                     ("rule", "best_expected_gain", "rule.model_news.v1", 1),
                     ("rule", "highest_probability", "rule.model_news.v1", 1)]
    again = run.pick_day(connect("us"), cfg, when, registry.strategies(), "2026-10-02")
    assert again["written"] == 0 and again["cost_views"] == 0
    kinds = connect("us").execute("SELECT record_kind, count(*) FROM cost_views GROUP BY 1 ORDER BY 1").fetchall()
    assert kinds == [("pick", 4), ("prediction", 2)] and out["cost_views"] == 6
    # F1.8: no pick at or after D's open (13:30Z on 2 Oct)
    late = run.pick_day(connect("us"), cfg, datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc), registry.strategies(),
                        "2026-10-02")
    assert late["ok"] is False and "before its open" in late["message"]


def test_settlement_refuses_a_pick_made_after_the_open(root):
    cfg = load_market("us")
    pred = prediction("us", "AAPL", 1, target_price=101.0, lo80=98.0, hi80=104.0, base_close=100.0)
    pick = {"id": "h2h:2026-10-01-AAPL-rule-highest_probability", "market": "us", "ticker": "AAPL",
            "made_at": "2026-10-02T14:00:00+00:00", "session_date": "2026-10-02", "family": "rule",
            "pick_rule": "highest_probability", "status": "picked", "strategy_id": pred["strategy_id"],
            "prediction_id": pred["id"], "horizon_days": 1}
    write_jsonl(root, "us", "strategy_predictions", "2026-10-02", [pred])
    write_jsonl(root, "us", "head_to_head_picks", "2026-10-02", [pick])
    out = settle_run.settle_due(connect("us"), cfg, NOW, betas={})
    assert out["refused_not_locked"] == [pick["id"]] and out["written"] == 1           # the accuracy trade only
    assert stored_trades()[0]["view"] == "accuracy"


def test_a_row_no_commit_added_is_refused_in_a_git_data_root(root):
    # F1.8 (issue #110): when the data root is a git repository, a prediction row that no commit added is refused,
    # while one committed before D's open (13:30Z on 2 Oct) settles
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_COMMITTER_DATE": "2026-10-01T22:00:00+00:00"}
    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)
    committed = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0)
    uncommitted = prediction("us", "AAPL", 2, target_price=102.2, lo80=99.0, hi80=103.0)
    git("init", "-q")
    write_jsonl(root, "us", "strategy_predictions", "2026-10-02", [committed])
    git("add", "data")
    git("commit", "-q", "-m", "predictions")
    write_jsonl(root, "us", "strategy_predictions", "2026-10-02", [uncommitted])     # appended, never committed
    out = settle_run.settle_due(connect("us"), load_market("us"), NOW, betas={})
    assert out["refused_not_locked"] == [uncommitted["id"]] and out["written"] == 1
    assert stored_trades()[0]["trade_id"] == f"acc:{committed['id']}"


def test_shallow_clone_boundary_lines_are_undated(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    def git(repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                            "GIT_COMMITTER_DATE": "2026-10-01T10:00:00+00:00"})
    git(origin, "init", "-q")
    data = origin / "d.jsonl"
    data.write_text('{"id": "a"}\n')
    git(origin, "add", "d.jsonl")
    git(origin, "commit", "-q", "-m", "one")
    data.write_text('{"id": "a"}\n{"id": "b"}\n')
    git(origin, "commit", "-q", "-am", "two")
    full = timing.first_commit_times(origin, data)
    assert set(full) == {'{"id": "a"}', '{"id": "b"}'} and None not in full.values()
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)], check=True,
                   capture_output=True)
    cut = timing.first_commit_times(shallow, shallow / "d.jsonl")
    assert cut == {'{"id": "a"}': None, '{"id": "b"}': None}                        # both in the boundary commit
    assert timing.in_git_repo(shallow) and not timing.in_git_repo(tmp_path)


def set_amount(day: str, amount: float) -> dict:
    """A B1 set_amount lifecycle event for MARUTI taking effect (and recorded) at 00:00Z on `day`."""
    return {"id": f"we-india-MARUTI-set_amount-{day}", "market": "india", "ticker": "MARUTI", "event": "set_amount",
            "effective_from": f"{day}T00:00:00+00:00", "recorded_at": f"{day}T00:00:00+00:00", "amount": amount,
            "currency": "INR", "reason": "test", "requested_by": "cli:session", "channel": "cli",
            "idempotency_key": f"amount-{day}", "validator_version": "lifecycle-v1"}


def test_amount_override_raises_or_lowers_the_amount(root):
    # decision 44 through B1's accessor (contracts/watchlist.trade_amount): set_amount events raise, then lower it
    write_jsonl(root, "india", "watchlist_events", "2026-10-01", [set_amount("2026-10-01", 200000.0)])
    write_jsonl(root, "india", "watchlist_events", "2026-10-03", [set_amount("2026-10-03", 10000.0)])
    at = {day: datetime(2026, 10, day, 12, tzinfo=timezone.utc) for day in (2, 4)}
    assert sizing.trade_amount("india", "MARUTI", datetime(2026, 9, 30, tzinfo=timezone.utc)) == 100000.0
    assert sizing.trade_amount("india", "MARUTI", at[2]) == 200000.0                   # raised
    assert sizing.trade_amount("india", "MARUTI", at[4]) == 10000.0                    # lowered
    assert sizing.trade_amount("india", "RELIANCE", at[4]) == 100000.0                 # the default


def test_eur_view_hand_checked():
    # 2 shares at 200 + a 1.15335 buy fee = 401.15335 USD at 1.165 -> 401.15335 / 1.165 x 1.0025 = 345.1985 EUR;
    # value 2 x 214 = 428 USD at 1.17 x 0.9975 = 364.8974 EUR; rate effect 428 / 1.17 - 428 / 1.165 = -1.5700
    view = lot_view({"price": 200.0, "cost": 1.15335, "quantity": 2.0}, 2.0, 214.0, (1.165, 1.17), 0.0025)
    assert view["cost_eur"] == pytest.approx(345.19849, abs=1e-5)
    assert view["value_eur"] == pytest.approx(364.89744, abs=1e-5)
    assert view["fx_effect_eur"] == pytest.approx(-1.57000, abs=1e-5)


@pytest.mark.usefixtures("root")
def test_portfolio_positions_have_the_eur_view():
    ctx = service.context("us")
    assert ctx.costs["order_fee_eur"] == 0.99 and ctx.costs["eurusd_symbol"] == "EURUSD"
    entry = service.TradeInput(ticker="AAPL", side="buy", quantity=2.0, trade_date=date(2026, 10, 2),
                               price_basis="open", source="claude_code")
    added = service.add_trade(ctx, entry)
    assert added["ok"] is True
    out = service.positions_report(service.context("us"))
    view = out["eur_view"][0]
    # 2 shares at the 2 Oct open 100; buy fee 0.99 x 1.10 = 1.089; BUX Basic FX 0.75%: cost (200 + 1.089) / 1.10 x
    # 1.0075 = 184.1792; value 2 x 103 (the 6 Oct close) = 206 / 1.20 x 0.9925 = 170.3792; pnl -13.8000
    assert (view["eurusd_at_buy"], view["eurusd_now"], view["cost_eur"], view["value_eur"]) == (
        1.1, 1.2, 184.18, 170.38)
    assert view["pnl_eur"] == -13.8 and view["fx_effect_eur"] == round(206 / 1.2 - 206 / 1.1, 2)


def horizon_rows(k: int, exit_day: str) -> tuple[dict, dict]:
    """B10's N+k model score and range of AAPL as of 2 Oct, made pre-open on Monday 5 Oct."""
    rid = f"2026-10-02-AAPL-{k}d"
    score = {"id": rid, "as_of_date": "2026-10-02", "ticker": "AAPL", "horizon_days": k,
             "label_convention": "open_to_close", "prob_up": 0.6, "prob_model": 0.6, "calibrated": True,
             "base_rate": 0.52, "news_score": 0.0, "news_logit": 0.0, "contributions": {}, "model_version": "test",
             "model_id": f"us-{k}d-test", "trained_until": "2026-09-30", "computed_at": "2026-10-05T10:00:00+00:00",
             "horizon_label": "n_plus_k", "entry_date": "2026-10-05", "exit_date": exit_day}
    band = {"id": rid, "made_at": "2026-10-05T10:00:00+00:00", "as_of_date": "2026-10-02", "session_date": "2026-10-05",
            "target_date": exit_day, "ticker": "AAPL", "horizon_days": k, "base_close": 101.0,
            "center": math.log((102.0 + k) / 101.0),           # a log shift (B10): target 102 + k
            "sigma_h": 0.02, "lo50": 100.0, "hi50": 104.0 + k, "lo80": 98.0, "hi80": 106.0 + k, "naive_lo50": 100.0,
            "naive_hi50": 104.0, "naive_lo80": 98.0, "naive_hi80": 106.0, "direction": None, "confidence": None,
            "regime": "TRENDING", "calibration_id": None, "notes": [], "inputs": [], "iv_sigma_h": None,
            "horizon_label": "n_plus_k", "entry_date": "2026-10-05", "exit_date": exit_day}
    return score, band


def test_predict_with_b10_scores_and_ranges(root, capsys, monkeypatch):
    # Monday 5 Oct before the open: as of Friday's close; N+1..N+5 exit 6..12 Oct (US sessions)
    exits = ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12"]
    rows = [horizon_rows(k, day) for k, day in zip(range(1, 6), exits)]
    write_jsonl(root, "us", "model_scores", "2026-10-05", [score for score, _ in rows])
    write_jsonl(root, "us", "ranges", "2026-10-05", [band for _, band in rows])
    monkeypatch.setenv("MB_NOW", "2026-10-05T11:45:00+00:00")
    assert cli.main(["--market", "us", "predict"]) == 0
    out = json.loads(capsys.readouterr().out)
    preds = {p["id"]: p for p in connect("us").execute("SELECT * FROM strategy_predictions").df().to_dict("records")}
    trading = sorted(f"cv:prediction:{i}" for i, p in preds.items() if p["qualifies"])
    # 10 strategies x 5; global abstains; issue #110: predict writes the cost-viable row of each qualifying one
    assert out == {"ok": True, "predictions": 50, "abstentions": 1, "cost_views": len(trading)} and trading
    views = connect("us").execute("SELECT id, record_kind FROM cost_views ORDER BY id").fetchall()
    assert views == [(i, "prediction") for i in trading]
    ref = preds["rule.model_news.v1:2026-10-02-AAPL-3d"]
    assert (ref["prob_up"], ref["target_price"], ref["lo80"], ref["hi80"], str(ref["exit_date"])[:10]) == (
        0.6, 105.0, 98.0, 109.0, "2026-10-08")
    assert str(ref["session_date"])[:10] == "2026-10-05" and ref["qualifies"] and ref["amount"] == 1000.0
    assert preds["rule.model_news_strict.v1:2026-10-02-AAPL-1d"]["qualifies"] is True   # 0.60 >= 0.60
    assert cli.main(["--market", "us", "predict"]) == 0                                 # ids already stored
    assert json.loads(capsys.readouterr().out) == {"ok": True, "predictions": 0, "abstentions": 0, "cost_views": 0}
    # pick afterwards: its prediction rows (cv:prediction:<id>) are already stored, only the picks are new
    pick = run.pick_day(connect("us"), load_market("us"), datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
                        registry.strategies(), "2026-10-05")
    kinds = connect("us").execute("SELECT record_kind, count(*), count(DISTINCT id) FROM cost_views GROUP BY 1 "
                                  "ORDER BY 1").fetchall()
    picked = pick["written"] - pick["no_candidate"]                     # the ai family has no prediction here
    assert kinds == [("pick", picked, picked), ("prediction", len(trading), len(trading))]
    assert pick["cost_views"] == picked > 0


def test_global_strategy_reads_the_cross_market_variant(root, capsys, monkeypatch):
    # rule.model_news_global.v1 (cross_market: true) predicts from B10's cross_market variant scores
    # (model_variant_scores, ids ending -cross_market) where they exist, and abstains on the other horizons
    exits = ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12"]
    rows = [horizon_rows(k, day) for k, day in zip(range(1, 6), exits)]
    write_jsonl(root, "us", "model_scores", "2026-10-05", [score for score, _ in rows])
    write_jsonl(root, "us", "ranges", "2026-10-05", [band for _, band in rows])
    cross = [{**score, "id": f"{score['id']}-cross_market", "prob_up": 0.7, "prob_model": 0.7,
              "model_variant": "cross_market"} for score, _ in rows[:2]]          # N+1 and N+2 only
    cross.append({**rows[2][0], "id": f"{rows[2][0]['id']}-cross_market", "prob_up": 0.7, "prob_model": 0.7,
                  "model_variant": "cross_market", "computed_at": "2026-10-05T12:00:00+00:00"})   # after MB_NOW
    write_jsonl(root, "us", "model_variant_scores", "2026-10-05", cross)
    monkeypatch.setenv("MB_NOW", "2026-10-05T11:45:00+00:00")
    assert cli.main(["--market", "us", "predict"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["ok"], out["predictions"], out["abstentions"]) == (True, 52, 1)
    con = connect("us")
    glob = {p["horizon_days"]: p for p in con.execute(
        "SELECT * FROM strategy_predictions WHERE strategy_id = 'rule.model_news_global.v1'").df().to_dict("records")}
    assert sorted(glob) == [1, 2]                  # not N+3: its variant score was computed after the clock
    assert (glob[1]["prob_up"], glob[1]["model_score_id"]) == (0.7, "2026-10-02-AAPL-1d-cross_market")
    assert "model_scores:2026-10-02-AAPL-2d-cross_market" in list(glob[2]["evidence_ids"])
    ref = con.execute("SELECT prob_up, model_score_id FROM strategy_predictions "
                      "WHERE id = 'rule.model_news.v1:2026-10-02-AAPL-1d'").fetchone()
    assert ref == (0.6, "2026-10-02-AAPL-1d")                                     # the base model, unchanged
    skipped = con.execute("SELECT horizons, reason FROM strategy_abstentions").fetchall()
    assert [(list(h), r) for h, r in skipped] == [([3, 4, 5], MSG_NO_CROSS_SCORE)]


@pytest.mark.usefixtures("root")
def test_backtest_reads_as_of_the_clock_and_adds_the_history_cache(monkeypatch):
    cfg = load_market("us")
    out = reports.run_backtest(connect("us"), cfg, NOW, history=False)
    assert out["eurusd"] == "stored EURUSD closes" and out["first_date"] == "2026-10-02"
    early = reports.run_backtest(connect("us"), cfg, datetime(2026, 10, 3, tzinfo=timezone.utc), history=False)
    assert early["last_date"] == "2026-10-02"                    # bars collected after the clock are not read
    days = pd.DatetimeIndex(["2026-09-29", "2026-09-30", "2026-10-01"])
    cached = {"AAPL": pd.DataFrame({"open": [98.0, 99.0, 99.5], "high": [99.0] * 3, "low": [97.0] * 3,
                                    "close": [98.5, 99.2, 100.0], "volume": [1.0] * 3}, index=days)}
    # issue #110: a symbol with no stored bars takes the cache whole; its dates after the clock are dropped
    later = pd.DatetimeIndex(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"])
    cached["XOM"] = pd.DataFrame({"open": [110.0] * 4, "high": [111.0] * 4, "low": [109.0] * 4,
                                  "close": [110.5] * 4, "volume": [1.0] * 4}, index=later)
    monkeypatch.setattr(reports, "load_cache", lambda _market: (cached, {}))
    out = reports.run_backtest(connect("us"), cfg, NOW, history=True)
    assert out["first_date"] == "2026-09-29" and out["splice"]["AAPL"]["cache_rows"] == 3
    assert out["splice"]["XOM"]["cache_rows"] == 2 and out["last_date"] == "2026-10-06"     # NOW: 6 Oct 23:00Z
    always = next(r for r in out["rows"] if (r["strategy_id"], r["horizon_days"]) == ("base.always_up.v1", 1))
    assert always["trades"] == 4                                 # 6 sessions -> 4 N+1 trades (29 Sep .. 2 Oct)
