"""The deterministic gate of one AI-trader prediction (docs/SPEC.md F4.2, F2.6), shared with the existing prediction
rules (the CLAUDE.md rules as F2.6 changes them for strategies; the news and anchor rules in gate_evidence.py):

- schema: only the trader's fields (constants.PREDICTION_FIELDS) and copies of derived ones, which must equal them;
- the trader: its own strategy_id, prompt_version and horizons (decision 38: N+1, N+3, N+5);
- the company: active, with an indicator snapshot and a regime row; no call with quality BLOCKED or earnings within
  1 day; id = <strategy_id>:<as_of_date>-<ticker>-<k>d with as_of_date = its latest price date, never stored twice;
- time: made_at ISO UTC, not after the gate's clock, not after the deadline (D's open - 15 minutes), not before the
  range it uses was published;
- probability: direction = the side of 0.5 of prob_up, confidence = max(prob_up, 1 - prob_up) within 0.50-0.90,
  at most 0.65 in an UNSTABLE regime, and not in a band its own track record closed;
- range: the published range of this ticker, horizon and D (ranges.py per horizon) may only be widened
  (range_widen 0-0.5); stated band edges must not be narrower and must equal the widened ones;
- target: inside the widened 80% range and on the call's side of the as-of close;
- reason: 1-60 words."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from marketbrief.core.calendar import session_open_utc
from marketbrief.model.forecast_rules import is_number
from marketbrief.traders import constants as c
from marketbrief.traders import track_record
from marketbrief.traders.gate_evidence import anchor_check, evidence_errors
from marketbrief.traders.inputs import GateInputs
from marketbrief.traders.records import EDGES, horizon_id, prediction_id, prediction_row, widened
from marketbrief.traders.registry import Trader
from marketbrief.traders.sessions import deadline, entry_session, exit_session
from marketbrief.utils.timefmt import ISO_UTC, as_utc_timestamp

REQUIRED = ("strategy_id", "ticker", "horizon_days", "direction", "prob_up", "target_price", "evidence_ids", "reason",
            "made_at", "prompt_version")   # made_at: stamped by run.stamped (always for a clockless trader)


@dataclass
class Verdict:
    """One record's result: the row to store (None when refused), blocking errors and warnings as (code, message)."""

    row: dict | None
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)


def schema_errors(rec) -> list[tuple[str, str]]:
    """Unknown or missing fields."""
    if not isinstance(rec, dict):
        return [(c.CODE_SCHEMA, "not a JSON object")]
    allowed = set(c.PREDICTION_FIELDS) | set(c.COPYABLE_FIELDS)
    errors = [(c.CODE_SCHEMA, c.MSG_UNKNOWN_FIELD.format(field=name)) for name in rec if name not in allowed]
    errors += [(c.CODE_SCHEMA, c.MSG_MISSING.format(field=name)) for name in REQUIRED if rec.get(name) in (None, "")]
    if not errors and (not isinstance(rec["horizon_days"], int) or isinstance(rec["horizon_days"], bool)):
        errors.append((c.CODE_SCHEMA, "horizon_days must be an integer"))
    if not errors and not isinstance(rec["ticker"], str):
        errors.append((c.CODE_SCHEMA, "ticker must be text"))
    return errors


def trader_errors(rec: dict, one: Trader) -> list[tuple[str, str]]:
    """The record is this trader's, with its prompt version and one of its horizons."""
    errors = []
    if rec["strategy_id"] != one.strategy_id:
        errors.append((c.CODE_STRATEGY, c.MSG_NOT_TRADER.format(strategy_id=rec["strategy_id"], want=one.strategy_id)))
    if rec["prompt_version"] != one.prompt_version:
        errors.append((c.CODE_STRATEGY, c.MSG_PROMPT_VERSION.format(got=rec["prompt_version"],
                                                                    want=one.prompt_version)))
    if rec["horizon_days"] not in one.horizons:
        errors.append((c.CODE_STRATEGY, c.MSG_HORIZON.format(horizon=rec["horizon_days"], horizons=list(one.horizons))))
    return errors


def company_errors(rec: dict, gi: GateInputs) -> list[tuple[str, str]]:
    """Active, a snapshot and a regime row, not BLOCKED, no earnings within a day."""
    ticker = rec["ticker"]
    if ticker not in gi.active:
        return [(c.CODE_TICKER, c.MSG_TICKER.format(ticker=ticker))]
    feats = gi.features.get(ticker)
    if feats is None:
        return [(c.CODE_BLOCKED, f"no indicator snapshot for {ticker}: no prediction")]
    errors = []
    if feats["quality"] == c.QUALITY_BLOCKED:
        errors.append((c.CODE_BLOCKED, c.MSG_BLOCKED.format(ticker=ticker)))
    days = feats["days_to_earnings"]
    if days is not None and days <= c.EARNINGS_DAYS_BLOCK:
        errors.append((c.CODE_EARNINGS, c.MSG_EARNINGS.format(ticker=ticker, days=days)))
    if feats["as_of_date"] not in gi.regimes:
        errors.append((c.CODE_BLOCKED, f"no regime row for {feats['as_of_date']}: no prediction"))
    return errors


