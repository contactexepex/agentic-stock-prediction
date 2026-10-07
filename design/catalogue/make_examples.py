"""Builds the EXAMPLE data files of design/catalogue/ (W1; docs/DATA_CATALOGUE.md).

Every file is marked `"_example": true`. Prices, benchmark and sector moves are copied from the stored bars
(`ohlc_raw`, 2026-09-29 .. 2026-10-06, read on 2026-10-07) and today's ranges' widths from the stored 1d/5d ranges;
everything else (strategy probabilities, trades, reasons, news, commands, the owner's portfolio) is INVENTED to show
the shape and is computed here from those inputs so the files agree with each other (quantities, costs, P&L,
agreement counts, scoreboard sums). Costs come from B2's engine with config/costs.yaml's rates (marked verify).
Sessions come from the real market calendar (India 2026-10-02 is a holiday). Rerun after a change:

    python design/catalogue/make_examples.py

Files whose entity is a stored kind hold rows with exactly that kind's columns (tests/test_w1_catalogue.py)."""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.core import calendar  # noqa: E402
from marketbrief.lab import costs as lab_costs  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402

NOTE = ("EXAMPLE DATA for page design only. Prices and index moves are stored bars; predictions, trades, reasons, "
        "news, commands and portfolio entries are invented and consistent with each other. Not a forecast, not advice.")
CURRENCY = {"india": "INR", "us": "USD"}
DEFAULT_AMOUNT = {"india": 100000.0, "us": 1000.0}
MADE_AT = {"india": "T02:10:00Z", "us": "T11:45:00Z"}   # pre-open runs: 07:40 IST, 07:45 New York (EDT)
EURUSD = 1.1700   # example rate; B2 collects EURUSD=X
# Cost rates: config/costs.yaml (statutory rates and the owner's `broker:` charges, all marked verify), applied by
# B2's engine (marketbrief/lab/costs.py).

# Stored bars (ohlc_raw): ticker -> date -> (open, high, low, close).
BARS = {
    "NVDA": {"2026-09-30": (229.27, 232.37, 228.17, 228.38), "2026-10-01": (229.98, 232.29, 228.16, 230.86),
             "2026-10-02": (236.06, 237.88, 233.60, 233.95), "2026-10-05": (236.09, 240.10, 235.15, 238.90),
             "2026-10-06": (242.10, 243.37, 238.93, 239.24)},
    "AAPL": {"2026-09-30": (330.80, 339.50, 330.14, 333.02), "2026-10-01": (330.00, 332.48, 325.81, 330.32),
             "2026-10-02": (333.26, 334.54, 330.61, 333.69), "2026-10-05": (332.82, 336.21, 331.65, 332.89),
             "2026-10-06": (332.28, 334.38, 330.62, 333.63)},
    "JPM": {"2026-09-30": (334.89, 336.34, 330.83, 330.83), "2026-10-01": (328.75, 333.58, 325.87, 333.18),
            "2026-10-02": (334.00, 334.85, 330.00, 332.38), "2026-10-05": (333.31, 333.75, 330.59, 332.38),
            "2026-10-06": (332.73, 333.79, 330.93, 331.28)},
    "RELIANCE": {"2026-09-30": (1182.0, 1196.5, 1181.7, 1187.0), "2026-10-01": (1180.1, 1183.9, 1160.8, 1167.7),
                 "2026-10-05": (1171.2, 1193.0, 1171.2, 1186.4), "2026-10-06": (1188.1, 1219.1, 1188.1, 1218.0)},
    "HDFCBANK": {"2026-09-30": (711.5, 720.3, 708.7, 708.7), "2026-10-01": (708.4, 721.3, 707.1, 721.2),
                 "2026-10-05": (731.95, 734.2, 701.25, 704.8), "2026-10-06": (705.6, 714.7, 701.0, 711.45)},
    "MARUTI": {"2026-09-30": (11901.0, 12065.0, 11879.0, 11967.0), "2026-10-01": (11900.0, 11907.0, 11305.0, 11386.0),
               "2026-10-05": (11386.0, 11544.0, 11305.0, 11532.0), "2026-10-06": (11485.0, 11625.0, 11451.0, 11625.0)},
}
PREV_CLOSE_0929 = {"NVDA": 227.21, "AAPL": 329.40, "JPM": 334.98, "RELIANCE": 1182.0, "HDFCBANK": 722.7,
                   "MARUTI": 11877.0}
