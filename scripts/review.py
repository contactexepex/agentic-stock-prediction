#!/usr/bin/env python3
"""Weekly review for one market (docs/DESIGN.md sections 6, 7 and 10 phase 4): what improved
coverage, what to drop.

From stored range outcomes, scored calls and calibration, for the review week, a rolling
window and since start (all by target date, never past the week's end):
- 50%/80% coverage vs target, interval score and width vs the naive baseline, by horizon,
  regime, sector and widening note;
- direction hit rate vs the always-up baseline, overall and by confidence band;
- ablation of each range input: (a) replay of the stored live scored ranges with one input
  changed (cue, AI drift, AI widening, earnings/event/regime widening, centre cap), and
  (b) walk-forward on stored prices (backtest.py) for the width parameters and the regime and
  event widening rebuilt from stored bars.
Thresholds and variants live in config/review.yaml. Small samples are flagged and get no
proposal. Proposed config/ranges.yaml changes are written to the report, never applied.
Appends a record to data/<market>/reviews/ and writes reports/<market>/review-YYYY-Www.md."""
from __future__ import annotations

import bisect
import json
import math
import re
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yaml

import backtest as bt
import events as ev
import indicators as ind
import rangelib as rl
import regime as rg
from common import (CONFIG, ROOT, append_jsonl, benchmark_key, connect, day_file, load_ranges_config,
                    market_arg, require_market, utc_now, utc_today, vol_index_key)
from features import load_bars

DEFAULTS = {
    "rolling_days": 30, "min_n": 30, "min_n_recommend": 200, "min_n_calls": 50,
    "min_improvement": 0.02, "coverage_tolerance": 0.02, "min_coverage_gain": 0.04,
    "calibration_tolerance": 0.05, "confidence_bands": [0.5, 0.6, 0.7, 0.8, 0.9],
    "history_eval_sessions": 120, "live_variants": [], "history_variants": [],
}
TARGETS = {"50": 0.5, "80": 0.8}
BASELINE = "current config"

# Notes written by ranges.py -> (tag, pattern). Unknown notes are tagged by their first word.
NOTE_PATTERNS = {
    "earnings": re.compile(r"^earnings in horizon \(x([\d.]+) day\)"),
    "regime": re.compile(r"^regime (\w+) x([\d.]+)"),
    "event": re.compile(r"^major event x([\d.]+)"),
    "ai_widen": re.compile(r"^AI widened \+([\d.]+)%"),
    "cue": re.compile(r"^cue ([+-]?[\d.]+)% x([\d.]+)"),
}


def load_review_config() -> dict:
    path = CONFIG / "review.yaml"
    return {**DEFAULTS, **((yaml.safe_load(path.read_text()) or {}) if path.exists() else {})}


# ---------- weeks ----------

def week_bounds(week: str) -> tuple[date, date]:
    m = re.fullmatch(r"(\d{4})-W(\d{2})", week)
    if not m:
        raise SystemExit(f"--week must look like 2026-W40, got {week!r}")
    start = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return start, start + timedelta(days=6)


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def previous_week(d: date) -> str:
    return iso_week(d - timedelta(days=7))


# ---------- helpers ----------

def _num(s: pd.Series) -> pd.Series:
    return pd.Series([np.nan if v is None or (isinstance(v, float) and math.isnan(v)) else float(v) for v in s],
                     dtype=float, index=s.index)


def _mean(s: pd.Series, digits: int = 4):
    s = _num(s).dropna()
    return round(float(s.mean()), digits) if len(s) else None


def _notes(v) -> list[str]:
    return [] if v is None or (isinstance(v, float) and math.isnan(v)) else [str(x) for x in v]


def note_tags(notes) -> list[str]:
    tags = []
    for n in _notes(notes):
        tag = next((k for k, p in NOTE_PATTERNS.items() if p.match(n)), None)
        if tag is None:
            tag = re.sub(r"[^a-z0-9_-]", "", n.split()[0].lower()) if n.split() else "other"
        if tag and tag not in tags:
            tags.append(tag)
    return tags or ["none"]


