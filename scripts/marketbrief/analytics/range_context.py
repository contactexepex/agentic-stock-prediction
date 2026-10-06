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
from marketbrief.constants.range_publication import (CALIBRATION_ID, CUE_TIME_SQL, INDEX_CUE_SQL, LATEST_REGIME_SQL,
                                                     MSG_INDEX_CUE_IGNORED, MSG_NO_REGIME, NO_CALIBRATION_ID,
                                                     OPTIONS_SQL, PREDICTIONS_SQL)
from marketbrief.core.calendar import market_events, session_close_utc, session_open_utc, sessions_ahead
from marketbrief.core.clock import utc_now


@dataclass
class RangeContext:
    """The shared inputs of one run (cfg, ranges config, regime row, as-of date, made-at time and stored data)."""
    cfg: dict
    rc: dict
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
    """One horizon of a run: its target session, calibration quantiles and whether a major event falls in it."""
    h: int
    target: date
    q: dict
    cal_id: str
    major: bool


def target_date(cfg: dict, as_of, h: int):
    """The session `h` trading days after `as_of`."""
    return sessions_ahead(cfg, as_of + timedelta(days=1), h)[-1]


def first_target_close(cfg: dict, as_of):
    """The close (UTC) of the first target session."""
    return session_close_utc(cfg, target_date(cfg, as_of, 1))


def first_target_open(cfg: dict, as_of):
    """The open (UTC) of the first target session."""
    return session_open_utc(cfg, target_date(cfg, as_of, 1))


def cue_times(con, feats: pd.DataFrame) -> dict:
    """When each ticker's cue was quoted: the quote features.py used, i.e. the latest one collected
    on the snapshot's UTC day no later than its computed_at (ADR first)."""
    out = {}
    for t, f in feats.iterrows():
        at = pd.Timestamp(f["computed_at"]).to_pydatetime()
        row = con.execute(CUE_TIME_SQL, [f"{t}:ADR", t, at, at, f"{t}:ADR"]).fetchone()
        out[t] = pd.Timestamp(row[0]).to_pydatetime() if row and row[0] is not None else None
    return out


def load_index_cue(con, cfg: dict, rc: dict, bars: dict, reg: pd.Series,
                   first_open: datetime) -> tuple[float | None, str | None]:
    """(the index cue as an expected log move, a note when the quote was too late): none unless beta split is on."""
    symbol = (cfg.get("index_cue") or {}).get("symbol")
    if not (enabled(rc, INPUT_BETA_SPLIT, cfg["market"]) and symbol):
        return None, None
    as_of = pd.Timestamp(reg["as_of_date"]).date()
    at = pd.Timestamp(reg["computed_at"]).to_pydatetime()
    quote = con.execute(INDEX_CUE_SQL, [symbol, at, at]).fetchone()
    cue_beta = index_cue_beta(cfg, bars, rc, pd.Timestamp(as_of))
    if not (quote and quote[0] is not None and cue_beta is not None):
        return None, None
    if pd.Timestamp(quote[1]).to_pydatetime() > first_open:
        return None, MSG_INDEX_CUE_IGNORED.format(symbol=symbol, first=target_date(cfg, as_of, 1))
    return cue_beta * math.log1p(float(quote[0])), None


def load_options(con, cfg: dict, rc: dict, made: datetime, first_open: datetime) -> pd.DataFrame:
    """The newest option snapshot per ticker and expiry known before made_at and the first target open."""
    opts = pd.DataFrame()
    if cfg.get("options") and "implied_vol" in rc:   # applied if switched on, else a shadow value
        opts = con.execute(OPTIONS_SQL, [made.date() - timedelta(days=int(rc["implied_vol"]["max_age_days"])),
                                         min(made, first_open)]).df()
        if not opts.empty:
            opts["expiry"] = opts["expiry"].map(lambda d: pd.Timestamp(d).date())
            opts = opts.sort_values("day").drop_duplicates(["ticker", "expiry"], keep="last")
    return opts