CLOSE_0928 = {"NVDA": 228.86, "AAPL": 338.40, "JPM": 336.59, "RELIANCE": 1197.6, "HDFCBANK": 719.05, "MARUTI": 12008.0}
# Benchmark and sector: (open of 2026-09-30, close per date).
INDEX = {
    "SPY": (766.45, {"2026-10-01": 763.99, "2026-10-02": 769.64, "2026-10-05": 774.83, "2026-10-06": 779.09}),
    "XLK": (195.47, {"2026-10-01": 197.81, "2026-10-02": 199.81, "2026-10-05": 200.93, "2026-10-06": 202.00}),
    "XLF": (53.99, {"2026-10-01": 53.46, "2026-10-02": 53.49, "2026-10-05": 53.88, "2026-10-06": 54.01}),
    "NIFTY50": (22665.0, {"2026-10-01": 22421.9492, "2026-10-05": 22555.75, "2026-10-06": 22776.0996}),
    "NIFTYBANK": (54175.8984, {"2026-10-01": 54450.75, "2026-10-05": 54714.1016, "2026-10-06": 55128.3984}),
    "ONGC": (230.21, {"2026-10-01": 222.37, "2026-10-05": 224.9, "2026-10-06": 224.2}),
}
COMPANIES = {
    "india": {"RELIANCE": ("Reliance Industries", "Energy", "RELIANCE.NS", 0.94, "NIFTY50", "ONGC"),
              "HDFCBANK": ("HDFC Bank", "Banks", "HDFCBANK.NS", 1.234, "NIFTY50", "NIFTYBANK"),
              "MARUTI": ("Maruti Suzuki", "Autos", "MARUTI.NS", 1.09, "NIFTY50", None)},
    "us": {"NVDA": ("Nvidia", "Tech", "NVDA", 1.874, "SPY", "XLK"),
           "AAPL": ("Apple", "Tech", "AAPL", 0.682, "SPY", "XLK"),
           "JPM": ("JPMorgan", "Banks", "JPM", 0.785, "SPY", "XLF")},
}
CIK = {"NVDA": "0001045810", "AAPL": "0000320193", "JPM": "0000019617"}
TODAY_CLOSE = {"NVDA": 239.24, "AAPL": 333.63, "JPM": 331.28, "RELIANCE": 1218.0, "HDFCBANK": 711.45, "MARUTI": 11625.0}
SIGMA_1D = {"NVDA": 0.019129, "AAPL": 0.013523, "JPM": 0.011005,   # stored 1d ranges, as_of 2026-10-06
            "RELIANCE": 0.040221 / math.sqrt(5), "HDFCBANK": 0.039704 / math.sqrt(5), "MARUTI": 0.045624 / math.sqrt(5)}
NEWS_STATUS = {"a41c9e07b2d35f18": "corroborated", "nse-ann-7781203": "confirmed_primary",   # news_item.json
               "d93b1f5e7c2a4b60": "corroborated", "nse-ann-7790412": "confirmed_primary"}
# Verified news first seen inside the example trades' windows (id, first_seen_at, sentiment): news_item.json.
WINDOW_NEWS = {"NVDA": [("d93b1f5e7c2a4b60", "2026-10-02T14:10:00Z", 0.5)],
               "RELIANCE": [("nse-ann-7790412", "2026-10-05T09:20:00Z", 0.4)]}
