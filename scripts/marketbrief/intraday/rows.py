"""One ticker's row of a check: measures, flags and attribution candidates (the inputs come from check.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from marketbrief.constants.config_keys import META_SECTOR, META_SECTOR_ETF, META_YAHOO
from marketbrief.core.schema_intraday import INTRADAY_SCHEMAS
from marketbrief.intraday import attribution, inputs
from marketbrief.intraday.constants import (
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
    judge_call,
    residual,
    rounded,
    scaled,
)
from marketbrief.intraday.quotes import SessionQuote
from marketbrief.intraday.settings import row_id


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
    prev_closes: dict = field(default_factory=dict)
    entry_opens: dict = field(default_factory=dict)
    market_moves: dict = field(default_factory=dict)  # benchmark key, cue snapshot
    news_since: datetime | None = None                # start of the news window (attribution.news_window)

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
        "method_version": METHOD_VERSION, "computed_at": ctx.computed_at,
    }


def ticker_row(ctx: CheckContext, ticker: str, meta: dict) -> dict:
    """The full row of one watchlist ticker."""
    row = base_row(ctx, ticker, meta)
    quote: SessionQuote | None = ctx.quotes.get(ticker)
    if quote is None or ctx.stale.get(ticker):
        row["quality"] = ctx.stale.get(ticker) or QUALITY_NO_QUOTE
        if quote is not None:
            row.update(last_price=rounded(quote.last_price, 4), last_time=quote.last_time.isoformat())
        return row
    row["quality"] = QUALITY_OK
    fill_measures(ctx, row, ticker, meta, quote)
    return row


def fill_measures(ctx: CheckContext, row: dict, ticker: str, meta: dict, quote: SessionQuote) -> None:
    """Measures, calls, flags and candidates of a ticker with a fresh quote."""
    settings, notes = ctx.settings, row["notes"]
    bands = ctx.ranges.get(ticker, {})
    range_1d, range_5d = bands.get(1), bands.get(5)
    sigma, sigma_note = inputs.daily_sigma(bands, ctx.features.get(ticker))
    if sigma_note:
        notes.append(sigma_note)
    bar_end = quote.last_time + _bar(settings)
    elapsed = elapsed_fraction(bar_end, ctx.session_open, ctx.session_close,
                               settings["measures"]["min_elapsed_fraction"])
    ret = quote.last_price / quote.open_price - 1
    prev = ctx.prev_closes.get(ticker)
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
    for horizon, band in ((1, range_1d), (5, range_5d)):
        if band:
            row[f"range_id_{horizon}d"] = band["id"]
            row[f"band_{horizon}d"] = band_position(quote.last_price, band)
            for key in ("lo80", "hi80") if horizon == 5 else ("lo80", "lo50", "hi50", "hi80"):
                row[f"{key}_{horizon}d"] = rounded(band[key], 4)
        else:
            notes.append(f"no_range_{horizon}d")
    row["calls"] = [_judged(ctx, call, ticker, quote, sigma, elapsed) for call in ctx.calls.get(ticker, [])]
    row["flags"] = flags_for(row, row["calls"], settings)
    row["flagged"] = any(flag in settings["flag_on"] for flag in row["flags"])
    if row["flagged"]:
        cue_notes = [note for note in (range_1d or {}).get("notes") or [] if "cue" in str(note)]
        context = {**row, "sector_key": sector_key, "cue_notes": cue_notes}
        window = (ctx.news_since or ctx.session_open, ctx.check_at)
        row["candidates"] = attribution.market_candidates(context, ctx.market_moves) + attribution.item_candidates(
            ctx.con, ticker, window, ctx.session_date, settings["attribution"]["max_news"])
        row["candidate_ids"] = [candidate["id"] for candidate in row["candidates"]]


def _judged(ctx: CheckContext, call: dict, ticker: str, quote: SessionQuote, sigma, elapsed: float) -> dict:
    """A call with its entry open (today's open when it entered today) judged against the last price."""
    entry_open = quote.open_price if call["entry_date"] == ctx.session_date.isoformat() else (
        ctx.entry_opens.get((ticker, call["entry_date"])))
    sessions = max(call["sessions_held"] - 1, 0) + elapsed
    return judge_call({**call, "entry_open": rounded(entry_open, 4)}, quote.last_price, sigma, sessions, ctx.settings)


def _bar(settings: dict) -> timedelta:
    """The length of one bar."""
    return timedelta(minutes=settings["quotes"]["bar_minutes"])
