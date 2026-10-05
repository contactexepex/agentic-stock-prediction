#!/usr/bin/env python3
"""Publish today's 50% and 80% price ranges per ticker and horizon for one market.

Run after features.py, calibrate.py and the forecaster. Inputs (all stored, never live APIs):
latest indicator snapshot and regime, latest calibration quantiles, upcoming events, and
today's predictions (AI direction/confidence and optional `range_widen`). Switchable inputs
(config/ranges.yaml per market and horizon, logic in range_inputs.py): past earnings-day moves,
ex-dividend shift, beta split of the overnight cue, and option-implied volatility (US; when
switched off its horizon sigma is still recorded as the shadow value `iv_sigma_h`).
Appends to data/<market>/ranges/; ids <as_of_date>-<ticker>-<h>d are written once.
Late-run guard: a range whose target session had already closed at made_at is not published;
other ranges note when the first target session had already closed, and an overnight cue (or
option snapshot) quoted after that close is ignored (it would carry that session's outcome)."""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta

import pandas as pd

import events as ev
import range_inputs as ri
import rangelib as rl
import relations
import smart_money as sm
from common import (append_jsonl, connect, day_file, load_ranges_config, market_arg, require_market,
                    utc_now)
from features import load_bars


def target_date(cfg: dict, as_of, h: int):
    return ev.sessions_ahead(cfg, as_of + timedelta(days=1), h)[-1]


def first_target_close(cfg: dict, as_of):
    return ev.session_close_utc(cfg, target_date(cfg, as_of, 1))


def cue_times(con, feats: pd.DataFrame) -> dict:
    """When each ticker's cue was quoted: the quote features.py used, i.e. the latest one collected
    on the snapshot's UTC day no later than its computed_at (ADR first)."""
    out = {}
    for t, f in feats.iterrows():
        at = pd.Timestamp(f["computed_at"]).to_pydatetime()
        row = con.execute("SELECT coalesce(ts, collected_at) FROM quotes WHERE symbol IN (?, ?) "
                          "AND CAST(collected_at AS DATE) = CAST(? AS DATE) AND collected_at <= ? "
                          "ORDER BY symbol = ? DESC, collected_at DESC LIMIT 1",
                          [f"{t}:ADR", t, at, at, f"{t}:ADR"]).fetchone()
        out[t] = pd.Timestamp(row[0]).to_pydatetime() if row and row[0] is not None else None
    return out