REGIME = {"india": "EVENT_HEAVY", "us": "TRENDING"}   # stored regime, as_of 2026-10-06
# Invented reference probabilities P(up) per horizon N+1..N+5 (today: as_of 2026-10-06; past: as_of 2026-09-29).
P_TODAY = {"NVDA": [0.566, 0.571, 0.578, 0.582, 0.585], "AAPL": [0.522, 0.528, 0.531, 0.533, 0.534],
           "JPM": [0.551, 0.556, 0.548, 0.552, 0.559], "RELIANCE": [0.561, 0.567, 0.572, 0.570, 0.575],
           "HDFCBANK": [0.470, 0.471, 0.469, 0.470, 0.471], "MARUTI": [0.552, 0.548, 0.555, 0.558, 0.561]}
P_PAST = {"NVDA": [0.571, 0.574, 0.583, 0.586, 0.584], "AAPL": [0.553, 0.562, 0.556, 0.551, 0.550],
          "JPM": [0.557, 0.551, 0.549, 0.548, 0.546], "RELIANCE": [0.558, 0.561, 0.569, 0.566, 0.565],
          "HDFCBANK": [0.552, 0.558, 0.551, 0.549, 0.548], "MARUTI": [0.556, 0.553, 0.551, 0.550, 0.549]}
OFFSET = {"rule.model_news.v1": 0.0, "rule.model_news_half.v1": -0.006, "rule.model_news_double.v1": 0.012,
          "rule.model_news_confirmed.v1": -0.004, "rule.model_news_high.v1": -0.008,
          "rule.model_news_global.v1": 0.007, "rule.model_news_calm.v1": 0.0, "rule.model_news_strict.v1": 0.0,
          "base.model_only.v1": -0.012, "ai.news_results.sonnet.v1": 0.010, "ai.pattern_mood.sonnet.v1": -0.010,
          "ai.combined.sonnet.v1": 0.020, "ai.combined.opus.v1": 0.030}


def r2(x: float) -> float:
    return round(x, 2)


def r4(x: float) -> float:
    return round(x, 4)


def market_of(ticker: str) -> str:
    return "india" if ticker in COMPANIES["india"] else "us"


def exits(market: str, entry: date, count: int = 5) -> list[str]:
    cfg, day, out = load_market(market), entry, []
    for _ in range(count):
        day = calendar.next_session(cfg, day, include=False)
        out.append(str(day))
    return out


def strategies() -> list[dict]:
    return yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]


def cost_views(market: str, entry_value: float, exit_value: float, quantity: float) -> dict:
    """Both views of one round trip with B2's engine (marketbrief/lab/costs.py, config/costs.yaml `broker:` rates);
    US orders converted at the example EUR/USD."""
    return lab_costs.cost_views(market, lab_costs.rates(market), (entry_value, exit_value), quantity,
                                {"eurusd": (EURUSD, EURUSD)})


def costs(market: str, entry_value: float, exit_value: float, quantity: float) -> tuple[float, dict]:
    """The market view (F1.6): what paper_trades_settled `costs` and `cost_lines` hold."""
    view = cost_views(market, entry_value, exit_value, quantity)["market"]
    return view["total"], view["lines"]


def band(ticker: str, base: float, k: int, p: float, widen: float = 0.0) -> dict:
    """Target and 50/80% bands around the log centre; an AI widening multiplies sigma by (1 + widen), as
    analytics/range_row.py does (the centre is not moved by it)."""
    sigma = SIGMA_1D[ticker] * math.sqrt(k)
    center = (p - 0.5) * sigma
    wide = sigma * (1 + widen)
    return {"target_price": r2(base * math.exp(center)), "lo50": r2(base * math.exp(center - 0.6745 * wide)),
            "hi50": r2(base * math.exp(center + 0.6745 * wide)), "lo80": r2(base * math.exp(center - 1.2816 * wide)),
            "hi80": r2(base * math.exp(center + 1.2816 * wide))}


