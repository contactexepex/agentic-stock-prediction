"""One ticker's row of a check: measures, flags and attribution candidates (the inputs come from check.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from marketbrief.core.calendar import prev_session
from marketbrief.constants.config_keys import META_SECTOR, META_SECTOR_ETF, META_YAHOO
from marketbrief.core.schema_intraday import INTRADAY_SCHEMAS
from marketbrief.intraday import attribution, inputs
from marketbrief.intraday.constants import (
    FLAG_OPEN_TRADE,
    KIND_INTRADAY_CHECKS,
    METHOD_VERSION,
    QUALITY_NO_QUOTE,
    QUALITY_OK,
    SECTOR_SOURCE_ETF,
    SECTOR_SOURCE_PEERS,
)
from marketbrief.intraday.measures import (
    band_position,
    elapsed_fraction,
    flags_for,
    is_trigger,
    judge_call,
    residual,
    rounded,
    scaled,
)
from marketbrief.intraday.quotes import SessionQuote
from marketbrief.intraday.settings import configured_horizons, row_id
from marketbrief.intraday.trade_rows import trade_pair

LEGACY_HORIZONS = {1: ("lo80", "lo50", "hi50", "hi80"), 5: ("lo80", "hi80")}   # WS5's _1d / _5d columns
BAND_FIELDS = ("range_id", "lo80", "lo50", "hi50", "hi80", "sigma_h")


@dataclass
class CheckContext:
    """Everything a check knows at check_at (read once, shared by the tickers' rows)."""

    cfg: dict
    settings: dict
    con: object
    check_id: str
    check_at: datetime
    session_date: date
    session_open: datetime
    session_close: datetime
    computed_at: str
    quotes: dict = field(default_factory=dict)        # symbol key -> SessionQuote | None
    stale: dict = field(default_factory=dict)         # symbol key -> quality when not ok
    ranges: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    prev_closes: dict = field(default_factory=dict)   # symbol -> (close, date) as stored by check_at
    entry_prices: dict = field(default_factory=dict)  # (ticker, date, open|close) -> price
    market_moves: dict = field(default_factory=dict)  # benchmark key, cue snapshot
    news_since: datetime | None = None                # start of the news window (attribution.news_window)
    trades: dict = field(default_factory=dict)        # B9: ticker -> open paper trades (trades.open_trades)
    trade_bars: dict = field(default_factory=dict)    # B9: (ticker, date) -> raw daily bar of a holding window
    adjustments: dict = field(default_factory=dict)   # B9: ticker -> [(ex_date, factor)] detected by check_at
    trade_checks: list = field(default_factory=list)  # B9: the trade_checks rows written by this check
    trade_details: list = field(default_factory=list)  # B9: their trade_check_details rows
    skipped_trades: list = field(default_factory=list)  # B9: trade ids skipped (India: a share above the amount)

    def range_horizons(self) -> set[int]:
        """Every horizon with a published range for this session (any ticker), or the configured ones when none
        is published (each missing horizon is then noted on every row, as WS5 noted no_range_1d/5d)."""
        found = {horizon for bands in self.ranges.values() for horizon in bands}
        return found or set(configured_horizons()) or set(LEGACY_HORIZONS)

    def ret(self, key: str | None) -> float | None:
        """Return since the open of a symbol whose quote is fresh."""
        quote = self.quotes.get(key) if key else None
        if quote is None or self.stale.get(key):
            return None
        return quote.last_price / quote.open_price - 1 if quote.open_price else None


def sector_move(ctx: CheckContext, ticker: str, meta: dict) -> tuple[str | None, float | None, str | None]:
    """(candidate key, return, source): the sector ETF/index when it has a fresh quote, else the mean of the
    sector's other watchlist tickers with fresh quotes."""
    etf = meta.get(META_SECTOR_ETF)
    if etf and ctx.ret(etf) is not None:
        return etf, ctx.ret(etf), SECTOR_SOURCE_ETF
    sector = meta.get(META_SECTOR)
    peers = [peer for peer in ctx.cfg.get("sectors", {}).get(sector, []) if peer != ticker]
    moves = [ctx.ret(peer) for peer in peers if ctx.ret(peer) is not None]
    if not sector or not moves:
        return None, None, None
    return sector.replace(" ", "_"), sum(moves) / len(moves), SECTOR_SOURCE_PEERS


def beta_for(ctx: CheckContext, ticker: str, notes: list[str]) -> float:
    """beta_1y of the features, clipped; the configured default when missing (noted)."""
    measures = ctx.settings["measures"]
    beta = (ctx.features.get(ticker) or {}).get("beta_1y")
    if beta is None:
        notes.append("beta_default")
        return float(measures["default_beta"])
    low, high = measures["beta_clip"]
    return min(max(float(beta), low), high)


def base_row(ctx: CheckContext, ticker: str, meta: dict) -> dict:
    """The identifying columns of a row, every measure empty."""
    return {
        **dict.fromkeys(INTRADAY_SCHEMAS[KIND_INTRADAY_CHECKS][1]),
        "id": row_id(ctx.check_id, ticker), "check_id": ctx.check_id, "check_at": ctx.check_at.isoformat(),
        "session_date": ctx.session_date.isoformat(), "ticker": ticker, "yahoo": meta.get(META_YAHOO, ticker),
        "flags": [], "flagged": False, "candidates": [], "candidate_ids": [], "calls": [], "notes": [],
        "method_version": METHOD_VERSION, "computed_at": ctx.computed_at, "bands": {},
        "open_trades": len(ctx.trades.get(ticker, [])),
    }


def ticker_row(ctx: CheckContext, ticker: str, meta: dict) -> dict:
    """The full row of one watchlist ticker, after its open trades' rows (added to ctx.trade_checks)."""
    row = base_row(ctx, ticker, meta)
    quote: SessionQuote | None = ctx.quotes.get(ticker)
    if quote is None or ctx.stale.get(ticker):
        row["quality"] = ctx.stale.get(ticker) or QUALITY_NO_QUOTE
        if quote is not None:
            row.update(last_price=rounded(quote.last_price, 4), last_time=quote.last_time.isoformat())
        add_trade_rows(ctx, row, ticker, quote, None, None)
        return row
    row["quality"] = QUALITY_OK
    fill_measures(ctx, row, ticker, meta, quote)
    return row


def add_trade_rows(ctx: CheckContext, row: dict, ticker: str, quote, sigma, elapsed) -> bool:
    """Check the ticker's open trades (B9); True when at least one of them is flagged."""
    flagged = False
    for trade in ctx.trades.get(ticker, []):
        pair = trade_pair(ctx, trade, quote, sigma, elapsed)
        if pair is None:
            ctx.skipped_trades.append(trade["trade_id"])
            continue
        ctx.trade_checks.append(pair[0])
        ctx.trade_details.append(pair[1])
        flagged = flagged or pair[0]["flagged"]
    row["open_trades"] = len(ctx.trades.get(ticker, [])) - sum(
        trade["trade_id"] in ctx.skipped_trades for trade in ctx.trades.get(ticker, []))
    return flagged


def fill_bands(ctx: CheckContext, row: dict, bands: dict[int, dict], price: float) -> None:
    """bands JSON for every published horizon (and WS5's _1d / _5d columns for k = 1 and 5); a horizon published
    for other tickers of the session but missing here is noted no_range_<k>d."""
    for horizon in sorted(set(ctx.range_horizons()) | set(bands)):
        band = bands.get(horizon)
        if not band:
            row["notes"].append(f"no_range_{horizon}d")
            continue
        position = band_position(price, band)
        row["bands"][str(horizon)] = {
            **{key: band["id"] if key == "range_id" else rounded(band.get(key), 6 if key == "sigma_h" else 4)
               for key in BAND_FIELDS}, "band": position}
        if horizon in LEGACY_HORIZONS:
            row[f"range_id_{horizon}d"], row[f"band_{horizon}d"] = band["id"], position
            for key in LEGACY_HORIZONS[horizon]:
                row[f"{key}_{horizon}d"] = rounded(band[key], 4)


def fill_measures(ctx: CheckContext, row: dict, ticker: str, meta: dict, quote: SessionQuote) -> None:
    """Measures, calls, open trades, flags and candidates of a ticker with a fresh quote."""
    settings, notes = ctx.settings, row["notes"]
    bands = ctx.ranges.get(ticker, {})
    shortest = bands.get(min(bands)) if bands else None
    sigma, sigma_note = inputs.daily_sigma(bands, ctx.features.get(ticker))
    if sigma_note:
        notes.append(sigma_note)
    bar_end = quote.last_time + _bar(settings)
    elapsed = elapsed_fraction(bar_end, ctx.session_open, ctx.session_close,
                               settings["measures"]["min_elapsed_fraction"])
    ret = quote.last_price / quote.open_price - 1
    prev, prev_date = ctx.prev_closes.get(ticker, (None, None))
    expected_prev = prev_session(ctx.cfg, ctx.session_date, include=False).isoformat()
    if prev is None:
        notes.append("no_prev_close")
    elif prev_date != expected_prev:
        notes.append(f"prev_close_from_{prev_date}")
    beta, bench_ret = beta_for(ctx, ticker, notes), ctx.ret(ctx.market_moves.get("benchmark"))
    sector_key, sector_ret, sector_source = sector_move(ctx, ticker, meta)
    resid = residual(ret, beta, bench_ret)
    row.update(
        last_price=rounded(quote.last_price, 4), last_time=quote.last_time.isoformat(),
        open_price=rounded(quote.open_price, 4), prev_close=rounded(prev, 4),
        gap=rounded(quote.open_price / prev - 1) if prev else None, ret_since_open=rounded(ret),
        elapsed_fraction=rounded(elapsed, 4), sigma_1d=rounded(sigma), move_z=rounded(scaled(ret, sigma, elapsed), 3),
        bench_ret=rounded(bench_ret), sector_ret=rounded(sector_ret), sector_source=sector_source,
        beta=rounded(beta, 4), residual=rounded(resid), residual_z=rounded(scaled(resid, sigma, elapsed), 3),
        sector_residual=rounded(ret - sector_ret) if sector_ret is not None else None,
    )
    fill_bands(ctx, row, bands, quote.last_price)
    row["calls"] = [_judged(ctx, call, ticker, quote, sigma, elapsed) for call in ctx.calls.get(ticker, [])]
    row["flags"] = flags_for(row, row["calls"], settings)
    if add_trade_rows(ctx, row, ticker, quote, sigma, elapsed):
        row["flags"].append(FLAG_OPEN_TRADE)
    row["flagged"] = any(is_trigger(flag, settings["flag_on"]) for flag in row["flags"])
    if row["flagged"]:
        range_notes = (shortest or {}).get("notes")
        cue_notes = [note for note in (list(range_notes) if range_notes is not None else []) if "cue" in str(note)]
        context = {**row, "sector_key": sector_key, "cue_notes": cue_notes}
        window = (ctx.news_since or ctx.session_open, ctx.check_at)
        row["candidates"] = attribution.market_candidates(context, ctx.market_moves) + attribution.item_candidates(
            ctx.con, ticker, window, ctx.session_date, settings["attribution"]["max_news"])
        row["candidate_ids"] = [candidate["id"] for candidate in row["candidates"]]


def _judged(ctx: CheckContext, call: dict, ticker: str, quote: SessionQuote, sigma, elapsed: float) -> dict:
    """A call with its entry price (open_to_close: the open of its entry session, today's intraday open when that
    is today; close_to_close: the stored as-of close) judged against the last price."""
    if call["entry_kind"] == "open" and call["entry_date"] == ctx.session_date.isoformat():
        entry = quote.open_price
    else:
        entry = ctx.entry_prices.get((ticker, call["entry_date"], call["entry_kind"]))
    sessions = max(call["sessions_held"] - 1, 0) + elapsed
    return judge_call({**call, "entry_price": rounded(entry, 4)}, quote.last_price, sigma, sessions, ctx.settings)


def _bar(settings: dict) -> timedelta:
    """The length of one bar."""
    return timedelta(minutes=settings["quotes"]["bar_minutes"])