def build(cfg: dict, rc: dict, con, now: str | None = None) -> list[dict]:
    reg = con.execute("SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1").df()
    if reg.empty:
        raise SystemExit("no regime snapshot; run features.py first")
    reg = reg.iloc[0]
    as_of = pd.Timestamp(reg["as_of_date"]).date()
    feats = con.execute("SELECT * FROM features_latest WHERE as_of_date = ?", [as_of]).df().set_index("ticker")
    cal = con.execute("SELECT * FROM calibration_latest").df().set_index("horizon_days")
    preds = con.execute("SELECT ticker, horizon_days, direction, confidence, range_widen FROM predictions "
                        "WHERE as_of_date = ? QUALIFY row_number() OVER (PARTITION BY id ORDER BY made_at DESC) = 1",
                        [as_of]).df()
    pred = {(r.ticker, int(r.horizon_days)): r for r in preds.itertuples()}
    existing = set(con.execute("SELECT id FROM ranges").df()["id"])
    bars = load_bars(con)
    company = con.execute("SELECT ticker, type, date FROM company_events WHERE date > ?", [as_of]).fetchall()
    earnings = {t: d for t, k, d in company if k == "earnings"}
    rwiden = relations.widen_by_ticker(cfg, rc, con)   # {} unless relation_widen.enabled
    now, rows = now or utc_now(), []
    smart = sm.range_flags(con, as_of, rc, now)   # fresh activist 13D accepted by made_at; widen off by default
    made = datetime.fromisoformat(now)
    first = target_date(cfg, as_of, 1)
    first_close = first_target_close(cfg, as_of)
    cue_ts = cue_times(con, feats)
    # range inputs (range_inputs.py); switched per market and horizon in config/ranges.yaml
    mk = cfg["market"]
    evdf = ri.load_events(con)
    earn_ev, divs = ri.earnings_events(evdf), ri.dividend_events(evdf)
    sig = {t: rl.ewma_sigma(bars[t]["close"], rc["ewma_lambda"]) for t in cfg["tickers"] if t in bars}
    moves = {t: ri.past_moves(cfg, bars[t]["close"], sig[t], earn_ev.get(t, []), rc["warmup_bars"])
             for t in cfg["tickers"] if t in bars} if ri.enabled(rc, "earnings_history", mk) else {}
    index_cue, index_cue_note = None, None
    if ri.enabled(rc, "beta_split", mk) and (cfg.get("index_cue") or {}).get("symbol"):
        sym = cfg["index_cue"]["symbol"]
        at = pd.Timestamp(reg["computed_at"]).to_pydatetime()
        q = con.execute("SELECT change_pct, coalesce(ts, collected_at) FROM quotes WHERE symbol = ? "
                        "AND CAST(collected_at AS DATE) = CAST(? AS DATE) AND collected_at <= ? "
                        "ORDER BY collected_at DESC LIMIT 1", [sym, at, at]).fetchone()
        cue_beta = ri.index_cue_beta(cfg, bars, rc, pd.Timestamp(as_of))
        if q and q[0] is not None and cue_beta is not None:
            if pd.Timestamp(q[1]).to_pydatetime() > first_close:
                index_cue_note = f"index cue ignored: {sym} quoted after {first} close"
            else:
                index_cue = cue_beta * math.log1p(float(q[0]))
    opts = pd.DataFrame()
    if cfg.get("options") and "implied_vol" in rc:   # applied if switched on, else a shadow value
        opts = con.execute("SELECT * FROM options_latest WHERE day >= ? AND collected_at <= ?",
                           [made.date() - timedelta(days=int(rc["implied_vol"]["max_age_days"])),
                            min(made, first_close)]).df()
        if not opts.empty:
            opts["expiry"] = opts["expiry"].map(lambda d: pd.Timestamp(d).date())
            opts = opts.sort_values("day").drop_duplicates(["ticker", "expiry"], keep="last")

    for h in rc["horizons"]:
        tgt = target_date(cfg, as_of, h)
        if made >= ev.session_close_utc(cfg, tgt):
            continue  # late run: the target session already closed, its outcome is public
        mevents = ev.market_events(cfg, as_of + timedelta(days=1), tgt)
        major = [e for e in mevents if e["major"]]
        if h in cal.index:
            c = cal.loc[h]
            q = {"q10": c.q10, "q25": c.q25, "q75": c.q75, "q90": c.q90}
            cal_id = f"{c.id} ({c.source}, n={c.n_history}+{c.n_live})"
        else:
            lo80, hi80 = rl.normal_quantiles(0.8)
            lo50, hi50 = rl.normal_quantiles(0.5)
            q, cal_id = {"q10": lo80, "q25": lo50, "q75": hi50, "q90": hi80}, "none (normal)"
        for t in cfg["tickers"]:
            rid = f"{as_of}-{t}-{h}d"
            if rid in existing or t not in feats.index:
                continue
            f = feats.loc[t]
            if f["quality"] == "BLOCKED" or pd.isna(f["ewma_vol"]) or pd.isna(f["close"]):
                continue
            base, sd = float(f["close"]), float(f["ewma_vol"]) / math.sqrt(rl.TRADING_DAYS)
            use = {k: ri.enabled(rc, k, mk, h) for k in ri.INPUTS}
            tev = earn_ev.get(t, [])
            if use["earnings_history"]:   # timed reaction sessions from the event history
                in_h = ri.earnings_in_horizon(cfg, tev, as_of, tgt)
            else:
                e = earnings.get(t)
                in_h = bool(e and e <= tgt)
            topts = opts[opts["ticker"] == t] if not opts.empty else opts
            iv = ri.implied_sigma(cfg, topts, as_of, tgt, sd, tev, rc) if not topts.empty else None

            def width(apply_iv: bool):
                s_d, mult, enote, wn, inp = sd, None, "", [], []
                if apply_iv and iv is not None:
                    s_iv, m_iv, ivn = iv
                    if s_iv != sd or (m_iv is not None and in_h):
                        s_d, mult, wn, inp = s_iv, (m_iv if in_h else None), list(ivn), ["implied_vol"]
                        enote = ", options-implied" if mult is not None else ""
                if in_h and mult is None and use["earnings_history"]:
                    m, n, med = ri.earnings_stats(moves.get(t, []), rc, as_of)
                    if n >= rc["earnings_history"]["min_events"]:
                        mult, enote = m, f", {n} past moves, median {med:.1%}"
                        inp.append("earnings_history")
                s_h, hn = rl.horizon_sigma(s_d, h, in_h, rc, reg["regime"], bool(major), mult, enote)
                return s_h, wn + hn, inp

            sigma_h, notes, inputs = width(use["implied_vol"])
            formula_sigma = sigma_h
            iv_formula = width(True)[0] if iv is not None else None
            if made >= first_close:
                notes.append(f"late: {first} closed before made_at")
            if t in rwiden:
                sigma_h *= 1 + rwiden[t][0]
                notes.append(rwiden[t][1])
            sm_factor, sm_notes = smart.get(t, (1.0, []))
            sigma_h *= sm_factor
            notes += sm_notes
            # centre: overnight cue (beta split or direct) + AI drift, capped
            center = 0.0
            cue = f.get("cue_change_pct")
            own = math.log1p(float(cue)) if cue is not None and not pd.isna(cue) else None
            if own is not None and cue_ts.get(t) is not None and cue_ts[t] > first_close:
                notes.append(f"cue ignored: quoted after {first} close")
                own = None
            beta = ri.clip_beta(f.get("beta_1y"), rc)
            if use["beta_split"] and index_cue_note:
                notes.append(index_cue_note)
            if use["beta_split"] and index_cue is not None and beta is not None:
                bs = rc["beta_split"]
                center += rl.beta_split_center(beta, index_cue, own, bs["index_weight"], bs["own_weight"],
                                               rc["cue_weight"])
                notes.append(f"index {index_cue:+.2%} expected from {cfg['index_cue']['symbol']}, "
                             f"x beta {beta:.2f} x{bs['index_weight']}"
                             + (f", own cue {float(cue):+.2%} net x{bs['own_weight']}" if own is not None else ""))
                inputs.append("beta_split")
            elif own is not None:
                center += rc["cue_weight"] * own
                notes.append(f"cue {float(cue):+.2%} x{rc['cue_weight']}")
            p = pred.get((t, h))
            direction = confidence = None
            if p is not None and p.direction in ("up", "down") and not pd.isna(p.confidence):
                direction, confidence = p.direction, float(p.confidence)
                sign = 1 if direction == "up" else -1
                center += sign * (confidence - 0.5) * rc["ai_drift_scale"] * sigma_h
                widen = 0.0 if p.range_widen is None or pd.isna(p.range_widen) else float(p.range_widen)
                widen = min(max(widen, 0.0), rc["max_ai_widen"])
                if widen:
                    sigma_h *= 1 + widen
                    notes.append(f"AI widened +{widen:.0%}")
            cap = rc["max_center_shift_sigma"] * sigma_h
            center = max(-cap, min(cap, center))
            if use["ex_dividend"]:   # a known price drop, outside the drift cap
                amounts = ri.dividends_in_horizon(cfg, divs.get(t, []), as_of, tgt)
                if amounts:
                    center += rl.ex_dividend_shift(base, amounts)
                    notes.append(f"ex-dividend {sum(amounts):g} ({sum(amounts) / base:.2%})")
                    inputs.append("ex_dividend")
            band = lambda zq: round(base * math.exp(center + zq * sigma_h), 4)  # noqa: E731
            close = bars[t]["close"] if t in bars else None
            s20 = rl.realized_sigma(close[close.index <= pd.Timestamp(as_of)]) if close is not None else None
            n50 = tuple(round(x, 4) for x in rl.naive_range(base, s20, h, 0.5)) if s20 else (None, None)
            n80 = tuple(round(x, 4) for x in rl.naive_range(base, s20, h, 0.8)) if s20 else (None, None)
            rows.append({
                "id": rid, "made_at": now, "as_of_date": str(as_of), "session_date": str(reg["session_date"])[:10],
                "target_date": str(tgt), "ticker": t, "horizon_days": h, "base_close": base,
                "center": round(center, 6), "sigma_h": round(sigma_h, 6),
                "lo50": band(q["q25"]), "hi50": band(q["q75"]), "lo80": band(q["q10"]), "hi80": band(q["q90"]),
                "naive_lo50": n50[0], "naive_hi50": n50[1], "naive_lo80": n80[0], "naive_hi80": n80[1],
                "direction": direction, "confidence": confidence, "regime": reg["regime"],
                "calibration_id": cal_id, "notes": notes, "inputs": inputs,
                "iv_sigma_h": round(iv_formula * sigma_h / formula_sigma, 6) if iv_formula else None,
            })
    return rows


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--now", help="made_at as ISO 8601 UTC with offset instead of now (tests only)")
    args = ap.parse_args()
    cfg = require_market(args)
    now = args.now or utc_now()
    if datetime.fromisoformat(now).tzinfo is None:
        raise SystemExit("--now needs a UTC offset, e.g. 2026-10-05T02:40:00+00:00")
    rc, con = load_ranges_config(), connect(cfg["market"])
    rows = build(cfg, rc, con, now)
    if rows:
        append_jsonl(day_file(cfg["market"], "ranges", pd.Timestamp(rows[0]["as_of_date"]).date()), rows)
    as_of = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    late = datetime.fromisoformat(now) >= first_target_close(cfg, as_of)
    print(json.dumps({"step": "ranges", "market": cfg["market"], "written": len(rows), "late": late,
                      "tickers": sorted({r["ticker"] for r in rows})}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