def prediction(spec: dict, ticker: str, as_of: str, base: float, k: int, p_ref: float,  # noqa: PLR0913
               momentum_up: bool) -> dict:
    market = market_of(ticker)
    entry = str(calendar.next_session(load_market(market), date.fromisoformat(as_of), include=False))
    signal = spec["parameters"].get("signal")
    if signal == "always_up":
        prob, direction = None, "up"
    elif signal == "momentum":
        prob, direction = None, ("up" if momentum_up else "down")
    else:
        prob = r4(p_ref + OFFSET[spec["id"]])
        direction = "up" if prob >= 0.5 else "down"
    threshold = spec["threshold"]
    qualifies = direction == "up" and (prob is None or prob >= threshold)
    if spec["parameters"].get("regime_filter") and REGIME[market] in ("UNSTABLE", "EVENT_HEAVY"):
        qualifies = False
    family, is_ai = spec["family"], spec["family"] == "ai"
    widen = 0.1 if is_ai else 0.0
    rng = band(ticker, base, k, prob if prob is not None else 0.5, widen)
    sid = f"{as_of}-{ticker}-{k}d"
    anchored = spec["id"].startswith("ai.combined")
    uses_model = signal == "model" or anchored
    news_id = {"NVDA": "a41c9e07b2d35f18", "RELIANCE": "nse-ann-7781203"}.get(ticker)   # JPM's item is a rumour
    uses_news = (is_ai and spec["id"] != "ai.pattern_mood.sonnet.v1") or (family == "rule" and news_id)
    evidence = ([news_id] if uses_news and news_id else []) + ([f"model_scores:{sid}"] if uses_model else []) + (
        [f"features:{as_of}-{ticker}"] if not is_ai or spec["id"] == "ai.pattern_mood.sonnet.v1" else [])
    reason = None
    if is_ai:
        reason = {"NVDA": "Verified report of new data-centre orders (corroborated) and a steady uptrend; the model "
                          "already leans up, so only a small upward adjustment.",
                  "RELIANCE": "Exchange filing confirms the retail unit's capital raise; price recovered above its "
                              "20-day high. Regime is event-heavy, so the probability stays modest."}.get(
            ticker, "No verified company news; follows the model with no change.")
    model_prob = r4(p_ref) if anchored else None
    adjustment = r4(prob - p_ref) if anchored and prob is not None else None
    return {
        "id": f"{spec['id']}:{sid}", "strategy_id": spec["id"], "family": family, "market": market, "ticker": ticker,
        "made_at": f"{entry}{MADE_AT[market]}", "as_of_date": as_of, "session_date": entry,
        "exit_date": exit_for(market, entry, k),
        "horizon_days": k, "direction": direction, "prob_up": prob,
        "confidence": None if prob is None else r4(max(prob, 1 - prob)), "threshold": threshold,
        "qualifies": qualifies, "base_close": base, "target_price": rng["target_price"], "range_id": sid,
        "lo50": rng["lo50"], "hi50": rng["hi50"], "lo80": rng["lo80"], "hi80": rng["hi80"], "range_widen": widen,
        "model_score_id": sid if uses_model else None, "model_prob": model_prob, "agent_adjustment": adjustment,
        "adjustment_reason": "Corroborated news not yet in the model's news term" if adjustment else None,
        "evidence_ids": evidence, "reason": reason, "regime": REGIME[market], "quality": "OK",
        "amount": amount_of(ticker), "currency": CURRENCY[market],
        "config_hash": f"sha256:{hash_id(spec['id']):016x}",
        "prompt_version": "trader-v1" if is_ai else None, "method_version": "lab-v1",
    }


def exit_for(market: str, entry: str, k: int) -> str:
    """The k-th session after D (N+k, decision 37)."""
    return exits(market, date.fromisoformat(entry))[k - 1]


