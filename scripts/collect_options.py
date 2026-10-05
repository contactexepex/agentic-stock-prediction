#!/usr/bin/env python3
"""Snapshot near-the-money implied volatility per watchlist ticker from yfinance option chains
into data/<market>/options/YYYY/MM/<today>.jsonl. Only for markets with `options: yfinance`
(the US); other markets are skipped cleanly (no free option chains for India).

Per ticker, the nearest expiries (1 to --max-days calendar days out, at most --expiries of them):
call and put implied vol interpolated to the spot price, their average (`atm_iv`, annualized)
and the at-the-money straddle (mid price, also as % of spot: roughly the implied move to that
expiry). Quotes with no bid or an implausible IV are ignored. Append-only: id
<date>-<ticker>-<expiry> is written once per UTC day. ranges.py blends `atm_iv` into the width
(docs/DESIGN.md section 4). A ticker that ends with no snapshot today (Yahoo returned no expiries,
none in the window, or no usable chain) is listed in `failed` with the reason."""
from __future__ import annotations

import json
import math
import sys
from datetime import date

import pandas as pd

from common import append_jsonl, day_file, market_arg, recent_ids, require_market, utc_now, utc_today

MIN_IV, MAX_IV = 0.01, 5.0


def _usable(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["strike", "impliedVolatility", "bid", "ask", "lastPrice"])
    df = df[(df["impliedVolatility"] > MIN_IV) & (df["impliedVolatility"] < MAX_IV)].sort_values("strike")
    quoted = df[(df["bid"].fillna(0) > 0) & (df["ask"].fillna(0) > 0)]
    return quoted if len(quoted) >= 2 else df


def iv_at(df: pd.DataFrame, spot: float) -> float | None:
    """Implied vol linearly interpolated in strike to the spot price."""
    df = _usable(df)
    if df.empty:
        return None
    below, above = df[df["strike"] <= spot].tail(1), df[df["strike"] >= spot].head(1)
    if below.empty or above.empty:
        return float((below if not below.empty else above)["impliedVolatility"].iloc[0])
    k0, k1 = float(below["strike"].iloc[0]), float(above["strike"].iloc[0])
    v0, v1 = float(below["impliedVolatility"].iloc[0]), float(above["impliedVolatility"].iloc[0])
    return v0 if k1 == k0 else v0 + (v1 - v0) * (spot - k0) / (k1 - k0)


def _price(row) -> float | None:
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    last = row.get("lastPrice")
    return float(last) if last is not None and last == last and last > 0 else None


def straddle(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> tuple[float | None, float | None]:
    """(strike, call + put price) at the listed strike nearest the spot."""
    if calls is None or puts is None or calls.empty or puts.empty:
        return None, None
    common = sorted(set(calls["strike"]) & set(puts["strike"]), key=lambda k: abs(k - spot))
    if not common:
        return None, None
    k = common[0]
    c, p = _price(calls[calls["strike"] == k].iloc[0]), _price(puts[puts["strike"] == k].iloc[0])
    return float(k), (c + p if c is not None and p is not None else None)


def snapshot(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> dict | None:
    civ, piv = iv_at(calls, spot), iv_at(puts, spot)
    ivs = [v for v in (civ, piv) if v is not None]
    if not ivs or not spot or spot <= 0:
        return None
    k, st = straddle(calls, puts, spot)
    r = lambda v, n=6: None if v is None or not math.isfinite(v) else round(v, n)  # noqa: E731
    return {"spot": r(spot, 4), "strike": k, "call_iv": r(civ), "put_iv": r(piv),
            "atm_iv": r(sum(ivs) / len(ivs)), "straddle": r(st, 4),
            "straddle_pct": r(st / spot) if st else None}


def no_chain_reason(listed: bool, expiries: list[str], max_days: int) -> str:
    """Why a ticker got no snapshot: Yahoo listed no expiries at all (an empty answer, e.g. a
    blocked or failed request), none falls in the window, or no chain had a usable implied vol."""
    if not listed:
        return "no option expiries returned"
    if not expiries:
        return f"no expiry within 1-{max_days} days"
    return "no usable chain (no quote with a plausible implied vol)"


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--expiries", type=int, default=4, help="nearest expiries per ticker (default 4)")
    ap.add_argument("--max-days", type=int, default=45, help="ignore expiries further out (default 45)")
    args = ap.parse_args()
    cfg = require_market(args)
    market = cfg["market"]
    if cfg.get("options") != "yfinance":
        print(json.dumps({"collector": "options", "market": market,
                          "skipped": "no free option chains for this market"}))
        return 0
    import yfinance as yf

    now, today = utc_now(), utc_today()
    seen = recent_ids(market, "options", days=2)
    rows, failed = [], []
    for key, meta in cfg["tickers"].items():
        try:
            tk = yf.Ticker(meta["yahoo"])
            expiries = [e for e in tk.options if 1 <= (date.fromisoformat(e) - today).days <= args.max_days]
            got, listed = 0, bool(tk.options)   # () when Yahoo's answer has no option result
            for e in expiries[:args.expiries]:
                oid = f"{today}-{key}-{e}"
                if oid in seen:          # already snapshotted today
                    got += 1
                    continue
                ch = tk.option_chain(e)
                und = getattr(ch, "underlying", None) or {}
                spot = und.get("regularMarketPrice") or tk.fast_info["lastPrice"]
                snap = snapshot(ch.calls, ch.puts, float(spot))
                if snap is None:
                    continue
                rows.append({"id": oid, "ticker": key, "collected_at": now, "expiry": e,
                             "days_to_expiry": (date.fromisoformat(e) - today).days, **snap,
                             "source": "yfinance"})
                seen.add(oid)
                got += 1
            if not got:
                failed.append({"ticker": key, "error": no_chain_reason(listed, expiries, args.max_days)})
        except Exception as exc:
            failed.append({"ticker": key, "error": str(exc)[:200]})
    written = append_jsonl(day_file(market, "options", today), rows)
    print(json.dumps({"collector": "options", "market": market, "written": written,
                      "tickers": len({r["ticker"] for r in rows}), "failed": failed}, indent=2))
    return 1 if failed and len(failed) == len(cfg["tickers"]) else 0


if __name__ == "__main__":
    sys.exit(main())
