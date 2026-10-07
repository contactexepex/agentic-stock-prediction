"""Column types of the signal model's kinds and of the persisted agent reasoning (docs/DESIGN.md section 15)."""
from __future__ import annotations

from marketbrief.constants.model import (KIND_AGENT_REASONING, KIND_MODEL_SCORES, KIND_MODEL_VARIANT_SCORES,
                                         KIND_MODEL_VARIANT_VERSIONS, KIND_MODEL_VERSIONS)
from marketbrief.core.schema_base import Schemas

MODEL_SCHEMAS: Schemas = {
    # One row per ticker x horizon x as-of date (model_scores.py, after features.py, before the forecaster);
    # a rerun appends a newer row only when the probability changed (view model_scores_latest). id =
    # <as_of_date>-<ticker>-<h>d like the prediction it anchors. prob_up = the issued probability that the
    # label_convention return is > 0 (prob_model: before the news term); contributions: the explanation
    # (explain.py: points per feature and group, top drivers, missing features, news items).
    KIND_MODEL_SCORES: ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "ticker": "VARCHAR", "horizon_days": "INTEGER",
        "label_convention": "VARCHAR", "prob_up": "DOUBLE", "prob_model": "DOUBLE", "calibrated": "BOOLEAN",
        "base_rate": "DOUBLE", "news_score": "DOUBLE", "news_logit": "DOUBLE", "contributions": "JSON",
        "model_version": "VARCHAR", "model_id": "VARCHAR", "trained_until": "DATE", "computed_at": "TIMESTAMPTZ",
        # B10 (docs/SPEC.md F2.7): n_plus_k on every row written from then on (null on older rows: open-to-close
        # 1-day = N+1, 5-day = legacy_5d_d4, core/horizons.legacy_label); D and the exit session of N+k
        "horizon_label": "VARCHAR", "entry_date": "DATE", "exit_date": "DATE",
    }),
    # One row per fitted model (monthly refit; model_scores.py appends it the first time a month is scored).
    # model = the formula as JSON (features, training means and sds, coefficients, intercept, z_clip,
    # excluded features with reasons); Platt slope/offset null while uncalibrated.
    KIND_MODEL_VERSIONS: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "horizon_days": "INTEGER", "label_convention": "VARCHAR",
        "model_version": "VARCHAR", "trained_until": "DATE", "fitted_at": "TIMESTAMPTZ", "train_rows": "INTEGER",
        "train_sessions": "INTEGER", "base_rate": "DOUBLE", "model": "JSON", "platt_slope": "DOUBLE",
        "platt_offset": "DOUBLE", "platt_rows": "INTEGER", "settings": "JSON",
        "horizon_label": "VARCHAR",  # B10: n_plus_k on fits from then on (null: open-to-close as before B10)
    }),
    # The day's debate per ticker (forecaster, after the forecast gate; agent_reasoning.py validate|add):
    # id = <as_of_date>-<ticker>; bull_case and bear_case as the researchers argued them (<= 80 words each),
    # verdict = the forecaster's reason (<= 60 words); decision_1d / decision_5d up | down | abstain (required);
    # decision_2d .. decision_4d the same for N+2..N+4 (B10; optional, absent = abstain);
    # evidence_ids: cited news/filing/announcement ids (public by made_at); prediction_ids: the stored calls.
    KIND_AGENT_REASONING: ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "ticker": "VARCHAR", "made_at": "TIMESTAMPTZ",
        "bull_case": "VARCHAR", "bear_case": "VARCHAR", "verdict": "VARCHAR", "decision_1d": "VARCHAR",
        "decision_5d": "VARCHAR", "decision_2d": "VARCHAR", "decision_3d": "VARCHAR", "decision_4d": "VARCHAR",
        "evidence_ids": "VARCHAR[]", "prediction_ids": "VARCHAR[]",
        "prompt_version": "VARCHAR", "written_at": "TIMESTAMPTZ",
    }),
}
# B10: the other model variants (constants/model.py MODEL_VARIANTS; today cross_market = every cross-market group on,
# for strategies with `cross_market: true`), kept apart from model_scores / model_versions so their readers never see
# them: the same columns plus model_variant; ids end in -<variant>. Read with contracts/horizons.scores_asof(variant=).
MODEL_SCHEMAS[KIND_MODEL_VARIANT_SCORES] = ("jsonl", {**MODEL_SCHEMAS[KIND_MODEL_SCORES][1],
                                                     "model_variant": "VARCHAR"})
MODEL_SCHEMAS[KIND_MODEL_VARIANT_VERSIONS] = ("jsonl", {**MODEL_SCHEMAS[KIND_MODEL_VERSIONS][1],
                                                       "model_variant": "VARCHAR"})