def hash_id(text: str) -> int:
    value = 0
    for char in text:
        value = (value * 131 + ord(char)) % (1 << 64)
    return value


def amount_of(ticker: str) -> float:
    return 10000.0 if ticker == "MARUTI" else DEFAULT_AMOUNT[market_of(ticker)]


def settle(pred: dict, view: str, pick_rule: str | None, pick_id: str | None) -> dict:
    market, ticker, k = pred["market"], pred["ticker"], pred["horizon_days"]
    entry_date, exit_date = pred["session_date"], pred["exit_date"]
    amount = pred["amount"]
    entry_price = BARS[ticker][entry_date][0]
    trade_id = f"acc:{pred['id']}" if view == "accuracy" else f"h2h:{pick_rule}:{pred['id']}"
    settled_at = f"{exit_date}T{'12:15:00Z' if market == 'india' else '22:15:00Z'}"
    row = dict.fromkeys(SCHEMAS["paper_trades_settled"][1])
    row.update(id=f"{trade_id}@{settled_at.replace('-', '').replace(':', '')}", trade_id=trade_id,
               prediction_id=pred["id"], strategy_id=pred["strategy_id"], family=pred["family"], view=view,
               pick_rule=pick_rule, pick_id=pick_id, market=market, ticker=ticker, horizon_days=k,
               made_at=pred["made_at"], entry_date=entry_date, exit_date=exit_date, amount=amount,
               currency=pred["currency"], prob_up=pred["prob_up"], target_price=pred["target_price"],
               lo80=pred["lo80"], hi80=pred["hi80"], regime=pred["regime"], flags=[], adjustment_ids=[],
               news_ids=[], reason_codes=[], settled_at=settled_at, method_version="engine-v1")
    quantity = math.floor(amount / entry_price) if market == "india" else round(amount / entry_price, 6)
    if quantity == 0:
        row.update(status="skipped_price_above_amount", entry_price=entry_price, quantity=0.0, reason_code=None,
                   reason_detail={"note": f"one share at {entry_price} costs more than the amount {amount}"})
        return row
    window = [d for d in BARS[ticker] if entry_date <= d <= exit_date]
    exit_price = BARS[ticker][exit_date][3]
    entry_value, exit_value = r2(quantity * entry_price), r2(quantity * exit_price)
    total, lines = costs(market, entry_value, exit_value, quantity)
    gross = r2(exit_value - entry_value)
    net = r2(gross - total)
    highs, lows = [BARS[ticker][d][1] for d in window], [BARS[ticker][d][2] for d in window]
    reached = [i + 1 for i, high in enumerate(highs) if high >= pred["target_price"]]
    move = (exit_price / entry_price - 1) * 100
    name, sector, _yahoo, beta, bench, sector_symbol = COMPANIES[market][ticker]
    bench_move = (INDEX[bench][1][exit_date] / INDEX[bench][0] - 1) * 100
    market_part = beta * bench_move
    sector_part = ((INDEX[sector_symbol][1][exit_date] / INDEX[sector_symbol][0] - 1) * 100 - bench_move
                   if sector_symbol else 0.0)
    rest = move - market_part - sector_part
    news_ids, news_part = window_news(market, ticker, entry_date, exit_date, rest)
    company_part = move - market_part - sector_part - news_part
    parts = {"market": market_part, "sector": sector_part, "news": news_part, "company": company_part}
    main = max(parts, key=lambda key: abs(parts[key]))
    code = {"market": "market_up" if market_part > 0 else "market_down",
            "sector": "sector_lift" if sector_part > 0 else "sector_drag",
            "news": "news_positive" if news_part > 0 else "news_negative", "company": "company_specific"}[main]
    codes = [code] + (["target_reached"] if reached else []) + (
        [] if pred["lo80"] <= exit_price <= pred["hi80"] else ["range_missed"])
    row.update(status="settled", exit_date_actual=exit_date, entry_price=entry_price, exit_price=exit_price,
               quantity=float(quantity), exit_quantity=float(quantity), entry_value=entry_value, exit_value=exit_value,
               gross_pnl=gross, costs=total, cost_lines=lines, net_pnl=net, return_pct=r2(net / amount * 100),
               target_error_pct=r2((exit_price / pred["target_price"] - 1) * 100),
               range_hit=pred["lo80"] <= exit_price <= pred["hi80"], target_reached=bool(reached),
               target_reached_session=reached[0] if reached else None,
               max_favourable_pct=r2((max(highs) / entry_price - 1) * 100),
               max_adverse_pct=r2((min(lows) / entry_price - 1) * 100), move_pct=r2(move), market_pct=r2(market_part),
               sector_pct=r2(sector_part), news_pct=r2(news_part),
               company_pct=r2(move) - r2(market_part) - r2(sector_part) - r2(news_part),
               reason_code=code, reason_codes=codes, news_ids=news_ids,
               reason_detail={"benchmark": bench, "benchmark_pct": r2(bench_move), "beta": beta,
                              "sector_source": sector_symbol or "none",
                              "news_statuses": {i: NEWS_STATUS[i] for i in news_ids}})
    row["company_pct"] = r2(row["company_pct"]) + 0.0   # + 0.0: no "-0.0" in the files
    return row


