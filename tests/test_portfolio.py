"""The paper portfolio (WS4; scripts/portfolio.py, marketbrief/portfolio/): trade validation, corrections with
supersedes, FIFO P&L with costs, split basis and no look-ahead, on a synthetic data root (offline).
Run: pytest -q tests/test_portfolio.py"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.model.settings import load_costs, round_trip_cost  # noqa: E402
from marketbrief.portfolio import service  # noqa: E402
from marketbrief.portfolio.cli import main  # noqa: E402
from marketbrief.portfolio.costs import trade_cost  # noqa: E402

NOW = "2026-10-07T12:00:00+00:00"
COLLECTED = "2026-10-07T00:00:00+00:00"
D1, D2, D3, D4 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5), date(2026, 10, 6)
SATURDAY = date(2026, 10, 3)
# (open, high, low, close) per ticker and session
BARS = {"AAPL": {D1: (200, 205, 198, 202), D2: (203, 208, 201, 206), D3: (207, 211, 204, 210),
                 D4: (209, 215, 207, 214)},
        "JPM": {D1: (300, 303, 297, 301), D2: (301, 304, 299, 302), D3: (302, 306, 300, 305), D4: (305, 309, 303, 308)}}
INDIA_BARS = {"HDFCBANK": {D1: (100, 104, 99, 101), D3: (110, 112, 108, 111), D4: (118, 121, 117, 120)}}
US_COSTS = {"commission_each_side": 0.0, "sec_fee_sell": 0.0000206, "finra_taf_per_share_sell": 0.000195,
            "finra_taf_max_per_trade": 9.79, "notional_per_trade": 10000.0, "slippage_each_side": 0.0}
INDIA_COSTS = {"brokerage_each_side": 0.0, "stt_each_side": 0.001, "exchange_txn_each_side": 0.0001,
               "sebi_fee_each_side": 0.0, "stamp_duty_buy": 0.0002, "gst_rate": 0.18, "slippage_each_side": 0.0}


def write_jsonl(root: Path, market: str, kind: str, day: date, rows: list[dict]) -> None:
    path = root / "data" / market / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)


def write_bars(root: Path, market: str, bars: dict, collected: str = COLLECTED) -> None:
    by_day: dict[date, list[str]] = {}
    for ticker, days in bars.items():
        for day, (o, h, low, c) in days.items():
            by_day.setdefault(day, []).append(f"{day},{ticker},{o},{h},{low},{c},{c},1000,{collected}")
    for day, lines in by_day.items():
        path = root / "data" / market / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = "" if path.exists() else "date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
        with path.open("a") as handle:
            handle.write(header + "\n".join(lines) + "\n")


def make_root(tmp_path: Path, monkeypatch) -> Path:
    """A synthetic data root with US and India bars, the clock frozen at NOW (shared with test_portfolio_signals)."""
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setenv("MB_NOW", NOW)
    write_bars(tmp_path, "us", BARS)
    write_bars(tmp_path, "india", INDIA_BARS)
    return tmp_path


@pytest.fixture
def root(tmp_path, monkeypatch):
    return make_root(tmp_path, monkeypatch)


def ctx_for(market: str = "us") -> service.Context:
    ctx = service.context(market)
    ctx.costs = US_COSTS if market == "us" else INDIA_COSTS
    return ctx


def buy(ctx, ticker="AAPL", quantity=10, day=D1, basis="open", **kw) -> dict:
    """add_trade with test defaults (a buy from claude_code); side, source and the optional fields as keywords."""
    side, source = kw.pop("side", "buy"), kw.pop("source", "claude_code")
    return service.add_trade(ctx, service.TradeInput(ticker, side, quantity, day, basis, source, **kw))


# ---------- validation ----------

@pytest.mark.parametrize("kw,word", [
    ({"ticker": "MSFT"}, "not in the us watchlist"),
    ({"day": SATURDAY}, "is not a session"),
    ({"day": date(2026, 10, 8)}, "after the run clock"),
    ({"basis": "manual", "price": 250.0}, "outside AAPL's stored low-high 198.0-205.0"),
    ({"basis": "manual"}, "needs a positive, finite price"),
    ({"price": 201.0}, "only with price_basis manual"),
    ({"quantity": 0}, "positive, finite number"),
    ({"quantity": float("inf")}, "positive, finite number"),
    ({"quantity": float("nan")}, "positive, finite number"),
    ({"quantity": True}, "positive, finite number"),
    ({"basis": "manual", "price": float("inf")}, "positive, finite price"),
    ({"side": "short"}, "side must be one of"),
    ({"basis": "vwap"}, "price_basis must be one of"),
    ({"day": date(2026, 9, 30)}, "no stored bar for AAPL on 2026-09-30"),
])
def test_add_trade_rejections(root, kw, word):
    ctx = ctx_for()
    result = buy(ctx, **kw)
    assert result["ok"] is False and any(word in e for e in result["errors"]), result
    assert not (root / "data" / "us" / "portfolio_trades").exists()   # nothing stored


@pytest.mark.usefixtures("root")
def test_bad_source_and_no_short():
    ctx = ctx_for()
    assert "source must be one of" in buy(ctx, source="email")["errors"][0]
    result = buy(ctx, side="sell")
    assert result["ok"] is False and "no paper short selling" in result["errors"][0]


@pytest.mark.usefixtures("root")
def test_price_defaults_to_stored_bar_and_manual_inside_range():
    ctx = ctx_for()
    assert buy(ctx)["trade"]["price"] == 200.0
    assert buy(ctx, basis="close")["trade"]["price"] == 202.0
    manual = buy(ctx, basis="manual", price=204.5)
    assert manual["ok"] and manual["trade"]["price"] == 204.5 and manual["trade"]["price_basis"] == "manual"


def test_duplicate_idempotency_key(root):
    ctx = ctx_for()
    first = buy(ctx, idempotency_key="slack-msg-1")
    assert first["ok"]
    again = buy(ctx, quantity=5, idempotency_key="slack-msg-1")
    assert again["ok"] is False and "already used" in again["errors"][0] and first["trade"]["id"] in again["errors"][0]
    # the derived default key: the same command twice (a retried message) is one trade
    assert buy(ctx, quantity=3)["ok"] and buy(ctx, quantity=3)["ok"] is False
    files = list((root / "data" / "us" / "portfolio_trades").rglob("*.jsonl"))
    assert len(files) == 1 and len(files[0].read_text().splitlines()) == 2


def test_rows_appended_never_rewritten_and_no_temp_left(root):
    ctx = ctx_for()
    buy(ctx)
    path = next((root / "data" / "us" / "portfolio_trades").rglob("*.jsonl"))
    before = path.read_text()
    buy(ctx, quantity=2)
    assert path.read_text().startswith(before) and path.name == "2026-10-07.jsonl"   # day file of entered_at (UTC)
    assert list((root / "work" / "portfolio").iterdir()) == []


# ---------- corrections ----------

@pytest.mark.usefixtures("root")
def test_correction_supersedes_and_cancel():
    ctx = ctx_for()
    wrong = buy(ctx, quantity=10)["trade"]
    fixed = buy(ctx, quantity=12, supersedes=wrong["id"])
    assert fixed["ok"] and fixed["trade"]["supersedes"] == wrong["id"]
    assert service.positions_report(ctx)["positions"][0]["quantity"] == 12
    again = buy(ctx, quantity=11, supersedes=wrong["id"])
    assert again["ok"] is False and "already cancelled or corrected" in again["errors"][0]
    other = buy(ctx, ticker="JPM", supersedes=fixed["trade"]["id"])
    assert other["ok"] is False and "keep the ticker" in other["errors"][0]
    assert "no such trade" in buy(ctx, supersedes="pt-us-nope")["errors"][0]
    cancel = service.cancel_trade(ctx, fixed["trade"]["id"], "claude_code", note="typo")
    assert cancel["ok"] and cancel["trade"]["side"] == "cancel" and cancel["trade"]["quantity"] == 0
    assert service.positions_report(ctx)["positions"] == []
    states = {row["id"]: row["state"] for row in service.list_report(ctx)["trades"]}
    assert states == {wrong["id"]: "superseded", fixed["trade"]["id"]: "superseded", cancel["trade"]["id"]: "cancel"}
    assert service.cancel_trade(ctx, cancel["trade"]["id"], "claude_code")["ok"] is False


@pytest.mark.usefixtures("root")
def test_cancel_that_would_uncover_a_sell_is_rejected():
    ctx = ctx_for()
    bought = buy(ctx, quantity=10)["trade"]
    assert buy(ctx, side="sell", quantity=4, day=D2)["ok"]
    result = service.cancel_trade(ctx, bought["id"], "claude_code")
    assert result["ok"] is False and "no paper short selling" in result["errors"][0]


# ---------- P&L ----------

@pytest.mark.usefixtures("root")
def test_pnl_india_fifo_with_costs():
    ctx = ctx_for("india")
    buy(ctx, ticker="HDFCBANK", quantity=10, day=D1)                        # 10 @ 100 (open)
    buy(ctx, ticker="HDFCBANK", side="sell", quantity=4, day=D3, basis="manual", price=110.0)
    out = service.pnl_report(ctx)
    side = 0.0001 * 1.18 + 0.001                                              # taxable x (1 + GST) + STT
    buy_cost, sell_cost = 1000 * (side + 0.0002), 440 * side
    realised = 40 - buy_cost * 0.4 - sell_cost
    unrealised = 120 - buy_cost * 0.6 - 720 * side                           # mark: the D4 close 120
    totals = out["totals"]
    assert totals["realised_gross"] == 40.0 and totals["realised_net"] == round(realised, 2)
    assert totals["unrealised_gross"] == 120.0 and totals["unrealised_net"] == round(unrealised, 2)
    assert totals["costs_paid"] == round(buy_cost + sell_cost, 2) and totals["est_exit_cost"] == round(720 * side, 2)
    assert totals["total_net"] == round(realised + unrealised, 2)
    assert out["positions"] == [{"ticker": "HDFCBANK", "quantity": 6.0, "avg_price": 100.0, "cost_value": 600.0,
                                 "mark_date": "2026-10-06", "mark": 120.0, "market_value": 720.0, "lots": 1}]
    assert out["paper_only"] is True


@pytest.mark.usefixtures("root")
def test_pnl_us_sell_side_fees():
    ctx = ctx_for()
    buy(ctx, quantity=100)                                                   # 100 @ 200
    buy(ctx, side="sell", quantity=100, day=D3, basis="close")               # 100 @ 210
    totals = service.pnl_report(ctx)["totals"]
    fee = 21000 * 0.0000206 + 100 * 0.000195                                 # SEC fee + FINRA TAF (under its cap)
    assert totals["realised_gross"] == 1000.0 and totals["realised_net"] == round(1000 - fee, 2)
    assert totals["unrealised_gross"] == 0.0 and service.positions_report(ctx)["positions"] == []


@pytest.mark.usefixtures("root")
def test_same_day_open_before_close():
    ctx = ctx_for()
    buy(ctx, quantity=5, basis="close", day=D2)
    result = buy(ctx, side="sell", quantity=5, basis="open", day=D2)          # the open comes before the close
    assert result["ok"] is False and "no paper short selling" in result["errors"][0]


@pytest.mark.parametrize("market,price", [("india", 1234.5), ("us", 187.25)])
def test_side_costs_add_up_to_the_models_round_trip(market, price):
    costs = load_costs(market)
    quantity = costs.get("notional_per_trade", 10000.0) / price
    both = trade_cost(market, costs, "buy", quantity, price) + trade_cost(market, costs, "sell", quantity, price)
    assert both == pytest.approx(round_trip_cost(market, costs, price) * quantity * price, rel=1e-12)


def test_split_after_the_trade_is_not_a_loss(root):
    write_jsonl(root, "us", "adjustments", D3, [{"id": "AAPL-2026-10-05", "ticker": "AAPL", "ex_date": "2026-10-05",
                                                 "factor": 0.5, "detected_at": "2026-10-06T00:00:00+00:00"}])
    write_bars(root, "us", {"AAPL": {D3: (104, 106, 102, 105), D4: (105, 108, 104, 107)}},
               collected="2026-10-07T00:30:00+00:00")
    ctx = ctx_for()
    buy(ctx, quantity=10, day=D1)                                            # 10 @ 200 before a 2:1 split
    out = service.pnl_report(ctx)
    assert out["positions"][0]["quantity"] == 20 and out["positions"][0]["avg_price"] == 100.0
    assert out["totals"]["unrealised_gross"] == 140.0                       # (107 - 100) x 20


# ---------- no look-ahead ----------

def test_no_look_ahead(root, monkeypatch):
    ctx = ctx_for()
    buy(ctx, quantity=10)
    write_bars(root, "us", {"AAPL": {D4: (1, 999, 1, 999)}}, collected="2026-10-07T13:00:00+00:00")   # after the clock
    late = {"id": "pt-us-late", "market": "us", "ticker": "AAPL", "side": "buy", "quantity": 1, "price": 200.0,
            "price_basis": "open", "trade_date": "2026-10-01", "source": "claude_code", "idempotency_key": "late",
            "entered_at": "2026-10-07T13:00:00+00:00", "note": None, "supersedes": None}
    write_jsonl(root, "us", "portfolio_trades", D4, [late])
    out = service.pnl_report(ctx_for())
    assert out["positions"][0]["quantity"] == 10 and out["positions"][0]["mark"] == 214.0
    monkeypatch.setenv("MB_NOW", "2026-10-07T14:00:00+00:00")
    later = service.pnl_report(ctx_for())
    assert later["positions"][0]["quantity"] == 11 and later["positions"][0]["mark"] == 999.0


# ---------- CLI ----------

def run_cli(argv: list[str]) -> tuple[int, dict, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, json.loads(out.getvalue()), err.getvalue()


@pytest.mark.usefixtures("root")
def test_cli_json_and_table():
    code, result, table = run_cli(["--market", "us", "add-trade", "--ticker", "MSFT", "--side", "buy", "--quantity",
                                   "1", "--date", "2026-10-01", "--basis", "open", "--source", "claude_code"])
    assert code == 2 and result["ok"] is False and "REJECTED" in table
    code, result, _ = run_cli(["--market", "us", "add-trade", "--ticker", "AAPL", "--side", "buy", "--quantity", "2",
                               "--date", "2026-10-01", "--basis", "open", "--source", "slack", "--key", "m1"])
    assert code == 0 and result["trade"]["price"] == 200.0
    code, result, table = run_cli(["--market", "us", "positions"])
    assert code == 0 and result["positions"][0]["quantity"] == 2.0 and "AAPL" in table
    code, result, _ = run_cli(["--market", "us", "request-company", "--name", "Microsoft", "--reason", "cloud",
                               "--source", "claude_code"])
    assert code == 0 and result["request"]["status"] == "requested"
    code, result, _ = run_cli(["--market", "us", "request-company", "--name", " microsoft", "--reason", "again",
                               "--source", "claude_code"])
    assert code == 2 and "already used" in result["errors"][0]
    code, result, _ = run_cli(["--market", "us", "request-company", "--ticker", "AAPL", "--reason", "x",
                               "--source", "claude_code"])
    assert code == 2 and "already in the us watchlist" in result["errors"][0]
    code, result, _ = run_cli(["--market", "us", "list"])
    assert len(result["trades"]) == 1 and len(result["requests"]) == 1
