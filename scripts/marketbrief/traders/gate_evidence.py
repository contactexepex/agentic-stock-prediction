"""The evidence and model-anchor rules of the traders' gate (docs/SPEC.md F2.6, F4.2), shared with the forecaster's
gate: the news-verification rules are `prediction_rules.check_news_status` and the anchor is
`model.forecast_rules.anchor_errors`, applied unchanged.

- Evidence ids: 1-3 ids. An id with a prefix of INPUT_PREFIXES names an input the trader read and must be this
  ticker's and as-of date's (`features:<as_of>-<ticker>`, `regime:<as_of>`, `model_scores:<as_of>-<ticker>-<k>d`);
  every other id is a news, filing or announcement id that must be stored and public by made_at.
- Blindness: a trader may cite only the kinds of its inputs (config/strategies.yaml parameters.inputs); the blind
  traders (news, pattern) may not state model_prob, agent_adjustment or adjustment_reason.
- News (DESIGN.md 3b): the first cited news id must be confirmed_primary or corroborated as of made_at; rumour and
  promotional never; contradicted only with range_widen; single_source or unverified caps confidence at 0.85.
- Anchor (combined traders, forecast-v11): with a stored score for the id (computed by made_at) model_prob is that
  score, |agent_adjustment| <= 0.10 with a reason, direction and confidence from the sum, prob_up = the sum; a non-zero
  adjustment cites a news, filing or announcement id. With no score the anchor fields stay out (warning)."""
from __future__ import annotations

from datetime import datetime

from marketbrief.analytics.prediction_rules import check_news_status
from marketbrief.constants.model import CODE_MODEL_SCORE_MISSING
from marketbrief.constants.verification import CODE_NEWS_STATUS_MISSING
from marketbrief.model.forecast_rules import anchor_errors, is_number
from marketbrief.traders import constants as c
from marketbrief.traders.inputs import GateInputs
from marketbrief.traders.registry import Trader
from marketbrief.utils.timefmt import as_utc_timestamp


def citable_kinds(one: Trader) -> set[str]:
    """The evidence kinds this trader may cite: 'news' and/or input prefixes."""
    return {c.CITABLE_BY_INPUT[name] for name in one.inputs if name in c.CITABLE_BY_INPUT}


def input_errors(rec: dict, one: Trader, frame: dict, ids: list[str]) -> list[tuple[str, str]]:
    """Input ids: allowed for this trader and naming this ticker's inputs of this as-of date."""
    want = {c.INPUT_FEATURES: f"{c.INPUT_FEATURES}{frame['as_of']}-{rec['ticker']}",
            c.INPUT_REGIME: f"{c.INPUT_REGIME}{frame['as_of']}",
            c.INPUT_MODEL: f"{c.INPUT_MODEL}{frame['range']['id']}"}
    kinds, out = citable_kinds(one), []
    for evidence_id in ids:
        prefix = next(prefix for prefix in c.INPUT_PREFIXES if evidence_id.startswith(prefix))
        if prefix not in kinds:
            out.append((c.CODE_BLIND, c.MSG_BLIND_CITE.format(strategy_id=one.strategy_id, kind=prefix.rstrip(":"),
                                                               ids=[evidence_id])))
        elif evidence_id != want[prefix]:
            out.append((c.CODE_EVIDENCE, c.MSG_INPUT_ID.format(id=evidence_id, want=want[prefix])))
        elif prefix == c.INPUT_MODEL and frame["score"] is None:
            out.append((c.CODE_EVIDENCE, c.MSG_EVIDENCE_UNKNOWN.format(ids=[evidence_id])))
    return out


