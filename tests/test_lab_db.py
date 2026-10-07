"""B2 end to end on a synthetic data root (offline): settle_due reads the stored predictions, picks, bars, splits and
EUR/USD as of the clock, appends paper_trades_settled once (idempotent), refuses a prediction made after D's open,
re-settles a trade as a new row when its split record is corrected, and pick_day writes both pick rules per family;
plus the owner portfolio's EUR view and the lab CLI."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from lab_fixtures import INDIA_RATES, US_RATES, prediction

import common
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import cli, registry, run
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
    """A data root with the US fixture bars and a config copy whose costs are the fixture's rates."""
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
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
    out = run.settle_due(connect("us"), cfg, NOW, betas={}, commits={})
    assert out["written"] == 1 and out["refused_not_locked"] == [late["id"]]
    row = stored_trades()[0]
    # qty 10; EUR 0.99 x (1.10 + 1.20) = 2.277 -> 2.28, SEC 0.02 -> costs 2.30, net 17.70 (as test_lab_engine)
    assert (row["trade_id"], row["status"], row["net_pnl"], row["costs"]) == (f"acc:{good['id']}", "settled", 17.7,
                                                                            2.3)
    assert run.settle_due(connect("us"), cfg, NOW, betas={}, commits={})["written"] == 0     # idempotent
    # a 2:1 split recorded later inside the window: the trade is re-settled as a new row
    write_jsonl(root, "us", "adjustments", "2026-10-06", [{"id": "adj-AAPL-2026-10-05", "ticker": "AAPL",
                                                           "ex_date": "2026-10-05", "factor": 0.5,
                                                           "detected_at": "2026-10-06T22:00:00+00:00"}])
    out = run.settle_due(connect("us"), cfg, NOW + timedelta(days=1), betas={}, commits={})
    rows = stored_trades()
    assert out["written"] == 1 and len(rows) == 2
    assert rows[1]["supersedes"] == rows[0]["id"] and list(rows[1]["flags"]) == ["split_in_window", "resettled"]
    assert rows[1]["exit_quantity"] == 20.0


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
    assert again["written"] == 0


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
    # 2 shares at the 2 Oct open 100; buy fee 0.99 x 1.10 = 1.089; cost (200 + 1.089) / 1.10 x 1.0025 = 183.2652;
    # value 2 x 103 (the 6 Oct close) = 206 / 1.20 x 0.9975 = 171.2375; pnl -12.0277
    assert (view["eurusd_at_buy"], view["eurusd_now"], view["cost_eur"], view["value_eur"]) == (
        1.1, 1.2, 183.27, 171.24)
    assert view["pnl_eur"] == -12.03 and view["fx_effect_eur"] == round(206 / 1.2 - 206 / 1.1, 2)


@pytest.mark.usefixtures("root")
def test_cli_summary_and_predict_without_b10(capsys):
    assert cli.main(["--market", "us", "summary"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["scoreboard"] == [] and summary["basis"] == "forward"
    assert cli.main(["--market", "us", "predict"]) == 2                          # B10's scores not built yet
    assert "B10" in json.loads(capsys.readouterr().out)["message"]
