"""The daily model score (scripts/model_scores.py; routine step 5a, after features.py, before context.py).

For the as-of date (the benchmark's newest bar, as features.py) and each horizon N+k of config/strategies.yaml
(core/horizons.py; buy at the open of D, sell at the close of the k-th session after D): the month's model is the
stored model_versions row fitted at the month's first as-of date, or, the first time the month is scored,
the walk-forward fit up to the as-of date (walk_forward.py; the same fit the backtest uses for that month),
which is then appended. Each watchlist ticker with a bar on the as-of date gets a model_scores row: the
issued probability (Platt-calibrated once enough past out-of-sample rows resolved), the fixed-prior news
term as of now, and the explanation (explain.py), labelled n_plus_k with D (entry_date) and the exit session
(exit_date) from the market calendar. A rerun appends a row only when the probability changed."""
from __future__ import annotations

import json

import pandas as pd

from marketbrief.constants.config_keys import CFG_MARKET, CFG_TICKERS
from marketbrief.constants.model import (VARIANT_BASE, VARIANT_CROSS, KIND_MODEL_SCORES, KIND_MODEL_VARIANT_SCORES,
                                         KIND_MODEL_VARIANT_VERSIONS, KIND_MODEL_VERSIONS, LABEL_OPEN_TO_CLOSE,
                                         MSG_NEWS_NOT_TRAINED, MSG_SCORE_STALE, MSG_TOO_LITTLE_HISTORY)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.core.database import connect
from marketbrief.core.horizons import entry_exit, horizons
from marketbrief.core.market_config import benchmark_key
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.model.explain import explain_row
from marketbrief.model.logistic import LogisticModel
from marketbrief.model.news_score import news_terms
from marketbrief.model.panel import build_panel
from marketbrief.model.panel_inputs import read_inputs
from marketbrief.model.settings import cross_groups, load_model_config
from marketbrief.model.backtest_variants import market_groups, with_groups
from marketbrief.model.walk_forward import MonthlyFit, refit_dates, walk_forward

PROB_DECIMALS = 4
STEP_NAME = "model_scores"


def version_id(market: str, horizon: int, model_version: str, cutoff, variant: str = VARIANT_BASE) -> str:
    """<market>-1d-open_to_close-<model_version>-<cutoff date> for N+1 (the same label as before B10, so its stored
    fits stay valid) and <market>-<k>d-n_plus_k-<model_version>-<cutoff date> for N+k, k >= 2 (a new label: the
    stored 5-day fits of the old D+4 label, ids with open_to_close, are never reused for N+5). The cross_market
    variant's fits end in -cross_market."""
    tag = LABEL_OPEN_TO_CLOSE if int(horizon) == 1 else LABEL_N_PLUS_K
    suffix = "" if variant == VARIANT_BASE else f"-{variant}"
    return f"{market}-{horizon}d-{tag}-{model_version}-{pd.Timestamp(cutoff).date()}{suffix}"


def score_id(as_of, ticker: str, horizon: int, variant: str = VARIANT_BASE) -> str:
    """<as_of>-<ticker>-<k>d (base, like the prediction it anchors) or ...-<k>d-cross_market."""
    return f"{as_of}-{ticker}-{horizon}d" + ("" if variant == VARIANT_BASE else f"-{variant}")


def variant_field(variant: str) -> dict:
    """{"model_variant": variant} on rows of the variant kinds; nothing on base rows (model_scores, model_versions)."""
    return {} if variant == VARIANT_BASE else {"model_variant": variant}


def kinds_of(variant: str) -> tuple[str, str]:
    """(scores kind, versions kind) a variant is stored in."""
    if variant == VARIANT_BASE:
        return KIND_MODEL_SCORES, KIND_MODEL_VERSIONS
    return KIND_MODEL_VARIANT_SCORES, KIND_MODEL_VARIANT_VERSIONS