def clean(o):
    """Plain JSON types (numpy scalars -> Python, NaN -> null, dates -> ISO strings)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, np.ndarray)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer, int)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, (date, pd.Timestamp)):
        return str(o)[:10]
    return o


def merge(rc: dict, overrides: dict) -> dict:
    return {**rc, **(overrides or {})}


# ---------- live ranges ----------

def load_ranges(con, cfg: dict, week_end: date) -> pd.DataFrame:
    df = con.execute("SELECT * FROM range_record WHERE target_date <= ? ORDER BY target_date, id", [week_end]).df()
    if df.empty:
        return df
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    base, y = df["base_close"].astype(float), df["actual_close"].astype(float)

    def iscore(lo, hi, band):
        return [100 * rl.interval_score(a, b, v, band) / bc if not (pd.isna(a) or pd.isna(b)) else np.nan
                for a, b, v, bc in zip(_num(lo), _num(hi), y, base)]
    df["is50_pct"] = iscore(df["lo50"], df["hi50"], 0.5)
    df["naive_is50_pct"] = iscore(df["naive_lo50"], df["naive_hi50"], 0.5)
    df["width50_pct"] = 100 * (df["hi50"] - df["lo50"]) / base
    df["tags"] = [note_tags(n) + (["ai_call"] if d in ("up", "down") else []) for n, d in zip(df["notes"], df["direction"])]
    df["sector"] = [cfg["tickers"].get(t, {}).get("sector") or "other" for t in df["ticker"]]
    return df


def range_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    return {"n": int(len(df)),
            "cover50": _mean(df["hit50"]), "cover80": _mean(df["hit80"]),
            "naive_cover50": _mean(df["naive_hit50"]), "naive_cover80": _mean(df["naive_hit80"]),
            "width50_pct": _mean(df["width50_pct"], 3), "width80_pct": _mean(df["width80_pct"], 3),
            "naive_width80_pct": _mean(df["naive_width80_pct"], 3),
            "score50_pct": _mean(df["is50_pct"], 3), "naive_score50_pct": _mean(df["naive_is50_pct"], 3),
            "score80_pct": _mean(df["is80_pct"], 3), "naive_score80_pct": _mean(df["naive_is80_pct"], 3)}


def by_horizon(df: pd.DataFrame, fn) -> dict:
    out = {"all": fn(df)}
    for h, g in (df.groupby("horizon_days") if not df.empty else []):
        out[f"{int(h)}d"] = fn(g)
    return out


def breakdown(df: pd.DataFrame, col: str) -> dict:
    if df.empty:
        return {}
    d = df.explode(col) if col == "tags" else df
    return {f"{k} · {int(h)}d": range_summary(g) for (k, h), g in d.groupby([col, "horizon_days"])}


# ---------- direction calls ----------

def load_calls(con, week_end: date) -> pd.DataFrame:
    df = con.execute("SELECT * FROM track_record WHERE target_date <= ? ORDER BY target_date, id", [week_end]).df()
    if not df.empty:
        df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df


def call_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    hit, up = _mean(df["hit"]), _mean(df["actual_return"] > 0)
    return {"n": int(len(df)), "hit_rate": hit, "always_up": up,
            "edge": round(hit - up, 4) if hit is not None and up is not None else None,
            "mean_confidence": _mean(df["confidence"])}


def band_label(lo: float, hi: float) -> str:
    return f"{lo:.0%}-{hi:.0%}"


def confidence_bands(df: pd.DataFrame, edges: list[float]) -> dict:
    out = {}
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        last = i == len(edges) - 2
        g = df[(df["confidence"] >= lo) & ((df["confidence"] <= hi) if last else (df["confidence"] < hi))] \
            if not df.empty else df
        s = call_summary(g)
        if s["n"]:
            s["gap"] = round(s["hit_rate"] - s["mean_confidence"], 4)
        out[band_label(lo, hi)] = s
    return out


# ---------- ablation (a): replay of stored live ranges ----------

def decompose(r, rc: dict) -> dict | None:
    """Split a published range into its inputs (from its notes and stored numbers). Parts the
    replay cannot attribute (new inputs, changed settings) are kept fixed in `residual`/`sd`."""
    h, base, s, c = int(r["horizon_days"]), float(r["base_close"]), r["sigma_h"], r["center"]
    if s is None or pd.isna(s) or s <= 0 or base <= 0 or pd.isna(c):
        return None
    s, c = float(s), float(c)
    q = {k: (math.log(float(r[col]) / base) - c) / s
         for k, col in (("q10", "lo80"), ("q25", "lo50"), ("q75", "hi50"), ("q90", "hi80"))}
    m = rf = mef = None
    widen, cue, cue_w = 0.0, 0.0, 0.0
    for n in _notes(r["notes"]):
        if (x := NOTE_PATTERNS["earnings"].match(n)):
            m = float(x.group(1))
        elif (x := NOTE_PATTERNS["regime"].match(n)):
            rf = float(x.group(2))
        elif (x := NOTE_PATTERNS["event"].match(n)):
            mef = float(x.group(1))
        elif (x := NOTE_PATTERNS["ai_widen"].match(n)):
            widen = float(x.group(1)) / 100
        elif (x := NOTE_PATTERNS["cue"].match(n)):
            cue, cue_w = math.log1p(float(x.group(1)) / 100), float(x.group(2))
    s_pre = s / (1 + widen)
    sd = s_pre / ((rf or 1.0) * (mef or 1.0)) / math.sqrt(h + (m * m - 1 if m else 0.0))
    conf = r["confidence"]
    ai = ({"up": 1, "down": -1}.get(r["direction"], 0) * (float(conf) - 0.5)
          if conf is not None and not pd.isna(conf) else 0.0)
    est = cue_w * cue + rc["ai_drift_scale"] * ai * s_pre
    capped = abs(abs(c) - rc["max_center_shift_sigma"] * s) < 2e-6 and abs(est) > abs(c)
    return {"h": h, "base": base, "y": float(r["actual_close"]), "q": q, "sd": sd, "earnings": m is not None,
            "regime": r["regime"], "event": mef is not None, "widen": widen, "cue": cue, "ai": ai,
            "residual": 0.0 if capped else c - est}


def replay(comp: dict, p: dict) -> dict:
    sd, h = comp["sd"], comp["h"]
    var = sd * sd * h + ((p["earnings_vol_multiple"] ** 2 - 1) * sd * sd if comp["earnings"] else 0.0)
    s = math.sqrt(var) * p["regime_factor"].get(comp["regime"], 1.0)
    s *= p["major_event_factor"] if comp["event"] else 1.0
    center = comp["residual"] + p["cue_weight"] * comp["cue"] + p["ai_drift_scale"] * comp["ai"] * s
    s *= 1 + min(max(comp["widen"], 0.0), p["max_ai_widen"])
    cap = p["max_center_shift_sigma"] * s
    center = max(-cap, min(cap, center))
    base, y, q = comp["base"], comp["y"], comp["q"]
    b = {k: base * math.exp(center + v * s) for k, v in q.items()}
    return {"horizon_days": h, "lo80": b["q10"], "hi80": b["q90"],
            "hit50": b["q25"] <= y <= b["q75"], "hit80": b["q10"] <= y <= b["q90"],
            "is50": 100 * rl.interval_score(b["q25"], b["q75"], y, 0.5) / base,
            "is80": 100 * rl.interval_score(b["q10"], b["q90"], y, 0.8) / base,
            "width80": 100 * (b["q90"] - b["q10"]) / base}


def replay_summary(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    m = res.mean(numeric_only=True)
    return {"n": int(len(res)), "cover50": round(float(m["hit50"]), 4), "cover80": round(float(m["hit80"]), 4),
            "width80_pct": round(float(m["width80"]), 3), "score50_pct": round(float(m["is50"]), 3),
            "score80_pct": round(float(m["is80"]), 3)}


def per_horizon(res: pd.DataFrame, horizons) -> dict:
    return {f"{h}d": replay_summary(res[res["horizon_days"] == h]) for h in horizons if not res.empty}


def live_ablation(df: pd.DataFrame, rc: dict, rv: dict) -> dict:
    comps = [c for c in (decompose(r, rc) for r in df.to_dict("records")) if c is not None] if not df.empty else []
    if not comps:
        return {"n": 0, "reproduced": 0, "variants": []}
    base_rows = [replay(c, rc) for c in comps]
    pub = df.to_dict("records")
    reproduced = sum(abs(b["lo80"] / float(p["lo80"]) - 1) < 1e-4 and abs(b["hi80"] / float(p["hi80"]) - 1) < 1e-4
                     for b, p in zip(base_rows, pub))
    variants = []
    for v in [{"name": BASELINE, "set": {}}, *rv["live_variants"]]:
        p = merge(rc, v.get("set"))
        res = pd.DataFrame(base_rows if not v.get("set") else [replay(c, p) for c in comps])
        variants.append({"name": v["name"], "set": v.get("set") or {}, "n": len(res),
                         "by_h": per_horizon(res, rc["horizons"])})
    return {"n": len(comps), "reproduced": int(reproduced), "variants": variants}


# ---------- ablation (b): walk-forward on stored prices ----------

def history_context(cfg: dict, bars: dict, dates: list) -> tuple[list[str], list[date]]:
    """Regime per bar date rebuilt from stored bars (as features.py does live, with closes instead
    of pre-open quotes) and the sorted dates of major market events."""
    bench = bars[benchmark_key(cfg)]["close"]
    vk = vol_index_key(cfg)
    vol = bars[vk]["close"].reindex(bench.index) if vk in bars else pd.Series(np.nan, index=bench.index)
    first, last = dates[0].date(), dates[-1].date()
    events = ev.market_events(cfg, first, last + timedelta(days=30))
    majors = sorted({e["date"] for e in events if e["major"]})
    regimes = []
    for i, d in enumerate(dates):
        tail = bench.iloc[max(0, i - 30): i + 1]
        lvl = None if pd.isna(vol.iloc[i]) else float(vol.iloc[i])
        prev = None if i == 0 or pd.isna(vol.iloc[i - 1]) else float(vol.iloc[i - 1])
        session = dates[i + 1].date() if i + 1 < len(dates) else ev.next_session(cfg, d.date(), include=False)
        near = ev.major_events_near(events, session)
        regimes.append(rg.classify(cfg["regime"], lvl, ind.ret(tail, 5), ind.realized_vol(tail), bool(near),
                                   lvl / prev - 1 if lvl and prev else None)[0])
    return regimes, majors


def hist_summary(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    m = res.mean(numeric_only=True)
    return {"n": int(len(res)), "cover50": round(float(m["hit50"]), 4), "cover80": round(float(m["hit80"]), 4),
            "width80_pct": round(float(m["width80"]), 3), "score50_pct": round(float(m["is50"]), 3),
            "score80_pct": round(float(m["is80"]), 3), "naive_cover80": round(float(m["naive_hit80"]), 4),
            "naive_score80_pct": round(float(m["naive_is80"]), 3)}


def history_ablation(cfg: dict, rc: dict, rv: dict, bars: dict, week_end: date) -> dict:
    bkey = benchmark_key(cfg)
    bars = {t: df[df.index <= pd.Timestamp(week_end)] for t, df in bars.items()}
    if bkey not in bars or len(bars[bkey]) < rc["warmup_bars"] + 30:
        return {"n": 0, "error": "not enough benchmark bars", "variants": []}
    dates = list(bars[bkey].index)
    rank = {d: i for i, d in enumerate(dates)}
    regimes, majors = history_context(cfg, bars, dates)
    day = [d.date() for d in dates]

    def major_in(i: int, h: int) -> bool:
        if i + h >= len(day):
            return False
        k = bisect.bisect_right(majors, day[i])
        return k < len(majors) and majors[k] <= day[i + h]

    cache, variants = {}, []
    for v in [{"name": BASELINE, "set": {}}, *rv["history_variants"]]:
        p = merge(rc, v.get("set"))
        by_h, n = {}, 0
        for h in p["horizons"]:
            key = (p["ewma_lambda"], p["warmup_bars"], h)
            if key not in cache:
                cache[key] = bt.observations(bars, cfg["tickers"], h, p, rank)
            obs = cache[key]
            if obs.empty:
                continue
            scale = {i: p["regime_factor"].get(regimes[i], 1.0) * (p["major_event_factor"] if major_in(i, h) else 1.0)
                     for i in range(len(dates))}
            s = hist_summary(bt.evaluate(obs, h, p, rv["history_eval_sessions"], scale))
            by_h[f"{h}d"] = s
            n += s["n"]
        variants.append({"name": v["name"], "set": v.get("set") or {}, "n": n, "by_h": by_h})
    share = {k: round(regimes[-rv["history_eval_sessions"]:].count(k) / min(len(regimes), rv["history_eval_sessions"]), 3)
             for k in rg.ORDER}
    return {"n": variants[0]["n"] if variants else 0, "sessions": rv["history_eval_sessions"],
            "regime_share": share, "variants": variants}


# ---------- verdicts and proposals ----------

def compare(base: dict, var: dict) -> dict | None:
    """rel_score: mean relative change of the 80% interval score (negative = better).
    coverage_shortfall: largest extra drop BELOW target of 50%/80% coverage (over-coverage is
    left to the interval score and the daily self-calibration). coverage_gain: mean move of
    80% coverage towards its target."""
    hs = [h for h, b in base.items() if b.get("n") and var.get(h, {}).get("n") and b.get("score80_pct")]
    if not hs:
        return None
    rel = float(np.mean([var[h]["score80_pct"] / base[h]["score80_pct"] - 1 for h in hs]))
    short = max(max(0.0, t - var[h][f"cover{b}"]) - max(0.0, t - base[h][f"cover{b}"])
                for h in hs for b, t in TARGETS.items())
    gain = float(np.mean([abs(base[h]["cover80"] - 0.8) - abs(var[h]["cover80"] - 0.8) for h in hs]))
    return {"rel_score": round(rel, 4), "coverage_shortfall": round(float(short), 4), "coverage_gain": round(gain, 4)}


def verdict(cmp: dict | None, n: int, rv: dict) -> str:
    if cmp is None:
        return "no data"
    if n < rv["min_n_recommend"]:
        return "low n"
    if cmp["rel_score"] <= -rv["min_improvement"] and cmp["coverage_shortfall"] <= rv["coverage_tolerance"]:
        return "improves score"
    if cmp["coverage_gain"] >= rv["min_coverage_gain"] and cmp["rel_score"] <= 0:
        return "improves coverage"
    if cmp["rel_score"] >= rv["min_improvement"]:
        return "worse score"
    if cmp["coverage_shortfall"] > rv["coverage_tolerance"]:
        return "under-covers"
    return "no material change"


def judge(ablation: dict, rv: dict) -> None:
    """Annotate each variant with its comparison to the current config and a verdict."""
    vs = ablation.get("variants") or []
    base = next((v for v in vs if v["name"] == BASELINE), None)
    for v in vs:
        if v is base:
            v["verdict"] = "baseline" if v["n"] else "no data"
            continue
        v["vs_current"] = compare(base["by_h"], v["by_h"]) if base else None
        v["verdict"] = verdict(v["vs_current"], v["n"], rv)


def proposals(rc: dict, live: dict, hist: dict) -> list[dict]:
    """Best qualifying variant per parameter set; live evidence wins over price history, and
    price history is not proposed against live evidence (n >= min) that the change is worse."""
    best: dict[tuple, dict] = {}
    live_worse = {tuple(sorted(v["set"])) for v in live.get("variants") or []
                  if v.get("verdict") in ("worse score", "under-covers")}
    for source, ab in (("history walk-forward", hist), ("live replay", live)):
        for v in ab.get("variants") or []:
            if v.get("verdict") not in ("improves score", "improves coverage"):
                continue
            key = tuple(sorted(v["set"]))
            if source != "live replay" and key in live_worse:
                continue
            cur = best.get(key)
            if cur is None or source == "live replay" and cur["source"] != "live replay" or \
                    cur["source"] == source and v["vs_current"]["rel_score"] < cur["rel_score"]:
                base = next(x for x in ab["variants"] if x["name"] == BASELINE)
                best[key] = {"variant": v["name"], "source": source, "n": v["n"], "verdict": v["verdict"],
                             "changes": [{"param": k, "current": rc.get(k), "proposed": val} for k, val in v["set"].items()],
                             "drop": v["name"].lower().startswith("drop"),
                             "rel_score": v["vs_current"]["rel_score"],
                             "cover80_now": {h: x.get("cover80") for h, x in base["by_h"].items()},
                             "cover80_then": {h: x.get("cover80") for h, x in v["by_h"].items()}}
    return sorted(best.values(), key=lambda p: p["rel_score"])


def confidence_advice(bands: dict, calls: dict, rv: dict) -> list[str]:
    out = []
    for band, s in bands.items():
        if s.get("n", 0) >= rv["min_n_calls"] and s["gap"] < -rv["calibration_tolerance"]:
            out.append(f"Calls at {band} confidence hit {s['hit_rate']:.0%} (mean stated {s['mean_confidence']:.0%}, "
                       f"n={s['n']}): use lower confidence or abstain in this band.")
    a = calls.get("all", {})
    if a.get("n", 0) >= rv["min_n_calls"] and a["edge"] is not None and a["edge"] <= 0:
        out.append(f"Calls hit {a['hit_rate']:.0%} vs always-up {a['always_up']:.0%} (n={a['n']}): no edge over the "
                   "baseline; abstain more.")
    return out


# ---------- report ----------

def fpct(v, digits: int = 0) -> str:
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{digits}%}"


def fnum(v, digits: int = 3) -> str:
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{digits}f}"


def fval(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {x}" for k, x in v.items()) + "}"
    return str(v)


def table(header: list[str], rows: list[list]) -> str:
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def flag(n: int, rv: dict) -> str:
    return "low n" if n < rv["min_n"] else ""


def range_row(label: list, s: dict, rv: dict) -> list:
    return [*label, s["n"], fpct(s.get("cover50")), fpct(s.get("cover80")), fpct(s.get("naive_cover50")),
            fpct(s.get("naive_cover80")), fnum(s.get("width80_pct"), 2), fnum(s.get("naive_width80_pct"), 2),
            fnum(s.get("score80_pct")), fnum(s.get("naive_score80_pct")), flag(s["n"], rv)]


def ablation_rows(ab: dict) -> list[list]:
    rows = []
    for v in ab.get("variants") or []:
        hs = list(v["by_h"])
        join = lambda key, f: " / ".join(f(v["by_h"][h].get(key)) for h in hs) or "–"  # noqa: E731
        rel = (v.get("vs_current") or {}).get("rel_score")
        rows.append([v["name"], v["n"], join("cover50", fpct), join("cover80", fpct),
                     join("width80_pct", lambda x: fnum(x, 2)), join("score80_pct", fnum),
                     "–" if rel is None else f"{rel:+.1%}", v.get("verdict", "")])
    return rows


def markdown(cfg: dict, rv: dict, rec: dict, d: dict) -> str:
    hz = " / ".join(f"{h}d" for h in load_ranges_config()["horizons"])
    win_names = {"week": f"week {rec['week']}", "rolling": f"last {rv['rolling_days']} days", "all": "since start"}
    lines = [f"# Weekly review: {cfg['name']}, {rec['week']} ({rec['week_start']} to {rec['week_end']})", "",
             "_Research log, not investment advice. Generated by `scripts/review.py`. Proposed changes are never "
             "applied automatically: a human decides and edits `config/ranges.yaml` by hand._", "",
             f"Scored ranges: week **{rec['n_ranges_week']}** · last {rv['rolling_days']} days **{rec['n_ranges_30d']}** · "
             f"since start **{rec['n_ranges_all']}**. Scored calls: week **{rec['n_calls_week']}** · since start "
             f"**{rec['n_calls_all']}**. Windows count ranges by target date, up to {rec['week_end']}.", ""]
    if rec["low_sample"]:
        lines += [f"> **Low sample:** fewer than {rv['min_n_recommend']} live scored ranges since start. Live numbers "
                  "are indicative only and no proposal is made from them. Rows with fewer than "
                  f"{rv['min_n']} items are flagged `low n`.", ""]
    if d.get("partial_week"):
        lines += ["> The review week has not ended yet: numbers are partial.", ""]

    hdr = ["Window", "H", "n", "50% cover", "80% cover", "Naive 50%", "Naive 80%", "80% width", "Naive width",
           "80% score", "Naive score", "Flag"]
    rows = [range_row([win_names[w], h], s, rv) for w, per in d["ranges"].items() for h, s in per.items()]
    lines += ["## Ranges: coverage vs target", "",
              "Targets 50% and 80%. Width and interval score in % of price; score is lower-is-better. Naive = last "
              "close +/- 20-day volatility.", "", table(hdr, rows)]
    for title, key in (("By regime", "regime"), ("By sector", "sector"), ("By widening note", "note")):
        rows = [range_row([k], s, rv) for k, s in d["breakdowns"][key].items()]
        lines += [f"### {title} (since start)", "", table(["Group · H", *hdr[2:]], rows)]
    lines += ["Notes: `cue` overnight cue, `ai_call` AI direction (drift), `ai_widen` AI widened, `earnings` "
              "earnings in horizon, `event` major market event, `regime` regime widening, `none` no adjustment.", ""]

    rows = [[win_names[w], h, s["n"], fpct(s.get("hit_rate")), fpct(s.get("always_up")),
             "–" if s.get("edge") is None else f"{s['edge']:+.0%}", fpct(s.get("mean_confidence")), flag(s["n"], rv)]
            for w, per in d["calls"].items() for h, s in per.items()]
    lines += ["## Direction calls", "", "Hit rate vs the always-up baseline on the same tickers and dates.", "",
              table(["Window", "H", "n", "Hit rate", "Always-up", "Edge", "Mean conf.", "Flag"], rows),
              "### By confidence band (since start)", "",
              table(["Band", "n", "Mean conf.", "Hit rate", "Gap", "Flag"],
                    [[b, s["n"], fpct(s.get("mean_confidence")), fpct(s.get("hit_rate")),
                      "–" if s.get("gap") is None else f"{s['gap']:+.0%}", flag(s["n"], rv)]
                     for b, s in d["bands"].items()])]

    lines += [f"## Calibration (latest as of {rec['week_end']})", "",
              table(["H", "Source", "History n", "Live n", "q10", "q25", "q75", "q90"],
                    [[f"{c['horizon_days']}d", c["source"], c["n_history"], c["n_live"],
                      *(fnum(c[k], 2) for k in ("q10", "q25", "q75", "q90"))] for c in d["calibration"]])]

    ab_hdr = ["Variant", "n", f"50% cover ({hz})", f"80% cover ({hz})", f"80% width ({hz})", f"80% score ({hz})",
              "Score vs current", "Verdict"]
    live = d["live_ablation"]
    lines += ["## Ablation: replay of live scored ranges (since start)", "",
              "Each stored range is rebuilt with one input changed (same quantiles, base and outcome). Inputs that "
              "only exist live (cues, AI calls, earnings and event flags) can only be judged here.", ""]
    if live["n"]:
        lines += [f"Replay with the current config reproduces {live['reproduced']} of {live['n']} published ranges "
                  "(the rest used settings or inputs the replay holds fixed).", "", table(ab_hdr, ablation_rows(live))]
    else:
        lines += ["_No scored live ranges yet._", ""]
    hist = d["history_ablation"]
    lines += ["## Ablation: walk-forward on stored prices", ""]
    if hist.get("n"):
        share = ", ".join(f"{k} {v:.0%}" for k, v in hist["regime_share"].items() if v)
        lines += [f"Last {hist['sessions']} sessions up to {rec['week_end']}, built as `backtest.py` does (each day sees "
                  "only outcomes known before it), plus regime and market-event widening rebuilt from stored bars "
                  f"(regime mix: {share}). No AI, cue or earnings inputs.", "", table(ab_hdr, ablation_rows(hist))]
    else:
        lines += [f"_Not run: {hist.get('error', 'skipped')}._", ""]

    props = d["proposals"]
    lines += ["## Proposed changes to config/ranges.yaml", "",
              "**Not applied.** Shown for a human to decide in the weekly run; edit `config/ranges.yaml` by hand "
              "and note the change in the commit message.", ""]
    rows = []
    for p in props:
        for ch in p["changes"]:
            rows.append([f"`{ch['param']}`", fval(ch["current"]), fval(ch["proposed"]), p["source"], p["n"], f"{p['rel_score']:+.1%}",
                         " / ".join(f"{fpct(p['cover80_now'].get(h))} → {fpct(p['cover80_then'].get(h))}"
                                    for h in p["cover80_then"]), p["variant"]])
    lines += [table(["Parameter", "Current", "Proposed", "Evidence", "n", "Score change", f"80% cover ({hz})", "Variant"], rows)
              if rows else f"_None: no variant cleared the thresholds (n >= {rv['min_n_recommend']}, score "
              f"{rv['min_improvement']:.0%} better without coverage falling more than {rv['coverage_tolerance']:.0%} "
              f"further below target, or 80% coverage "
              f"{rv['min_coverage_gain']:.0%} closer to target)._\n"]
    drops = [p["variant"] for p in props if p["drop"]]
    lines += ["### What to drop", "", ("- " + "\n- ".join(drops)) if drops else "_Nothing: no input's removal "
              "cleared the thresholds._", "", "### Forecaster confidence", "",
              ("- " + "\n- ".join(d["advice"])) if d["advice"] else
              f"_No advice: no confidence band with n >= {rv['min_n_calls']} misses its stated confidence._", ""]
    lines += ["## Method", "",
              f"- Thresholds from `config/review.yaml`: flag below n={rv['min_n']}, no proposal below "
              f"n={rv['min_n_recommend']} ranges or n={rv['min_n_calls']} calls per band.",
              "- Score change = average over horizons of the relative change in the 80% interval score "
              "(negative is better).",
              "- Each variant changes one input against the current config; proposals are not tested together, "
              "so change one parameter at a time and let the next review confirm it.",
              "- Only coverage falling below target blocks a proposal; over-coverage is priced by the interval "
              "score and narrowed by the daily self-calibration (`calibrate.py`).",
              "- AI judgement is never backtested: AI drift and AI widening are judged only on live ranges.", ""]
    return "\n".join(lines)


# ---------- main ----------

def build(cfg: dict, rc: dict, rv: dict, con, week: str, history: bool = True) -> tuple[dict, dict]:
    start, end = week_bounds(week)
    roll_start = end - timedelta(days=rv["rolling_days"] - 1)
    ranges, calls = load_ranges(con, cfg, end), load_calls(con, end)
    windows = {"week": start, "rolling": roll_start, "all": date.min}

    def win(df, s):
        return df[df["target_date"] >= s] if not df.empty else df
    d = {"partial_week": end >= utc_today(),
         "ranges": {w: by_horizon(win(ranges, s), range_summary) for w, s in windows.items()},
         "calls": {w: by_horizon(win(calls, s), call_summary) for w, s in windows.items()},
         "breakdowns": {"regime": breakdown(ranges, "regime"), "sector": breakdown(ranges, "sector"),
                        "note": breakdown(ranges, "tags")},
         "bands": confidence_bands(calls, rv["confidence_bands"])}
    cal = con.execute("SELECT DISTINCT ON (horizon_days) * FROM calibration WHERE as_of_date <= ? "
                      "ORDER BY horizon_days, as_of_date DESC, computed_at DESC", [end]).df()
    d["calibration"] = [{k: (str(v)[:10] if k == "as_of_date" else v) for k, v in r.items() if k != "computed_at"}
                        for r in cal.to_dict("records")]
    d["live_ablation"] = live_ablation(ranges, rc, rv)
    d["history_ablation"] = history_ablation(cfg, rc, rv, load_bars(con), end) if history else \
        {"n": 0, "error": "skipped (--no-history)", "variants": []}
    for ab in (d["live_ablation"], d["history_ablation"]):
        judge(ab, rv)
    d["proposals"] = proposals(rc, d["live_ablation"], d["history_ablation"])
    d["advice"] = confidence_advice(d["bands"], d["calls"]["all"], rv)

    ra, ca = d["ranges"]["all"]["all"], d["calls"]["all"]["all"]
    rec = {"id": week, "week": week, "week_start": str(start), "week_end": str(end), "computed_at": utc_now(),
           "report": f"reports/{cfg['market']}/review-{week}.md",
           "n_ranges_week": d["ranges"]["week"]["all"]["n"], "n_ranges_30d": d["ranges"]["rolling"]["all"]["n"],
           "n_ranges_all": ra["n"], "n_calls_week": d["calls"]["week"]["all"]["n"], "n_calls_all": ca["n"],
           "cover50_all": ra.get("cover50"), "cover80_all": ra.get("cover80"), "score80_all": ra.get("score80_pct"),
           "naive_score80_all": ra.get("naive_score80_pct"), "call_hit_all": ca.get("hit_rate"),
           "always_up_all": ca.get("always_up"), "low_sample": ra["n"] < rv["min_n_recommend"],
           "n_proposals": len(d["proposals"]), "proposals": d["proposals"],
           "detail": {k: d[k] for k in ("ranges", "calls", "breakdowns", "bands", "calibration", "advice")} | {
               "live_ablation": d["live_ablation"], "history_ablation": d["history_ablation"],
               "thresholds": {k: rv[k] for k in DEFAULTS if not k.endswith("_variants")}}}
    return clean(rec), d


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--week", help="ISO week to review, e.g. 2026-W40 (default: the previous ISO week)")
    ap.add_argument("--if-due", action="store_true", help="do nothing if this week's review is already stored")
    ap.add_argument("--no-history", action="store_true", help="skip the walk-forward on stored prices")
    args = ap.parse_args()
    cfg = require_market(args)
    week = args.week or previous_week(utc_today())
    week_bounds(week)
    con = connect(cfg["market"])
    if args.if_due and con.execute("SELECT count(*) FROM reviews WHERE id = ?", [week]).fetchone()[0]:
        print(json.dumps({"step": "review", "market": cfg["market"], "week": week, "due": False,
                          "report": f"reports/{cfg['market']}/review-{week}.md"}, indent=2))
        return 0
    rv = load_review_config()
    rec, d = build(cfg, load_ranges_config(), rv, con, week, history=not args.no_history)
    path = ROOT / rec["report"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(cfg, rv, rec, d))
    out = day_file(cfg["market"], "reviews", utc_today())
    append_jsonl(out, [rec])
    print(json.dumps({"step": "review", "market": cfg["market"], "week": week, "due": True, "report": rec["report"],
                      "record": str(out.relative_to(ROOT)), "n_ranges_week": rec["n_ranges_week"],
                      "n_ranges_all": rec["n_ranges_all"], "n_calls_all": rec["n_calls_all"],
                      "low_sample": rec["low_sample"],
                      "proposals": [{**c, "source": p["source"], "n": p["n"], "rel_score": p["rel_score"]}
                                    for p in rec["proposals"] for c in p["changes"]]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