def frame_of(rec: dict, gi: GateInputs) -> tuple[dict | None, list[tuple[str, str]]]:
    """The derived values of the record (dates, range, score, regime, ...) or the time/range errors."""
    feats, cfg = gi.features[rec["ticker"]], gi.cfg
    as_of = feats["as_of_date"]
    session = entry_session(cfg, as_of)
    exit_day = exit_session(cfg, session, rec["horizon_days"])
    made = as_utc_timestamp(rec["made_at"]) if ISO_UTC.match(str(rec["made_at"])) else None
    if made is None:
        return None, [(c.CODE_TIME, c.MSG_MADE_AT.format(made_at=rec["made_at"]))]
    made = made.to_pydatetime()
    errors, due = [], deadline(cfg, session)
    if made > gi.now + timedelta(minutes=c.FUTURE_TOLERANCE_MINUTES):
        errors.append((c.CODE_TIME, c.MSG_FUTURE.format(made_at=made.isoformat(), now=gi.now.isoformat())))
    if made > due:
        errors.append((c.CODE_TIME, c.MSG_AFTER_DEADLINE.format(made_at=made.isoformat(), deadline=due.isoformat(),
                                                                open=session_open_utc(cfg, session).isoformat(),
                                                                minutes=c.DEADLINE_MINUTES)))
    rid = horizon_id(as_of, rec["ticker"], rec["horizon_days"])
    rng = gi.range_for(rid, made)
    if rng is None:
        return None, [*errors, (c.CODE_RANGE, c.MSG_NO_RANGE.format(range_id=rid))]
    if str(rng["entry_date"]) != str(session) or str(rng["exit_date"]) != str(exit_day):
        errors.append((c.CODE_RANGE, c.MSG_RANGE_SESSION.format(range_id=rid, range_session=rng["entry_date"],
                                                                session=session) + f" (exit {exit_day})"))
    if as_utc_timestamp(rng["made_at"]) > as_utc_timestamp(made):
        errors.append((c.CODE_LOOKAHEAD, c.MSG_BEFORE_INPUT.format(made_at=made.isoformat(), what="range " + rid,
                                                                   published=rng["made_at"])))
    widen = rec.get("range_widen", 0) if rec.get("range_widen") is not None else 0
    if not is_number(widen) or not 0 <= widen <= c.WIDEN_MAX:
        return None, [*errors, (c.CODE_RANGE, c.MSG_WIDEN.format(widen_max=c.WIDEN_MAX, widen=widen))]
    prob = rec["prob_up"]
    confidence = round(max(prob, 1 - prob), c.PROB_DECIMALS) if is_number(prob) else None
    frame = {"market": gi.market, "as_of": as_of, "session": session, "exit": exit_day, "made": made, "range": rng,
             "edges": widened(rng, float(widen)), "widen": float(widen), "score": gi.score_for(rid, made),
             "regime": gi.regimes[as_of][0], "regime_at": gi.regimes[as_of][1],
             "features_at": feats.get("computed_at"), "quality": feats["quality"],
             "amount": gi.amounts.get(rec["ticker"]),
             "currency": gi.currency, "confidence": confidence}
    return frame, errors


def probability_errors(rec: dict, one: Trader, gi: GateInputs, frame: dict) -> list[tuple[str, str]]:
    """Direction from prob_up, the confidence band, the UNSTABLE cap and the trader's own track record."""
    prob = rec["prob_up"]
    if not is_number(prob) or not 0 < prob < 1:
        return [(c.CODE_PROBABILITY, c.MSG_PROB.format(prob=prob))]
    if abs(prob - 0.5) < 1e-9:
        return [(c.CODE_PROBABILITY, c.MSG_HALF)]
    errors = []
    if rec["direction"] != ("up" if prob > 0.5 else "down"):
        errors.append((c.CODE_PROBABILITY, c.MSG_DIRECTION.format(direction=rec["direction"], prob=prob)))
    confidence = frame["confidence"]
    if not c.CONF_MIN <= confidence <= c.CONF_MAX:
        errors.append((c.CODE_PROBABILITY, c.MSG_CONFIDENCE.format(confidence=confidence, low=c.CONF_MIN,
                                                                   high=c.CONF_MAX)))
    if frame["regime"] == c.REGIME_UNSTABLE and confidence > c.UNSTABLE_CONF_CAP + 1e-9:
        errors.append((c.CODE_PROBABILITY, c.MSG_UNSTABLE.format(confidence=confidence, cap=c.UNSTABLE_CONF_CAP)))
    closed = track_record.refusal(confidence, gi.track.get(one.strategy_id, {}))
    if closed:
        errors.append((c.CODE_TRACK, c.MSG_TRACK.format(confidence=confidence, band=closed["band"], n=closed["n"],
                                                        rate=closed["hit_rate"], low=closed["low"])))
    return errors