def variant_settings(settings: dict, market: str) -> list[tuple[str, dict]]:
    """(variant, settings) of each written model: base = config/model.yaml as written; cross_market = every
    cross-market group of the market switched on."""
    return [(VARIANT_BASE, settings), (VARIANT_CROSS, with_groups(settings, market, market_groups(market)))]


def version_record(market: str, horizon: int, fit: MonthlyFit, settings: dict, variant: str = VARIANT_BASE) -> dict:
    """The model_versions row of a fit (the formula as JSON, no pickles)."""
    platt = fit.platt or (None, None)
    return {"id": version_id(market, horizon, settings["model_version"], fit.cutoff, variant), "market": market,
            **variant_field(variant),
            "horizon_days": horizon, "label_convention": LABEL_OPEN_TO_CLOSE, "horizon_label": LABEL_N_PLUS_K,
            "model_version": settings["model_version"], "trained_until": str(fit.cutoff.date()),
            "fitted_at": utc_now(), "train_rows": fit.train_rows, "train_sessions": fit.train_sessions,
            "base_rate": fit.base_rate, "model": fit.model.to_json(), "platt_slope": platt[0],
            "platt_offset": platt[1], "platt_rows": fit.platt_rows,
            "settings": {k: v for k, v in settings.items() if k not in ("backtest",)}}


def fit_from_record(row: dict) -> MonthlyFit:
    """A stored model_versions row back as a MonthlyFit."""
    model = row["model"] if isinstance(row["model"], dict) else json.loads(row["model"])
    platt = None if row["platt_slope"] is None or pd.isna(row["platt_slope"]) else (row["platt_slope"],
                                                                                   row["platt_offset"])
    return MonthlyFit(pd.Timestamp(row["trained_until"]), LogisticModel.from_json(model), platt,
                      int(row["platt_rows"]), float(row["base_rate"]), int(row["train_rows"]),
                      int(row["train_sessions"]))


def month_fit(con, panel: pd.DataFrame, spec: tuple, as_of: pd.Timestamp,
              settings: dict) -> tuple[MonthlyFit | None, dict | None]:
    """(the as-of month's fit, the new model_versions row to append or None). spec = (market, horizon[, variant])."""
    market, horizon, variant = (*spec, VARIANT_BASE)[:3]
    cutoff = refit_dates(panel.loc[panel["date"] <= as_of, "date"])[-1]
    wanted = version_id(market, horizon, settings["model_version"], cutoff, variant)
    table = "model_versions_latest" if variant == VARIANT_BASE else (
        f"(SELECT DISTINCT ON (id) * FROM {KIND_MODEL_VARIANT_VERSIONS} ORDER BY id, fitted_at DESC)")
    stored = con.execute(f"SELECT * FROM {table} WHERE id = ?", [wanted]).df()
    if len(stored):
        return fit_from_record(stored.iloc[0].to_dict()), None
    _, fits = walk_forward(panel, (market, LABEL_OPEN_TO_CLOSE, horizon), settings, until=as_of)
    if not fits or fits[-1].cutoff != cutoff:
        return None, None
    return fits[-1], version_record(market, horizon, fits[-1], settings, variant)


def latest_probabilities(con) -> dict[str, tuple[float, str]]:
    """id -> (prob_up, model_id) of the newest stored score of every variant (ids differ between variants)."""
    out = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id, prob_up, model_id FROM model_scores_latest").fetchall()}
    out.update({r[0]: (r[1], r[2]) for r in con.execute(
        f"SELECT DISTINCT ON (id) id, prob_up, model_id FROM {KIND_MODEL_VARIANT_SCORES} "
        "ORDER BY id, computed_at DESC").fetchall()})
    return out


