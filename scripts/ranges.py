#!/usr/bin/env python3
"""Publish today's 50% and 80% price ranges per ticker and horizon for one market.

Run after features.py, calibrate.py and the forecaster. Inputs (all stored, never live APIs):
latest indicator snapshot and regime, latest calibration quantiles, upcoming events, and
today's predictions (AI direction/confidence and optional `range_widen`). Switchable inputs
(config/ranges.yaml, logic in range_inputs.py): past earnings-day moves, ex-dividend shift,
beta split of the overnight cue, and option-implied volatility (US).
Appends to data/<market>/ranges/; ids <as_of_date>-<ticker>-<h>d are written once."""
from __future__ import annotations

import json
import math
import sys
from datetime import timedelta

import pandas as pd

import events as ev
import range_inputs as ri
import rangelib as rl
from common import (append_jsonl, connect, day_file, load_ranges_config, market_arg, require_market,
                    utc_now, utc_today)
from features import load_bars


def target_date(cfg: dict, as_of, h: int):
    return ev.sessions_ahead(cfg, as_of + timedelta(days=1), h)[-1]


def build(cfg: dict, rc: dict, con) -> list[dict]:
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
    evdf = ri.load_events(con)
    earn_ev, divs = ri.earnings_events(evdf), ri.dividend_events(evdf)
    mk = cfg["market"]
    use = {k: ri.enabled(rc, k, mk) for k in ("earnings_history", "ex_dividend", "beta_split", "implied_vol")}
    sig = {t: rl.ewma_sigma(bars[t]["close"], rc["ewma_lambda"]) for t in cfg["tickers"] if t in bars}
    moves = {t: ri.past_moves(cfg, bars[t]["close"], sig[t], earn_ev.get(t, []), rc["warmup_bars"])
             for t in cfg["tickers"] if t in bars} if use["earnings_history"] else {}
    index_cue = cue_beta = None
    if use["beta_split"] and (cfg.get("index_cue") or {}).get("symbol"):
        q = con.execute("SELECT change_pct FROM quotes_latest WHERE symbol = ? AND day = CAST(? AS DATE)",
                        [cfg["index_cue"]["symbol"], str(reg["computed_at"])[:10]]).fetchone()
        cue_beta = ri.index_cue_beta(cfg, bars, rc, pd.Timestamp(as_of))
        if q and q[0] is not None and cue_beta is not None:
            index_cue = cue_beta * math.log1p(float(q[0]))
    opts = pd.DataFrame()
    if use["implied_vol"]:
        opts = con.execute("SELECT * FROM options_latest WHERE day >= ?",
                           [utc_today() - timedelta(days=int(rc["implied_vol"]["max_age_days"]))]).df()
        if not opts.empty:
            opts["expiry"] = opts["expiry"].map(lambda d: pd.Timestamp(d).date())
            opts = opts.sort_values("day").drop_duplicates(["ticker", "expiry"], keep="last")
    now, rows = utc_now(), []

    for h in rc["horizons"]:
        tgt = target_date(cfg, as_of, h)
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
            notes, inputs = [], []
            tev = earn_ev.get(t, [])
            in_h = ri.earnings_in_horizon(cfg, tev, as_of, tgt)
            mult, enote = None, ""
            if use["implied_vol"] and not opts.empty:
                sd2, m_iv, ivn = ri.implied_sigma(cfg, opts[opts["ticker"] == t], as_of, tgt, sd, tev, rc)
                if sd2 != sd or (m_iv is not None and in_h):
                    sd, mult, notes, inputs = sd2, m_iv if in_h else None, notes + ivn, inputs + ["implied_vol"]
                    enote = ", options-implied" if mult is not None else ""
            if in_h and mult is None and use["earnings_history"]:
                m, n, med = ri.earnings_stats(moves.get(t, []), rc, as_of)
                if n >= rc["earnings_history"]["min_events"]:
                    mult, enote = m, f", {n} past moves, median {med:.1%}"
                    inputs.append("earnings_history")
            sigma_h, wnotes = rl.horizon_sigma(sd, h, in_h, rc, reg["regime"], bool(major), mult, enote)
            notes += wnotes
            # centre: overnight cue (beta split or direct) + AI drift, capped
            center = 0.0
            cue = f.get("cue_change_pct")
            own = math.log1p(float(cue)) if cue is not None and not pd.isna(cue) else None
            beta = ri.clip_beta(f.get("beta_1y"), rc)
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
            })
    return rows


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    rc, con = load_ranges_config(), connect(cfg["market"])
    rows = build(cfg, rc, con)
    if rows:
        append_jsonl(day_file(cfg["market"], "ranges", pd.Timestamp(rows[0]["as_of_date"]).date()), rows)
    print(json.dumps({"step": "ranges", "market": cfg["market"], "written": len(rows),
                      "tickers": sorted({r["ticker"] for r in rows})}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
