"""The shared derived records of the read models (scripts/marketbrief/warehouse/rm_entities.py, re-exported by
rm_common): Agreement, Open trade and Company, checked against W1's catalogue examples (design/catalogue/, built
with B2's engine from real stored bars), on a copy of the repo's stored data with the catalogue's predictions, picks
and a settlement appended as stored rows, as of 2026-10-07T12:00Z (nothing stored later is read)."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import rm_common, rm_entities  # noqa: E402
from marketbrief.warehouse.rm_registry import BuildContext  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CUTOFF = datetime.fromisoformat("2026-10-07T12:00:00+00:00")
MARKETS = ("india", "us")


def catalogue(name: str) -> list[dict]:
    return json.loads((REPO / "design" / "catalogue" / name).read_text())["records"]


def append(root: Path, market: str, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / market / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)


def past_prediction(trade: dict) -> dict:
    """The stored prediction behind a catalogue open trade (made before D's open, as the protocol requires)."""
    keys = (
        "strategy_id",
        "family",
        "market",
        "ticker",
        "horizon_days",
        "exit_date",
        "target_price",
        "lo50",
        "hi50",
        "lo80",
        "hi80",
        "amount",
        "currency",
    )
    return {
        "id": trade["prediction_id"],
        **{k: trade[k] for k in keys},
        "session_date": trade["entry_date"],
        "as_of_date": trade["entry_date"],
        "made_at": f"{trade['entry_date']}T00:30:00Z",
        "direction": "up",
        "qualifies": True,
        "prob_up": 0.6,
    }


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    """Both markets' stored data plus: today's catalogue predictions (made 11:45Z), the predictions and picks
    behind the catalogue's open trades, a settled trade, a prediction made after D's open, and a prediction made
    after the cut-off."""
    root = tmp_path_factory.mktemp("entities")
    for market in MARKETS:
        shutil.copytree(REPO / "data" / market, root / "data" / market)
    opens = catalogue("open_trade.json")
    for market in MARKETS:
        today = [p for p in catalogue("prediction.json") if p["market"] == market]
        append(root, market, "strategy_predictions", "2026-10-07", today)
        mine = [t for t in opens if t["market"] == market]
        past = {t["prediction_id"]: past_prediction(t) for t in mine}
        for pred in past.values():
            append(root, market, "strategy_predictions", pred["session_date"], [pred])
        picks = [
            {
                "id": f"pick:{t['trade_id']}",
                "market": market,
                "ticker": t["ticker"],
                "made_at": f"{t['entry_date']}T00:30:00Z",
                "family": t["family"],
                "pick_rule": t["trade_id"].split(":")[1],
                "status": "picked",
                "prediction_id": t["prediction_id"],
            }
            for t in mine
            if t["view"] == "head_to_head"
        ]
        if picks:
            append(root, market, "head_to_head_picks", picks[0]["made_at"][:10], picks)
    nvda = next(t for t in opens if t["ticker"] == "NVDA" and t["view"] == "accuracy")
    extra = {**past_prediction(nvda), "id": "rule.model_news.v1:2026-09-29-NVDA-4d", "horizon_days": 4}
    late = {
        **past_prediction(nvda),
        "id": "rule.model_news.v1:2026-09-29-NVDA-3d",
        "horizon_days": 3,
        "made_at": "2026-09-30T14:00:00Z",
    }  # after D's open (13:30Z): never a trade (F1.8)
    future = {
        **past_prediction(nvda),
        "id": "rule.model_news.v1:2026-09-29-NVDA-2d",
        "horizon_days": 2,
        "made_at": "2026-10-07T12:30:00Z",
    }  # stored after the cut-off
    append(root, "us", "strategy_predictions", "2026-09-30", [extra, late])
    # META: a 2-for-1 split on D (2 Oct) and another after it (5 Oct), so the target (as-of basis, 1 Oct) and the
    # entry (D's basis) need different factors (intraday/trade_rows.py)
    append(root, "us", "strategy_predictions", "2026-10-02", [SPLIT_PREDICTION])
    append(
        root,
        "us",
        "adjustments",
        "2026-10-06",
        [
            {
                "id": f"META-{day}",
                "ticker": "META",
                "ex_date": day,
                "factor": 0.5,
                "detected_at": "2026-10-06T22:00:00Z",
            }
            for day in ("2026-10-02", "2026-10-05")
        ],
    )
    append(root, "us", "strategy_predictions", "2026-10-07", [future])
    append(
        root,
        "us",
        "paper_trades_settled",
        "2026-10-06",
        [
            {
                "id": f"acc:{extra['id']}@x",
                "trade_id": f"acc:{extra['id']}",
                "status": "settled",
                "market": "us",
                "ticker": "NVDA",
                "view": "accuracy",
                "settled_at": "2026-10-06T22:15:00Z",
            }
        ],
    )
    # B2's go-live switch: only strategies live on D have open trades (B9's open_trades), so the config copy makes
    # every strategy live from the oldest D here
    config = root / "config"
    shutil.copytree(REPO / "config", config)
    reg = yaml.safe_load((config / "strategies.yaml").read_text())
    for spec in reg["strategies"]:
        spec["live_from"] = "2026-09-01"
    (config / "strategies.yaml").write_text(yaml.safe_dump(reg, sort_keys=False))
    saved, saved_config = common.ROOT, common.CONFIG
    common.ROOT, common.CONFIG = root, config
    try:
        yield {market: BuildContext(load_market(market), connect(market), CUTOFF) for market in MARKETS}
    finally:
        common.ROOT, common.CONFIG = saved, saved_config


SPLIT_PREDICTION = {
    "id": "rule.model_news.v1:2026-10-01-META-5d",
    "strategy_id": "rule.model_news.v1",
    "family": "rule",
    "market": "us",
    "ticker": "META",
    "horizon_days": 5,
    "as_of_date": "2026-10-01",
    "session_date": "2026-10-02",
    "exit_date": "2026-10-09",
    "made_at": "2026-10-02T00:30:00Z",
    "direction": "up",
    "qualifies": True,
    "prob_up": 0.6,
    "target_price": 1000.0,
    "lo50": 950.0,
    "hi50": 1050.0,
    "lo80": 900.0,
    "hi80": 1100.0,
    "amount": 1000.0,
    "currency": "USD",
}
AGREEMENT_KEYS = (
    "market",
    "as_of_date",
    "session_date",
    "ticker",
    "name",
    "horizon_days",
    "buy",
    "of",
    "by_family",
    "avg_prob_up",
    "label",
    "paper",
)


@pytest.mark.parametrize(("market", "ticker"), [("us", "NVDA"), ("india", "RELIANCE")])
def test_agreement_counts_match_the_catalogue(stored, market, ticker):
    """The catalogue's prediction file holds every strategy's call on NVDA and RELIANCE, so their counts match."""
    rows = rm_common.agreement(stored[market])
    assert sorted(rows) == ["1", "2", "3", "4", "5"]
    for k, by_rank in rows.items():
        assert [row["rank"] for row in by_rank] == list(range(1, len(by_rank) + 1))
        assert {row["ticker"] for row in by_rank} == stored[market].active  # every active company, once
        mine = next(row for row in by_rank if row["ticker"] == ticker)
        expected = next(a for a in catalogue("agreement.json") if a["ticker"] == ticker and a["horizon_days"] == int(k))
        assert {key: mine[key] for key in AGREEMENT_KEYS} == {key: expected[key] for key in AGREEMENT_KEYS}


def test_agreement_ranks_by_buyers_then_probability_then_ticker():
    preds = [
        {
            "ticker": t,
            "family": "rule",
            "qualifies": q,
            "prob_up": p,
            "horizon_days": 1,
            "as_of_date": "2026-10-06",
            "session_date": "2026-10-07",
        }
        for t, q, p in [("A", True, 0.6), ("B", True, 0.7), ("C", False, 0.4), ("D", True, 0.7)]
    ]
    companies = [{"ticker": t, "name": t} for t in "ABCDE"]
    ranked = rm_entities.agreement_rows(preds, companies, "us")["1"]
    assert [(row["ticker"], row["rank"]) for row in ranked] == [("B", 1), ("D", 2), ("A", 3), ("C", 4), ("E", 5)]
    assert ranked[3]["of"] == 1 and ranked[3]["buy"] == 0 and ranked[3]["avg_prob_up"] is None


def test_open_trades_match_the_catalogue(stored):
    """Every catalogue open trade is rebuilt from the stored bars (entry = D's open, last = the newest close by the
    cut-off) with the same quantity, unrealised profit and distance to target."""
    for market in MARKETS:
        records = {r["trade_id"]: r for r in rm_common.open_trades(stored[market])}
        expected = [t for t in catalogue("open_trade.json") if t["market"] == market]
        assert expected
        for trade in expected:
            assert records[trade["trade_id"]] == trade, trade["trade_id"]
        extra = {"acc:" + SPLIT_PREDICTION["id"]} if market == "us" else set()
        assert set(records) == {t["trade_id"] for t in expected} | extra  # nothing else is open


def test_settled_late_and_future_predictions_are_not_open(stored):
    ids = {r["prediction_id"] for r in rm_common.open_trades(stored["us"])}
    assert "rule.model_news.v1:2026-09-29-NVDA-4d" not in ids  # settled by the cut-off
    assert "rule.model_news.v1:2026-09-29-NVDA-3d" not in ids  # made after D's open
    assert "rule.model_news.v1:2026-09-29-NVDA-2d" not in ids  # stored after the cut-off
    # today's catalogue predictions (D = 7 Oct) have not entered: D's open is not stored by the cut-off
    assert not any(r["entry_date"] == "2026-10-07" for r in rm_common.open_trades(stored["us"]))


def test_open_trade_on_todays_basis_after_a_split():
    trade = {
        "trade_id": "acc:x",
        "view": "accuracy",
        "prediction_id": "x",
        "strategy_id": "s",
        "family": "rule",
        "ticker": "T",
        "horizon_days": 5,
        "entry_date": date(2026, 9, 30),
        "exit_date": date(2026, 10, 7),
        "amount": 1000.0,
        "target_price": 110.0,
        "lo80": 90.0,
        "lo50": 95.0,
        "hi50": 105.0,
        "hi80": 115.0,
    }
    # a 2-for-1 split after D (so after the as-of date too)
    prices = {"entry": 100.0, "last": 52.0, "last_date": "2026-10-06", "factor": 0.5, "target_factor": 0.5}
    record = rm_entities.open_trade_record(trade, "us", "USD", prices)
    assert record["quantity"] == 10.0 and record["entry_price"] == 100.0 and record["last_price"] == 52.0
    assert record["unrealised_pnl"] == 40.0  # 20 shares now x 52 - 1000
    assert record["unrealised_pct"] == 4.0
    assert record["to_target_pct"] == 5.77  # the target on today's basis: 55
    india = rm_entities.open_trade_record({**trade, "amount": 50.0}, "india", "INR", {**prices, "factor": 1.0})
    assert india is None  # one share costs more than the amount (F1.4)


def test_companies_carry_the_agreement_and_open_trade_counts(stored):
    for market in MARKETS:
        ctx = stored[market]
        rows = rm_common.companies(ctx)
        assert {row["ticker"] for row in rows} == ctx.collected
        assert [row["state"] == "active" for row in rows] == sorted(
            (row["state"] == "active" for row in rows), reverse=True
        )
        n1 = {row["ticker"]: {"buy": row["buy"], "of": row["of"]} for row in rm_common.agreement(ctx)["1"]}
        trades = rm_common.open_trades(ctx)
        for row in rows:
            assert row["open_trades"] == sum(t["ticker"] == row["ticker"] for t in trades)
            assert row["agreement_n1"] == (n1[row["ticker"]] if row["state"] == "active" else None)
            assert set(row) == set(rm_entities.COMPANY_KEYS) | {
                "last_close",
                "last_close_date",
                "change_pct",
                "agreement_n1",
                "open_trades",
            }
    by_ticker = {row["ticker"]: row for row in rm_common.companies(stored["us"])}
    company = next(c for c in catalogue("company.json") if c["ticker"] == "NVDA")
    for key in ("last_close", "last_close_date", "change_pct", "agreement_n1", "exchange", "currency"):
        assert by_ticker["NVDA"][key] == company[key], key
    assert by_ticker["NVDA"]["open_trades"] == company["open_trades"]


def test_records_validate_against_their_shared_schemas(stored):
    from marketbrief.warehouse import openapi_spec, schema_check

    document = openapi_spec.spec()

    def problems(value, name):
        return schema_check.errors(value, {"$ref": f"#/components/schemas/{name}"}, document)

    for market in MARKETS:
        ctx = stored[market]
        assert problems(rm_common.agreement(ctx), "AgreementMap") == []
        for trade in rm_common.open_trades(ctx):
            assert problems(trade, "OpenTrade") == [], trade["trade_id"]
        for company in rm_common.companies(ctx):
            assert problems(company, "CompanyRecord") == [], company["ticker"]


def test_open_trade_factors_come_from_the_stored_splits(stored):
    """META: split ex-dates on D (2 Oct) and after it (5 Oct). D's raw open is already on the first split's basis, so
    the entry takes only the later factor; the target was set on the as-of date (1 Oct), before both."""
    ctx = stored["us"]
    record = next(r for r in rm_common.open_trades(ctx) if r["ticker"] == "META")
    bars = dict(
        ctx.con.execute(
            "SELECT date::VARCHAR, open FROM ohlc_raw WHERE ticker = 'META' AND date = DATE '2026-10-02'"
        ).fetchall()
    )
    last_date, last = ctx.con.execute(
        "SELECT date::VARCHAR, close FROM ohlc_raw WHERE ticker = 'META' AND date <= DATE '2026-10-06' "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    entry = bars["2026-10-02"]
    shares = round(1000.0 / entry, 6)
    assert (record["entry_price"], record["last_price"], record["last_price_date"]) == (entry, last, last_date)
    assert record["quantity"] == shares
    assert record["unrealised_pnl"] == round(shares * (last / 0.5 - entry), 2)  # entry factor: only 5 Oct
    assert record["unrealised_pct"] == round((last / (entry * 0.5) - 1) * 100, 2)
    assert record["to_target_pct"] == round((1000.0 * 0.25 / last - 1) * 100, 2)  # target factor: both splits