def news_errors(one: Trader, gi: GateInputs, made: datetime, ids: list[str]) -> list[tuple[str, str]]:
    """News ids: allowed for this trader, stored, and public by made_at."""
    if not ids:
        return []
    if c.CITE_NEWS not in citable_kinds(one):
        return [(c.CODE_BLIND, c.MSG_BLIND_CITE.format(strategy_id=one.strategy_id, kind="news", ids=ids))]
    out = []
    unknown = [evidence_id for evidence_id in ids if evidence_id not in gi.evidence]
    if unknown:
        out.append((c.CODE_EVIDENCE, c.MSG_EVIDENCE_UNKNOWN.format(ids=unknown)))
    late = [evidence_id for evidence_id in ids if gi.evidence.get(evidence_id) is not None
            and as_utc_timestamp(gi.evidence[evidence_id]) > as_utc_timestamp(made)]
    if late:
        out.append((c.CODE_LOOKAHEAD, c.MSG_EVIDENCE_LATE.format(made_at=made.isoformat(), ids=late)))
    return out


def evidence_errors(rec: dict, one: Trader, gi: GateInputs, frame: dict) -> tuple[list, list]:
    """(errors, warnings) of the evidence ids and their news-verification status."""
    ids = rec["evidence_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= c.MAX_EVIDENCE or not all(isinstance(i, str) for i in ids):
        count = len(ids) if isinstance(ids, list) else ids
        return [(c.CODE_EVIDENCE, c.MSG_EVIDENCE_COUNT.format(most=c.MAX_EVIDENCE, count=count))], []
    inputs = [evidence_id for evidence_id in ids if evidence_id.startswith(c.INPUT_PREFIXES)]
    news = [evidence_id for evidence_id in ids if not evidence_id.startswith(c.INPUT_PREFIXES)]
    errors = input_errors(rec, one, frame, inputs) + news_errors(one, gi, frame["made"], news)
    if errors or not news:
        return errors, []
    if not gi.statuses.active(frame["made"]):
        return [], [(CODE_NEWS_STATUS_MISSING, f"no news status rows by {frame['made'].isoformat()}: "
                                               "evidence status rules not applied")]
    statuses = [gi.statuses.of(evidence_id, rec["ticker"], frame["made"]) for evidence_id in news]
    view = {"evidence_ids": news, "confidence": frame["confidence"], "range_widen": frame["widen"]}
    return list(check_news_status(view, statuses)), []


def anchor_check(rec: dict, one: Trader, frame: dict, news_cited: bool) -> tuple[list, list]:
    """(errors, warnings) of the model anchor; blind traders may not state its fields."""
    stated = [name for name in c.ANCHOR_FIELDS if rec.get(name) not in (None, "")]
    if not one.sees_model_score:
        return ([(c.CODE_BLIND, c.MSG_BLIND_FIELD.format(strategy_id=one.strategy_id, fields=stated))]
                if stated else []), []
    score = frame["score"]
    if score is None:
        if rec.get("model_prob") is None:
            return [], [(CODE_MODEL_SCORE_MISSING, f"no model score {frame['range']['id']}: anchor not applied")]
        return [(c.CODE_ANCHOR, "model_prob given but no model score is stored for this id")], []
    if as_utc_timestamp(score["computed_at"]) > as_utc_timestamp(frame["made"]):
        return [(c.CODE_LOOKAHEAD, c.MSG_SCORE_LATE.format(id=score["id"], computed=score["computed_at"],
                                                           made_at=frame["made"].isoformat()))], []
    view = {key: rec.get(key) for key in (*c.ANCHOR_FIELDS, "direction")} | {"confidence": frame["confidence"]}
    errors = [(c.CODE_ANCHOR, message) for message in anchor_errors(view, float(score["prob_up"]))]
    adjustment = rec.get("agent_adjustment")
    if is_number(adjustment) and is_number(rec.get("model_prob")):
        final = float(score["prob_up"]) + float(adjustment)
        if abs(float(rec["prob_up"]) - final) > c.PROB_TOLERANCE:
            errors.append((c.CODE_ANCHOR, c.MSG_PROB_SUM.format(prob=rec["prob_up"], final=round(final, 4))))
        if abs(float(adjustment)) > 1e-9 and not news_cited:
            errors.append((c.CODE_ANCHOR, c.MSG_ADJUSTMENT_EVIDENCE.format(adjustment=adjustment)))
    return errors, []