def score_record(fit: MonthlyFit, row: pd.DataFrame, news: dict, meta: dict) -> dict:
    """One model_scores row. meta: ticker, horizon, as_of, model_id, model_version, variant, entry and exit (D and
    the exit session of N+k)."""
    explanation = explain_row(fit, row, news["logit"], news["text"])
    explanation["news"] = {k: news[k] for k in ("score", "items", "ids", "by_event_type")}
    explanation["news"]["note"] = MSG_NEWS_NOT_TRAINED
    as_of = meta["as_of"].date()
    return {"id": score_id(as_of, meta["ticker"], meta["horizon"], meta["variant"]), "as_of_date": str(as_of),
            "ticker": meta["ticker"], **variant_field(meta["variant"]),
            "horizon_days": meta["horizon"], "label_convention": LABEL_OPEN_TO_CLOSE,
            "prob_up": round(explanation["prob_up"], PROB_DECIMALS),
            "prob_model": round(explanation["prob_model"], PROB_DECIMALS), "calibrated": fit.platt is not None,
            "base_rate": round(fit.base_rate, PROB_DECIMALS), "news_score": news["score"],
            "news_logit": round(news["logit"], 6), "contributions": explanation,
            "model_version": meta["model_version"], "model_id": meta["model_id"],
            "trained_until": str(fit.cutoff.date()), "computed_at": utc_now(), "horizon_label": LABEL_N_PLUS_K,
            "entry_date": str(meta["entry"]), "exit_date": str(meta["exit"])}


def run(cfg: dict) -> dict:
    """Score every watchlist ticker and horizon for the as-of date; returns the JSON summary."""
    market, settings = cfg[CFG_MARKET], load_model_config()
    con = connect(market)
    inputs = read_inputs(con, market)
    variants = variant_settings(settings, market)
    union = tuple(sorted({g for _, s in variants for g in cross_groups(s, market)}))
    panel = build_panel(cfg, inputs, settings["warmup_bars"], union)
    as_of = inputs["bars"][benchmark_key(cfg)].index[-1]
    tickers = list(cfg[CFG_TICKERS])
    news = news_terms(con, tickers, pd.Timestamp(clock()), settings["news"])
    stored = latest_probabilities(con)
    today_rows = panel[panel["date"] == as_of].set_index("ticker") if len(panel) else pd.DataFrame()
    scores, versions, notes, unchanged = [], [], [], 0
    for (variant, model_settings), horizon in ((v, h) for v in variants for h in horizons()):
        fit, record = (month_fit(con, panel, (market, horizon, variant), as_of, model_settings) if len(panel)
                       else (None, None))
        if fit is None:
            notes.append(MSG_TOO_LITTLE_HISTORY.format(cutoff=as_of.date(), sessions=panel["date"].nunique()
                                                       if len(panel) else 0, need=settings["min_train_sessions"]))
            continue
        versions += [record] if record else []
        entry, exit_day = entry_exit(cfg, as_of.date(), horizon)
        meta = {"horizon": horizon, "as_of": as_of, "model_version": settings["model_version"], "variant": variant,
                "model_id": version_id(market, horizon, settings["model_version"], fit.cutoff, variant), "entry": entry,
                "exit": exit_day}
        for ticker in tickers:
            if ticker not in today_rows.index:
                last = inputs["bars"][ticker].index[-1].date() if ticker in inputs["bars"] else None
                notes.append(MSG_SCORE_STALE.format(ticker=ticker, last=last, as_of=as_of.date()))
                continue
            rec = score_record(fit, today_rows.loc[[ticker]].reset_index(), news[ticker], {**meta, "ticker": ticker})
            if stored.get(rec["id"]) == (rec["prob_up"], rec["model_id"]):
                unchanged += 1
                continue
            scores.append(rec)
    for variant, _ in variants:
        scores_kind, versions_kind = kinds_of(variant)
        for kind, rows in ((versions_kind, versions), (scores_kind, scores)):
            own = [row for row in rows if row.get("model_variant", VARIANT_BASE) == variant]
            if own:
                append_jsonl(day_file(market, kind, utc_today()), own)
    return {"step": STEP_NAME, "market": market, "as_of_date": str(as_of.date()), "scores": len(scores),
            "unchanged": unchanged, "new_model_versions": [v["id"] for v in versions], "notes": sorted(set(notes))}


def main() -> int:
    """Entry point of scripts/model_scores.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps(run(cfg), indent=2, default=str))
    return 0
