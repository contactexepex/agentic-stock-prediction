"""F1.10 automatic reason of a settled trade (computed, no AI; decision 43). The entry-to-exit move (split
adjusted) is split into parts that add up to it:
  market_pct  = beta x the benchmark's move over the same window (open of D to the exit close; beta = the
                ticker's beta_1y feature as of the prediction, 1 when missing);
  sector_pct  = the sector's move beyond the benchmark: its sector index or ETF (config sector_etf) minus the
                benchmark, else the mean move of the other watchlist tickers of its sector minus the benchmark,
                else 0;
  news_pct    = the rest (move - market - sector), credited to news only when verified news on the company
                (confirmed_primary or corroborated as of settlement, timed from D's open to the exit close) exists
                and its summed sentiment has the rest's sign; else 0;
  company_pct = what is left (company-specific).
reason_code = the code of the largest part by size (market_up/down, sector_lift/drag, news_positive/negative,
company_specific); reason_codes adds target_reached and range_missed."""
from __future__ import annotations

from datetime import date

from marketbrief.core.calendar import session_close_utc, session_open_utc
from marketbrief.core.market_config import benchmark_key
from marketbrief.lab.constants import PCT_DIGITS, PERCENT, VERIFIED_STATUSES
from marketbrief.lab.market_data import MarketData
from marketbrief.utils.timefmt import as_utc_timestamp


def window_move(data: MarketData, symbol: str, entry: date, exit_: date) -> float | None:
    """A symbol's move in % from its open of D to its close of the exit session, split adjusted; None if missing."""
    start, end = data.bar(symbol, entry), data.bar(symbol, exit_)
    if not start or not end or start.get("open") in (None, 0) or end.get("close") is None:
        return None
    factor, _ = data.split_factor(symbol, entry, exit_)
    return (float(end["close"]) / factor / float(start["open"]) - 1) * PERCENT


def sector_part(data: MarketData, ticker: str, window: tuple[date, date], bench: float) -> tuple[float, str]:
    """(sector move beyond the benchmark in %, its source: the index key, 'peers:<n>' or 'none')."""
    meta = data.cfg["tickers"].get(ticker) or {}
    index = meta.get("sector_etf")
    if index:
        move = window_move(data, index, *window)
        if move is not None:
            return move - bench, index
    peers = [t for t, m in data.cfg["tickers"].items() if t != ticker and m.get("sector") == meta.get("sector")]
    moves = [m for m in (window_move(data, peer, *window) for peer in sorted(peers)) if m is not None]
    if moves:
        return sum(moves) / len(moves) - bench, f"peers:{len(moves)}"
    return 0.0, "none"


def verified_news(data: MarketData, ticker: str, window: tuple[date, date]) -> list[dict]:
    """Verified news items on the ticker timed from D's open to the exit close, by time then id."""
    start, end = session_open_utc(data.cfg, window[0]), session_close_utc(data.cfg, window[1])
    items = [item for item in data.news if item["ticker"] == ticker and item.get("status") in VERIFIED_STATUSES
             and start <= as_utc_timestamp(item["ts"]).to_pydatetime() <= end]
    return sorted(items, key=lambda item: (str(item["ts"]), item["id"]))


def main_code(parts: dict[str, float]) -> str:
    """The reason code of the largest part (ties: market, sector, news, company)."""
    name = max(("market", "sector", "news", "company"), key=lambda key: abs(parts[key]))
    value = parts[name]
    return {"market": "market_up" if value > 0 else "market_down",
            "sector": "sector_lift" if value > 0 else "sector_drag",
            "news": "news_positive" if value > 0 else "news_negative", "company": "company_specific"}[name]


def automatic_reason(data: MarketData, ticker: str, window: tuple[date, date], move_pct: float,
                     hits: tuple[bool, bool | None]) -> dict:
    """The reason columns of one settled trade. window = (D, the exit session used); hits = (target_reached,
    range_hit)."""
    bench_key = benchmark_key(data.cfg)
    bench = window_move(data, bench_key, *window) if bench_key else None
    beta = data.betas.get(ticker)
    market = (1.0 if beta is None else float(beta)) * (bench or 0.0)
    sector, source = sector_part(data, ticker, window, bench or 0.0) if bench is not None else (0.0, "none")
    news = verified_news(data, ticker, window)
    rest = move_pct - market - sector
    tone = sum(float(item.get("sentiment") or 0.0) for item in news)
    news_part = rest if news and tone and (rest > 0) == (tone > 0) else 0.0
    parts = {key: round(value, PCT_DIGITS) for key, value in
             {"market": market, "sector": sector, "news": news_part}.items()}
    parts["company"] = round(round(move_pct, PCT_DIGITS) - parts["market"] - parts["sector"] - parts["news"],
                             PCT_DIGITS)
    code = main_code(parts)
    codes = [code] + (["target_reached"] if hits[0] else []) + (["range_missed"] if hits[1] is False else [])
    detail = {"benchmark": bench_key, "benchmark_pct": None if bench is None else round(bench, PCT_DIGITS),
              "beta": None if beta is None else float(beta), "beta_source": "features.beta_1y" if beta is not None
              else "default_1", "sector_source": source, "news_sentiment": round(tone, PCT_DIGITS),
              "news_statuses": {item["id"]: item["status"] for item in news},
              "news_rule": "rest credited to verified news only when the news sentiment has its sign"}
    return {"move_pct": round(move_pct, PCT_DIGITS), "market_pct": parts["market"], "sector_pct": parts["sector"],
            "news_pct": parts["news"], "company_pct": parts["company"], "reason_code": code, "reason_codes": codes,
            "news_ids": [item["id"] for item in news], "reason_detail": detail}