def window_news(market: str, ticker: str, entry_date: str, exit_date: str, rest: float) -> tuple[list[str], float]:
    """B2's rule (lab/reasons.py): the rest of the move (after market and sector) goes to news only when verified
    news (confirmed_primary or corroborated) was first seen from D's open to the exit close and its summed sentiment
    has the rest's sign; else 0. The same for every strategy holding that company over that window."""
    cfg = load_market(market)
    start = calendar.session_open_utc(cfg, date.fromisoformat(entry_date)).isoformat().replace("+00:00", "Z")
    end = calendar.session_close_utc(cfg, date.fromisoformat(exit_date)).isoformat().replace("+00:00", "Z")
    inside = [n for n in WINDOW_NEWS.get(ticker, []) if start <= n[1] <= end
              and NEWS_STATUS[n[0]] in ("confirmed_primary", "corroborated")]
    mood = sum(n[2] for n in inside)
    if not inside or mood == 0 or (mood > 0) != (rest > 0):
        return [], 0.0
    return [n[0] for n in inside], rest


def write(name: str, entity: str, kind: str | None, records: list, extra: dict | None = None) -> None:
    if kind:
        columns = list(SCHEMAS[kind][1])
        for record in records:
            assert set(record) == set(columns), (name, set(record) ^ set(columns))
        records = [{column: record[column] for column in columns} for record in records]
    body = {"_example": True, "_note": NOTE, "entity": entity, "kind": kind,
            "catalogue": f"docs/DATA_CATALOGUE.md#{entity.replace('_', '-')}", "as_of": "2026-10-07T12:00:00Z",
            **(extra or {}), "records": records}
    (HERE / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    from catalogue_entities import build_all   # the remaining entities (kept apart for the module size limit)

    specs = strategies()
    today_preds, past_preds = [], []
    for ticker in TODAY_CLOSE:
        bars = BARS[ticker]
        momentum_today = bars["2026-10-06"][3] > bars["2026-10-05"][3]
        momentum_past = PREV_CLOSE_0929[ticker] > CLOSE_0928[ticker]
        for spec in specs:
            for k in spec["horizons"]:
                today_preds.append(prediction(spec, ticker, "2026-10-06", TODAY_CLOSE[ticker], k,
                                              P_TODAY[ticker][k - 1], momentum_today))
                past_preds.append(prediction(spec, ticker, "2026-09-29", PREV_CLOSE_0929[ticker], k,
                                             P_PAST[ticker][k - 1], momentum_past))
    build_all(write, settle, today_preds, past_preds, specs)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
