"""Long daily history for the signal model's backtest, cached under work/ (gitignored), never in data/.

`scripts/model_history.py --market M [--start 2011-01-01]` fetches every watchlist ticker and market-config
symbol of M from Yahoo (yfinance, auto_adjust=False: the basis collect_prices.py stores, i.e. OHLC
split-adjusted as of the fetch, not dividend-adjusted) and writes work/model_history/<market>/bars.csv.gz
plus manifest.json (symbols, Yahoo symbol, rows, first and last date, dropped bars, fetched_at, file size
and SHA-256). The same bars are dropped as collect_prices.py drops them: the bar of the fetch day (and,
for the market's own stocks and indices, bars after the last complete session), a stock or own-exchange
index bar on a day that is no session of the exchange calendar (exchange_calendars from the start date,
plus the config's holidays and special sessions), and a flat zero-volume stock bar.

`model_backtest.py --history` reads data/ plus this cache (merged_bars): data/'s bars win on every date
they cover; the cache adds only the dates before a symbol's first stored bar, scaled onto the stored
basis by the median stored/cache close ratio over the first HISTORY_OVERLAP_DATES common dates (1 when
they agree; the ratio and the largest deviation are reported). Limits (docs/DESIGN.md section 15):
today's watchlist (survivorship bias: companies that left the index or failed are absent), and the
split adjustment of old bars is Yahoo's as of the fetch, not what was known at the time (returns are
ratios, so a consistent re-basing does not leak; a wrong split factor would show as a one-day jump)."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from marketbrief.constants.config_keys import CFG_SYMBOLS, CFG_TICKERS, META_ROLE, META_YAHOO
from marketbrief.constants.model import (DIR_MODEL_HISTORY, FILE_HISTORY_BARS, FILE_HISTORY_MANIFEST, HISTORY_BASIS,
                                         HISTORY_COLUMNS, HISTORY_DEFAULT_START, HISTORY_OVERLAP_DATES,
                                         MSG_NO_HISTORY)
from marketbrief.constants.prices import OWN_EXCHANGE_ROLES, PRICE_DECIMALS
from marketbrief.core import paths
from marketbrief.core.calendar import extra_holidays, last_complete_session, special_sessions
from marketbrief.core.cli import market_arg
from marketbrief.core.market_config import load_market, market_names

OHLC = ["open", "high", "low", "close"]


def cache_dir(market: str):
    """work/model_history/<market> under the data root."""
    return paths.ROOT / DIR_MODEL_HISTORY / market


def own_sessions(cfg: dict, start: date, end: date) -> set[date]:
    """The market's sessions from start to end: the exchange calendar from `start` (not the library's
    default window), plus special sessions, minus the config's extra holidays; weekdays past its range."""
    import exchange_calendars

    calendar = exchange_calendars.get_calendar(cfg["calendar"], start=start.isoformat())
    last = calendar.last_session.date()
    first = calendar.first_session.date()   # the first session on or after `start`
    sessions = {stamp.date() for stamp in calendar.sessions_in_range(first.isoformat(), min(end, last).isoformat())}
    if end > last:  # past the library's range: weekdays, as calendar.is_session does
        sessions |= {day.date() for day in pd.bdate_range(last, end)} - {last}
    return (sessions | special_sessions(cfg)) - extra_holidays(cfg)


def is_own(cfg: dict, key: str) -> bool:
    """A watchlist stock or an index of the market's own exchange (follows the market calendar)."""
    return key in cfg[CFG_TICKERS] or cfg[CFG_SYMBOLS].get(key, {}).get(META_ROLE) in OWN_EXCHANGE_ROLES


def clean_frame(cfg: dict, key: str, frame: pd.DataFrame, cut: dict) -> tuple[pd.DataFrame, dict]:
    """The frame's final bars as HISTORY_COLUMNS rows and the counts of dropped bars.
    cut: {today, own_through, sessions}."""
    out = pd.DataFrame({"date": [stamp.date() for stamp in frame.index],
                        **{col: frame[col.capitalize()].to_numpy(dtype=float) for col in OHLC},
                        "volume": frame["Volume"].fillna(0).to_numpy(dtype=float)})
    out = out[out[OHLC].notna().all(axis=1)]
    own = is_own(cfg, key)
    final = out["date"] <= cut["own_through"] if own else out["date"] < cut["today"]
    out = out[final]
    off_day = out["date"].map(lambda day: day not in cut["sessions"]) if own else pd.Series(False, index=out.index)
    flat = (out[OHLC].nunique(axis=1) == 1) & (out["volume"] == 0) & (key in cfg[CFG_TICKERS])
    counts = {"dropped_non_session": int(off_day.sum()), "dropped_flat_zero_volume": int((flat & ~off_day).sum())}
    out = out[~off_day & ~flat].copy()
    out[OHLC] = out[OHLC].round(PRICE_DECIMALS)
    out["volume"] = out["volume"].astype("int64")
    return out.assign(ticker=key)[list(HISTORY_COLUMNS)], counts