def number_errors(rec: dict, frame: dict) -> list[tuple[str, str]]:
    """Target inside the widened 80% range and on the call's side of C; stated edges never narrower; copies equal."""
    edges, rng, errors = frame["edges"], frame["range"], []
    for edge in EDGES:
        given = rec.get(edge)
        if given is None:
            continue
        narrower = given > float(rng[edge]) + c.PRICE_TOLERANCE if edge.startswith("lo") else \
            given < float(rng[edge]) - c.PRICE_TOLERANCE
        if not is_number(given) or narrower:
            errors.append((c.CODE_RANGE, c.MSG_NARROWED.format(edge=edge, given=given, published=rng[edge])))
        elif abs(given - edges[edge]) > c.PRICE_TOLERANCE:
            errors.append((c.CODE_NUMBERS, c.MSG_COPY.format(field=edge, given=given, stored=edges[edge])))
    target, close = rec["target_price"], float(rng["base_close"])
    if not is_number(target) or not edges["lo80"] <= target <= edges["hi80"]:
        errors.append((c.CODE_TARGET, c.MSG_TARGET_BAND.format(target=target, low=edges["lo80"], high=edges["hi80"])))
    elif (rec["direction"] == "up" and target < close) or (rec["direction"] == "down" and target > close):
        side = "at or above" if rec["direction"] == "up" else "at or below"
        errors.append((c.CODE_TARGET, c.MSG_TARGET_SIDE.format(target=target, side=side, close=close,
                                                               direction=rec["direction"])))
    return errors + copy_errors(rec, frame)


def copy_errors(rec: dict, frame: dict) -> list[tuple[str, str]]:
    """Every copied derived field equals the stored value."""
    rng, score = frame["range"], frame["score"]
    derived = {"as_of_date": str(frame["as_of"]), "session_date": str(frame["session"]),
               "exit_date": str(frame["exit"]), "base_close": float(rng["base_close"]),
               "confidence": frame["confidence"], "range_id": rng["id"],
               "model_score_id": score["id"] if score is not None else None,
               "id": prediction_id(rec["strategy_id"], frame["as_of"], rec["ticker"], rec["horizon_days"])}
    errors = []
    for name, stored in derived.items():
        if name not in rec:
            continue
        given = rec[name]
        same = abs(given - stored) <= c.PRICE_TOLERANCE if is_number(given) and is_number(stored) else given == stored
        if not same:
            errors.append((c.CODE_NUMBERS, c.MSG_COPY.format(field=name, given=given, stored=stored)))
    return errors


def reason_errors(rec: dict) -> list[tuple[str, str]]:
    """1-60 words of text."""
    text = rec["reason"]
    count = len(text.split()) if isinstance(text, str) else 0
    return [] if 1 <= count <= c.REASON_WORDS else [(c.CODE_REASON, c.MSG_REASON.format(words=c.REASON_WORDS,
                                                                                        count=count))]


def repeat_verdict(rec: dict, one: Trader, gi: GateInputs, seen: set[str]) -> Verdict | None:
    """A stored id is skipped with a warning (CLAUDE.md: skip an id that already exists, so a rerun stores nothing
    twice); an id repeated in the file is refused; else None (and the id is remembered)."""
    pid = prediction_id(one.strategy_id, gi.features[rec["ticker"]]["as_of_date"], rec["ticker"], rec["horizon_days"])
    if pid in gi.stored_predictions:
        return Verdict(None, [], [(c.CODE_STORED, c.MSG_STORED.format(id=pid))])
    if pid in seen:
        return Verdict(None, [(c.CODE_DUPLICATE, c.MSG_DUPLICATE.format(id=pid))])
    seen.add(pid)
    return None


def check_record(rec, one: Trader, gi: GateInputs, seen: set[str]) -> Verdict:
    """Gate one prediction record; `seen` collects the ids of the file so far (a repeat is refused)."""
    errors = schema_errors(rec)
    if errors:
        return Verdict(None, errors)
    errors = trader_errors(rec, one) + company_errors(rec, gi)
    if errors:
        return Verdict(None, errors)
    repeat = repeat_verdict(rec, one, gi, seen)
    if repeat is not None:
        return repeat
    frame, errors = frame_of(rec, gi)
    if frame is None:
        return Verdict(None, errors)
    errors += probability_errors(rec, one, gi, frame) + number_errors(rec, frame) + reason_errors(rec)
    warnings = []
    if frame["confidence"] is not None:
        found, warnings = evidence_errors(rec, one, gi, frame)
        news_cited = isinstance(rec["evidence_ids"], list) and any(
            not str(i).startswith(c.INPUT_PREFIXES) for i in rec["evidence_ids"])
        anchor, anchor_warnings = anchor_check(rec, one, frame, news_cited)
        errors += found + anchor
        warnings += anchor_warnings
    if errors:
        return Verdict(None, errors, warnings)
    return Verdict(prediction_row(rec, one, frame, frame["made"]), [], warnings)
