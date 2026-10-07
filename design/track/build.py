"""Assemble the data for the Track record screen (both markets) and inline it into template.html.

    python design/track/build.py --out design/track

writes <out>/track.html and <out>/data-track.json. The screen is the proof gate for "Paper": the live record
(scored calls by confidence band, scored ranges, what is open and waiting), the weekly review's verdict on model
skill, and the back-tests clearly tagged (rule replay coverage by horizon, regime, month and ticker; the
walk-forward model's Brier, AUC, reliability, thresholds and paper strategy after costs against baselines).
Read-only on the repo; the replay runs into work/design/ when its JSON is missing."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from marketbrief.core.calendar import prev_session  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from system import inline_system  # noqa: E402

spec = importlib.util.spec_from_file_location("decision_build", os.path.join(REPO, "design", "decision", "build.py"))
decision_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decision_build)


def market_block(market: str, review_cfg: dict) -> dict:
    con = connect(market)
    cfg = load_market(market)

    def q(sql):
        return con.execute(sql).df()

    tickers = list(cfg["tickers"])
    end = date.fromisoformat(str(q(f"select max(date) d from ohlc where ticker in ({','.join(repr(t) for t in tickers)})").iloc[0, 0])[:10])
    start = end
    for _ in range(decision_build.SESSIONS_BACK):
        start = prev_session(cfg, start - timedelta(days=1))
    replay = decision_build.replay_summary_json(market, start, end)
    bt, bt_path = decision_build.backtest_json(market)
    res = bt["results"][market]

    # ---- live record
    bands = review_cfg["confidence_bands"]
    live_calls = q("""select p.horizon_days, p.confidence, o.hit, o.label_basis from outcomes o join predictions p on p.id = o.prediction_id""").to_dict("records")
    by_band = []
    for lo in bands:
        rows = [r for r in live_calls if r["confidence"] >= lo and r["confidence"] < lo + 0.10]
        by_band.append({"band": lo, "n": len(rows), "hits": sum(1 for r in rows if r["hit"]), "hit_rate": (sum(1 for r in rows if r["hit"]) / len(rows)) if rows else None})
    n_pred = int(q("select count(*) from predictions").iloc[0, 0])
    n_open_pred = int(q("select count(*) from open_predictions").iloc[0, 0])
    rr = q("select count(*) n, avg(case when hit50 then 1 else 0 end) c50, avg(case when hit80 then 1 else 0 end) c80, avg(is80_pct) s80, avg(naive_is80_pct) ns80 from range_record").to_dict("records")[0]
    open_r = q("select count(*) n, min(target_date) tfirst, max(target_date) tlast, min(as_of_date) first_asof from open_ranges").to_dict("records")[0]
    lessons = int(q("select count(*) from lessons").iloc[0, 0])
    review = q("select * from reviews order by computed_at desc limit 1").to_dict("records")
    review = review[0] if review else None
    if review:
        review = {k: review[k] for k in ("week", "week_start", "week_end", "computed_at", "report", "n_ranges_week", "n_ranges_30d", "n_ranges_all", "n_calls_week", "n_calls_all",
                                         "cover50_all", "cover80_all", "score80_all", "naive_score80_all", "call_hit_all", "always_up_all", "low_sample", "n_proposals", "model_skill")}
        props = q("select proposals from reviews order by computed_at desc limit 1").iloc[0, 0]
        try:
            review["proposals"] = [{"variant": p.get("variant"), "verdict": p.get("verdict"), "source": p.get("source"), "n": p.get("n")} for p in json.loads(props)] if props else []
        except Exception:
            review["proposals"] = []
    first_live_range = q("select min(as_of_date) d, min(made_at) t from ranges").to_dict("records")[0]

    # ---- model skill gate (same rule as pipeline/review/model_skill.py, applied to the 5d open-to-close result)
    ms = review_cfg["model_skill"]
    gate_rows = []
    for key in ("1d open_to_close", "5d open_to_close"):
        v = res[key]
        gate_rows.append({"label": key, "n": v["n"], "n_ok": v["n"] >= ms["min_n"], "brier_skill": v["brier_skill"], "brier_ok": v["brier_skill"] > ms["min_brier_skill"],
                          "auc": v["auc"], "auc95": v["auc95"], "auc_ok": v["auc95"][0] > ms["min_auc_low"], "brier": v["brier"], "brier_base": v["brier_base_rate"],
                          "dates": v["dates"], "first_date": v["first_date"], "last_date": v["last_date"], "up_share": v["up_share"]})

    # ---- back-test summaries kept compact for the page
    def h_block(h):
        hz = replay["horizons"][h]
        keep = lambda d: {k: d.get(k) for k in ("n", "days", "cover50", "cover80", "cover80_ci", "width50_pct", "width80_pct", "score80", "naive_score80", "naive_cover80", "naive_cover50", "qs_pct", "abs_err_pct")}  # noqa: E731
        return {"overall": keep(hz["overall"]), "by_regime": {k: keep(v) for k, v in hz["by_regime"].items()}, "by_month": {k: keep(v) for k, v in hz["by_month"].items()},
                "by_ticker": {k: keep(v) for k, v in hz["by_ticker"].items()}, "by_sector": {k: keep(v) for k, v in hz.get("by_sector", {}).items()}}
    rep = {"window": [replay["start"], replay["end"]], "computed_at": replay["computed_at"], "horizons": {h: h_block(h) for h in ("1", "5")},
           "baselines": {h: {k: {kk: v.get(kk) for kk in ("label", "calls", "hits", "hit_rate", "ci95")} for k, v in replay["baselines"][h].items()} for h in ("1", "5")},
           "regime_days": replay["regime_days"], "summary": replay.get("summary", [])[:6], "limitations": replay.get("limitations", [])}
    model = {}
    for key, v in res.items():
        model[key] = {k: v.get(k) for k in ("label", "n", "dates", "first_date", "last_date", "up_share", "brier", "brier_base_rate", "brier_skill", "log_loss", "log_loss_base_rate", "auc", "auc95", "calibrated_share", "reliability", "thresholds")}
        model[key]["paper"] = v.get("paper")
        model[key]["model"] = {k: v["model"].get(k) for k in ("fits", "first_cutoff", "last_cutoff", "last_train_rows", "last_base_rate", "last_platt")} if v.get("model") else None
    # expected dates: 20 ranges a day -> when will min_n_recommend real ranges be checked (1-day ranges settle the next session)
    from marketbrief.core.calendar import next_session, sessions_ahead
    today = next_session(cfg, end + timedelta(days=1))
    needed = max(0, review_cfg["min_n_recommend"] - int(rr["n"]))
    days_needed = -(-needed // len(tickers))
    ahead = sessions_ahead(cfg, today, days_needed + 2)
    ranges_by = str(ahead[min(len(ahead) - 1, days_needed + 1)]) if needed else str(today)
    expected = {"ranges_needed": review_cfg["min_n_recommend"], "ranges_checked": int(rr["n"]), "ranges_per_day": len(tickers), "ranges_by": ranges_by,
                "calls_needed": review_cfg["min_n_calls"], "calls_checked": len(live_calls), "calls_made": n_pred, "today": str(today)}
    return {"market": market, "market_name": cfg["name"], "n_tickers": len(tickers), "as_of": str(end), "currency": decision_build.CURRENCY[cfg["currency"]], "expected": expected,
            "live": {"calls_total": len(live_calls), "calls_by_band": by_band, "predictions": n_pred, "open_predictions": n_open_pred,
                     "ranges_scored": int(rr["n"]), "ranges_cover50": None if rr["c50"] is None or rr["c50"] != rr["c50"] else float(rr["c50"]), "ranges_cover80": None if rr["c80"] is None or rr["c80"] != rr["c80"] else float(rr["c80"]),
                     "open_ranges": int(open_r["n"]), "open_first_target": None if open_r["tfirst"] is None else str(open_r["tfirst"])[:10], "open_last_target": None if open_r["tlast"] is None else str(open_r["tlast"])[:10],
                     "first_live_range_asof": None if first_live_range["d"] is None else str(first_live_range["d"])[:10], "lessons": lessons},
            "review": review, "gates": gate_rows, "replay": rep, "model": model, "bt_computed_at": bt.get("computed_at"), "bt_path": os.path.relpath(bt_path, REPO),
            "verdicts": bt.get("verdicts", [])[:8]}


def build() -> dict:
    review_cfg = yaml.safe_load(open(os.path.join(REPO, "config", "review.yaml")))
    settings = yaml.safe_load(open(os.path.join(REPO, "config", "settings.yaml")))
    markets = {m: market_block(m, review_cfg) for m in ("india", "us")}
    return decision_build.clean({"built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "markets": markets,
                                 "rules": {"confidence_bands": review_cfg["confidence_bands"], "min_n_calls": review_cfg["min_n_calls"], "calibration_tolerance": review_cfg["calibration_tolerance"],
                                           "model_skill": review_cfg["model_skill"], "min_n": review_cfg["min_n"], "call_scoring_from": str(settings.get("call_scoring", {}).get("from", ""))}})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = build()
    json.dump(data, open(os.path.join(a.out, "data-track.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    html = inline_system(tpl.replace("/*__DATA__*/null", payload))
    out = os.path.join(a.out, "track.html")
    open(out, "w").write(html)
    for m, b in data["markets"].items():
        print(f"{m}: live calls {b['live']['calls_total']} ranges scored {b['live']['ranges_scored']} open ranges {b['live']['open_ranges']} gates {[(g['label'], g['n_ok'], g['brier_ok'], g['auc_ok']) for g in b['gates']]}")
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