def fetch_market(cfg: dict, start: date, yfinance, now: datetime | None = None) -> dict:
    """Fetch, clean and write one market's cache; returns the manifest."""
    now = now or datetime.now(timezone.utc)
    targets = {**{k: m[META_YAHOO] for k, m in cfg[CFG_SYMBOLS].items()},
               **{k: m[META_YAHOO] for k, m in cfg[CFG_TICKERS].items()}}
    cut = {"today": now.date(), "own_through": last_complete_session(cfg, now),
           "sessions": own_sessions(cfg, start, now.date())}
    frames, symbols, failed = [], {}, []
    for key, symbol in targets.items():
        try:
            frame = yfinance.Ticker(symbol).history(start=start.isoformat(), interval="1d", auto_adjust=False)
        except Exception as exc:  # one symbol's error must not stop the others
            failed.append({"ticker": key, "yahoo": symbol, "error": str(exc)[:200]})
            continue
        if frame is None or frame.empty:
            failed.append({"ticker": key, "yahoo": symbol, "error": "no data"})
            continue
        rows, counts = clean_frame(cfg, key, frame, cut)
        frames.append(rows)
        symbols[key] = {"yahoo": symbol, "role": cfg[CFG_SYMBOLS].get(key, {}).get(META_ROLE, "ticker"),
                        "rows": len(rows), "first": str(rows["date"].min()) if len(rows) else None,
                        "last": str(rows["date"].max()) if len(rows) else None, **counts}
    bars = pd.concat(frames).sort_values(["ticker", "date"]) if frames else pd.DataFrame(columns=HISTORY_COLUMNS)
    payload = gzip.compress(bars.to_csv(index=False).encode(), mtime=0)
    folder = cache_dir(cfg["market"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE_HISTORY_BARS).write_bytes(payload)
    manifest = {"market": cfg["market"], "fetched_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "start": start.isoformat(), "basis": HISTORY_BASIS, "file": FILE_HISTORY_BARS,
                "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "rows": len(bars),
                "symbols": symbols, "failed": failed}
    (folder / FILE_HISTORY_MANIFEST).write_text(json.dumps(manifest, indent=1))
    return manifest


def load_cache(market: str) -> tuple[dict[str, pd.DataFrame], dict]:
    """({symbol: bars indexed by date}, manifest) of a market's cache; exits when there is none."""
    folder = cache_dir(market)
    path = folder / FILE_HISTORY_BARS
    if not path.exists():
        raise SystemExit(MSG_NO_HISTORY.format(market=market, path=path))
    bars = pd.read_csv(io.BytesIO(gzip.decompress(path.read_bytes())), parse_dates=["date"])
    manifest = json.loads((folder / FILE_HISTORY_MANIFEST).read_text())
    return {key: group.set_index("date").drop(columns="ticker") for key, group in bars.groupby("ticker")}, manifest


def splice(stored: pd.DataFrame, cached: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Stored bars plus the cache's earlier bars on the stored basis, and the splice diagnostics."""
    first = stored.index[0]
    common = cached.index.intersection(stored.index)[:HISTORY_OVERLAP_DATES]
    ratios = (stored.loc[common, "close"] / cached.loc[common, "close"]).to_numpy(dtype=float)
    ratio = float(np.median(ratios)) if len(ratios) else 1.0
    earlier = cached[cached.index < first].copy()
    earlier[OHLC] = earlier[OHLC] * ratio
    earlier["volume"] = earlier["volume"] / ratio
    diag = {"cache_rows": len(earlier), "overlap_dates": len(common), "ratio": round(ratio, 6),
            "max_overlap_deviation": round(float(np.max(np.abs(ratios / ratio - 1))), 6) if len(ratios) else None}
    return pd.concat([earlier[stored.columns], stored]), diag


def merged_bars(stored: dict[str, pd.DataFrame], cached: dict[str, pd.DataFrame]) -> tuple[dict, dict]:
    """({symbol: bars} of data/ plus the cache's earlier dates, {symbol: splice diagnostics})."""
    out, diagnostics = {}, {}
    for key in sorted(set(stored) | set(cached)):
        own, extra = stored.get(key), cached.get(key)
        if extra is None or extra.empty:
            out[key] = own
        elif own is None or own.empty:
            out[key] = extra[["open", "high", "low", "close", "volume"]]
            diagnostics[key] = {"cache_rows": len(extra), "overlap_dates": 0, "ratio": 1.0,
                                "max_overlap_deviation": None}
        else:
            out[key], diagnostics[key] = splice(own, extra)
    return out, diagnostics


def main() -> int:
    """Entry point of scripts/model_history.py (all markets unless --market)."""
    parser = market_arg(__doc__)
    parser.add_argument("--start", default=HISTORY_DEFAULT_START, help="first date to fetch (YYYY-MM-DD)")
    args = parser.parse_args()
    import yfinance  # imported here so the rest of the repo works without it

    out = {}
    for market in [args.market] if args.market else market_names():
        manifest = fetch_market(load_market(market), date.fromisoformat(args.start), yfinance)
        out[market] = {k: manifest[k] for k in ("fetched_at", "start", "rows", "bytes", "failed")}
        out[market]["path"] = str(cache_dir(market))
    print(json.dumps(out, indent=1))
    return 0
