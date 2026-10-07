"""Everything the published ranges of one run share: stored snapshot, calibration, predictions, events and cues."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.analytics import range_math
from marketbrief.analytics import relation_flags
from marketbrief.analytics import smart_money
from marketbrief.analytics.event_history import dividend_events, earnings_events, load_events
from marketbrief.analytics.earnings_reaction import past_moves
from marketbrief.analytics.features import load_bars
from marketbrief.analytics.index_cue import index_cue_beta
from marketbrief.analytics.range_switches import enabled
from marketbrief.constants.range_inputs import INPUT_BETA_SPLIT, INPUT_EARNINGS_HISTORY, TYPE_EARNINGS
from marketbrief.constants.range_publication import (
    CALIBRATION_ID,
    CALIBRATION_SQL,
    CUE_TIME_SQL,
    INDEX_CUE_SQL,
    LATEST_REGIME_SQL,
    MSG_INDEX_CUE_IGNORED,
    MSG_NO_REGIME,
    NO_CALIBRATION_ID,
    OPTIONS_SQL,
    PREDICTIONS_SQL,
)
from marketbrief.core.calendar import market_events, session_close_utc, session_open_utc, sessions_ahead
from marketbrief.core.clock import utc_now
from marketbrief.core.horizons import window_sessions


@dataclass
class RangeContext:
    """The shared inputs of one run (cfg, ranges config, regime row, as-of date, made-at time and stored data)."""

    cfg: dict
    ranges_config: dict
    reg: pd.Series
    as_of: date
    now: str
    made: datetime
    first: date
    first_open: datetime
    first_close: datetime
    feats: pd.DataFrame
    cal: pd.DataFrame
    pred: dict
    existing: set
    bars: dict
    earnings: dict
    rwiden: dict
    smart: dict
    cue_ts: dict
    earn_ev: dict
    divs: dict
    moves: dict
    index_cue: float | None
    index_cue_note: str | None
    opts: pd.DataFrame


@dataclass
class HorizonContext:
    """One horizon N+k of a run: its target (exit) session, the sessions from the as-of close to it (k + 1),
    calibration quantiles and whether a major event falls in it."""

    horizon: int
    target: date
    quantiles: dict
    cal_id: str
    major: bool
    sessions: int = 0

    def __post_init__(self):
        self.sessions = self.sessions or window_sessions(self.horizon)


def target_date(cfg: dict, as_of, sessions: int):
    """The session `sessions` trading days after `as_of` (1 = D; the exit of N+k is window_sessions(k))."""
    return sessions_ahead(cfg, as_of + timedelta(days=1), sessions)[-1]


def first_target_close(cfg: dict, as_of):
    """The close (UTC) of D, the first session after the as-of close (every horizon's window covers it)."""
    return session_close_utc(cfg, target_date(cfg, as_of, 1))


def first_target_open(cfg: dict, as_of):
    """The open (UTC) of D, the first session after the as-of close."""
    return session_open_utc(cfg, target_date(cfg, as_of, 1))


def cue_times(con, feats: pd.DataFrame) -> dict:
    """When each ticker's cue was quoted: the quote features.py used, i.e. the latest one collected
    on the snapshot's UTC day no later than its computed_at (ADR first)."""
    out = {}
    for ticker, feature_row in feats.iterrows():
        computed_at = pd.Timestamp(feature_row["computed_at"]).to_pydatetime()
        row = con.execute(CUE_TIME_SQL, [f"{ticker}:ADR", ticker, computed_at, computed_at, f"{ticker}:ADR"]).fetchone()
        out[ticker] = pd.Timestamp(row[0]).to_pydatetime() if row and row[0] is not None else None
    return out


def load_index_cue(
    con, cfg: dict, ranges_config: dict, bars: dict, reg: pd.Series, first_open: datetime
) -> tuple[float | None, str | None]:
    """(the index cue as an expected log move, a note when the quote was too late): none unless beta split is on."""
    symbol = (cfg.get("index_cue") or {}).get("symbol")
    if not (enabled(ranges_config, INPUT_BETA_SPLIT, cfg["market"]) and symbol):
        return None, None
    as_of = pd.Timestamp(reg["as_of_date"]).date()
    computed_at = pd.Timestamp(reg["computed_at"]).to_pydatetime()
    quote = con.execute(INDEX_CUE_SQL, [symbol, computed_at, computed_at]).fetchone()
    cue_beta = index_cue_beta(cfg, bars, ranges_config, pd.Timestamp(as_of))
    if not (quote and quote[0] is not None and cue_beta is not None):
        return None, None
    if pd.Timestamp(quote[1]).to_pydatetime() > first_open:
        return None, MSG_INDEX_CUE_IGNORED.format(symbol=symbol, first=target_date(cfg, as_of, 1))
    return cue_beta * math.log1p(float(quote[0])), None


def load_options(con, cfg: dict, ranges_config: dict, made: datetime, first_open: datetime) -> pd.DataFrame:
    """The newest option snapshot per ticker and expiry known before made_at and the first target open."""
    option_snapshots = pd.DataFrame()
    if cfg.get("options") and "implied_vol" in ranges_config:  # applied if switched on, else a shadow value
        option_snapshots = con.execute(
            OPTIONS_SQL,
            [made.date() - timedelta(days=int(ranges_config["implied_vol"]["max_age_days"])), min(made, first_open)],
        ).df()
        if not option_snapshots.empty:
            option_snapshots["expiry"] = option_snapshots["expiry"].map(lambda expiry: pd.Timestamp(expiry).date())
            option_snapshots = option_snapshots.sort_values("day").drop_duplicates(["ticker", "expiry"], keep="last")
    return option_snapshots


def load_context(cfg: dict, ranges_config: dict, con, now: str | None = None) -> RangeContext:
    """Read the stored snapshot, calibration, predictions, events and cues of one run."""
    reg = con.execute(LATEST_REGIME_SQL).df()
    if reg.empty:
        raise SystemExit(MSG_NO_REGIME)
    reg = reg.iloc[0]
    as_of = pd.Timestamp(reg["as_of_date"]).date()
    feats = con.execute("SELECT * FROM features_latest WHERE as_of_date = ?", [as_of]).df().set_index("ticker")
    cal = con.execute(CALIBRATION_SQL).df().set_index("horizon_days")
    preds = con.execute(PREDICTIONS_SQL, [as_of]).df()
    existing = set(con.execute("SELECT id FROM ranges").df()["id"])
    bars = load_bars(con)
    company = con.execute("SELECT ticker, type, date FROM company_events WHERE date > ?", [as_of]).fetchall()
    rwiden = relation_flags.widen_by_ticker(cfg, ranges_config, con)  # {} unless relation_widen.enabled
    now = now or utc_now()
    # fresh activist 13D accepted by made_at; widen off by default
    smart = smart_money.range_flags(con, as_of, ranges_config, now)
    made = datetime.fromisoformat(now)
    first_open, first_close = first_target_open(cfg, as_of), first_target_close(cfg, as_of)
    # SEC 2.02 filings that are not results releases are dropped using the 10-Q/10-K reports
    # accepted by made_at (a replay with --now never uses a later one; issue #24: by time, not date)
    events = load_events(con)
    known_by = pd.Timestamp(made).tz_convert(cfg["timezone"]).date()
    earn_ev = earnings_events(events, as_of=known_by, made_at=made)
    sigma = {
        ticker: range_math.ewma_sigma(bars[ticker]["close"], ranges_config["ewma_lambda"])
        for ticker in cfg["tickers"]
        if ticker in bars
    }
    moves = (
        {
            ticker: past_moves(
                cfg,
                bars[ticker]["close"],
                sigma[ticker],
                earn_ev.get(ticker, []),
                ranges_config["warmup_bars"],
            )
            for ticker in cfg["tickers"]
            if ticker in bars
        }
        if enabled(ranges_config, INPUT_EARNINGS_HISTORY, cfg["market"])
        else {}
    )
    index_cue, index_cue_note = load_index_cue(con, cfg, ranges_config, bars, reg, first_open)
    return RangeContext(
        cfg=cfg,
        ranges_config=ranges_config,
        reg=reg,
        as_of=as_of,
        now=now,
        made=made,
        first=target_date(cfg, as_of, 1),
        first_open=first_open,
        first_close=first_close,
        feats=feats,
        cal=cal,
        pred={(prediction.ticker, int(prediction.horizon_days)): prediction for prediction in preds.itertuples()},
        existing=existing,
        bars=bars,
        earnings={ticker: earnings_day for ticker, event_type, earnings_day in company if event_type == TYPE_EARNINGS},
        rwiden=rwiden,
        smart=smart,
        cue_ts=cue_times(con, feats),
        earn_ev=earn_ev,
        divs=dividend_events(events),
        moves=moves,
        index_cue=index_cue,
        index_cue_note=index_cue_note,
        opts=load_options(con, cfg, ranges_config, made, first_open),
    )


def horizon_context(ctx: RangeContext, horizon: int) -> HorizonContext | None:
    """The horizon's target (the exit session of N+k) and calibration, or None when its outcome is already public
    (late run). A mid-session run (D has opened) still publishes every horizon, noted late (range_row): no N+k
    exits at D's close, the window of each only starts in it."""
    target_day = target_date(ctx.cfg, ctx.as_of, window_sessions(horizon))
    if ctx.made >= session_close_utc(ctx.cfg, target_day):
        return None  # late run: the target session already closed, its outcome is public
    major = any(event["major"] for event in market_events(ctx.cfg, ctx.as_of + timedelta(days=1), target_day))
    if horizon in ctx.cal.index:
        calibration = ctx.cal.loc[horizon]
        quantiles = {"q10": calibration.q10, "q25": calibration.q25, "q75": calibration.q75, "q90": calibration.q90}
        cal_id = CALIBRATION_ID.format(
            id=calibration.id, source=calibration.source, history=calibration.n_history, live=calibration.n_live
        )
    else:
        lo80, hi80 = range_math.normal_quantiles(0.8)
        lo50, hi50 = range_math.normal_quantiles(0.5)
        quantiles, cal_id = {"q10": lo80, "q25": lo50, "q75": hi50, "q90": hi80}, NO_CALIBRATION_ID
    return HorizonContext(horizon=horizon, target=target_day, quantiles=quantiles, cal_id=cal_id, major=major)