def load_context(cfg: dict, rc: dict, con, now: str | None = None) -> RangeContext:
    """Read the stored snapshot, calibration, predictions, events and cues of one run."""
    reg = con.execute(LATEST_REGIME_SQL).df()
    if reg.empty:
        raise SystemExit(MSG_NO_REGIME)
    reg = reg.iloc[0]
    as_of = pd.Timestamp(reg["as_of_date"]).date()
    feats = con.execute("SELECT * FROM features_latest WHERE as_of_date = ?", [as_of]).df().set_index("ticker")
    cal = con.execute("SELECT * FROM calibration_latest").df().set_index("horizon_days")
    preds = con.execute(PREDICTIONS_SQL, [as_of]).df()
    existing = set(con.execute("SELECT id FROM ranges").df()["id"])
    bars = load_bars(con)
    company = con.execute("SELECT ticker, type, date FROM company_events WHERE date > ?", [as_of]).fetchall()
    rwiden = relation_flags.widen_by_ticker(cfg, rc, con)   # {} unless relation_widen.enabled
    now = now or utc_now()
    smart = smart_money.range_flags(con, as_of, rc, now)   # fresh activist 13D accepted by made_at; widen off by default
    made = datetime.fromisoformat(now)
    first_open, first_close = first_target_open(cfg, as_of), first_target_close(cfg, as_of)
    # SEC 2.02 filings that are not results releases are dropped using the 10-Q/10-K reports
    # accepted by made_at's local date (a replay with --now never uses a later one)
    events = load_events(con)
    known_by = pd.Timestamp(made).tz_convert(cfg["timezone"]).date()
    earn_ev = earnings_events(events, as_of=known_by)
    sigma = {t: range_math.ewma_sigma(bars[t]["close"], rc["ewma_lambda"]) for t in cfg["tickers"] if t in bars}
    moves = {t: past_moves(cfg, bars[t]["close"], sigma[t], earn_ev.get(t, []), rc["warmup_bars"])
             for t in cfg["tickers"] if t in bars} if enabled(rc, INPUT_EARNINGS_HISTORY, cfg["market"]) else {}
    index_cue, index_cue_note = load_index_cue(con, cfg, rc, bars, reg, first_open)
    return RangeContext(
        cfg=cfg, rc=rc, reg=reg, as_of=as_of, now=now, made=made, first=target_date(cfg, as_of, 1),
        first_open=first_open, first_close=first_close, feats=feats, cal=cal,
        pred={(r.ticker, int(r.horizon_days)): r for r in preds.itertuples()}, existing=existing, bars=bars,
        earnings={t: d for t, k, d in company if k == TYPE_EARNINGS}, rwiden=rwiden, smart=smart,
        cue_ts=cue_times(con, feats), earn_ev=earn_ev, divs=dividend_events(events), moves=moves,
        index_cue=index_cue, index_cue_note=index_cue_note, opts=load_options(con, cfg, rc, made, first_open))


def horizon_context(ctx: RangeContext, h: int) -> HorizonContext | None:
    """The horizon's target and calibration, or None when its outcome is already public (late or mid-session run)."""
    tgt = target_date(ctx.cfg, ctx.as_of, h)
    if ctx.made >= session_close_utc(ctx.cfg, tgt):
        return None  # late run: the target session already closed, its outcome is public
    if tgt == ctx.first and ctx.made >= ctx.first_open:
        return None  # mid-session run: the 1-day target session has opened, its outcome is partly public
    major = any(e["major"] for e in market_events(ctx.cfg, ctx.as_of + timedelta(days=1), tgt))
    if h in ctx.cal.index:
        c = ctx.cal.loc[h]
        q = {"q10": c.q10, "q25": c.q25, "q75": c.q75, "q90": c.q90}
        cal_id = CALIBRATION_ID.format(id=c.id, source=c.source, history=c.n_history, live=c.n_live)
    else:
        lo80, hi80 = range_math.normal_quantiles(0.8)
        lo50, hi50 = range_math.normal_quantiles(0.5)
        q, cal_id = {"q10": lo80, "q25": lo50, "q75": hi50, "q90": hi80}, NO_CALIBRATION_ID
    return HorizonContext(h=h, target=tgt, q=q, cal_id=cal_id, major=major)
