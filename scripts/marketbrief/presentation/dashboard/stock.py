"""One ticker's part of the dashboard data: bars, the last session's open/close/gap, the published
ranges with risk/reward, the model score with its explanation, the forecaster's bull and bear cases,
headlines with their verification status, the next earnings date and the indicators. Every number is
copied from a stored row; the only arithmetic is plain ratios of stored prices (gap, change, distance
to a range edge), each named for what it is."""

from __future__ import annotations

import json
import re

import pandas as pd

from marketbrief.constants.dashboard import INDICATOR_COLUMNS, NEWS_PER_TICKER
from marketbrief.constants.model import GROUP_BASELINE
from marketbrief.utils.numbers import json_safe_float

PRICE_DIGITS = 4


def iso_day(value) -> str | None:
    """A date as YYYY-MM-DD, None when missing."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return pd.Timestamp(value).date().isoformat()


def iso_time(value) -> str | None:
    """A timestamp as ISO text, None when missing."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return pd.Timestamp(value).isoformat()


def as_list(value) -> list:
    """A stored list column as a plain list (None and NaN -> [])."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [x for x in list(value) if x is not None]


def ratio(numerator, denominator) -> float | None:
    """numerator / denominator - 1, None when either is missing or the denominator is 0."""
    a, b = json_safe_float(numerator), json_safe_float(denominator)
    return None if a is None or not b else a / b - 1


def bar_rows(ticker_bars: pd.DataFrame) -> list[list]:
    """[date, open, high, low, close, volume] per bar, oldest first."""
    return [
        [
            iso_day(b.date),
            json_safe_float(b.open, PRICE_DIGITS),
            json_safe_float(b.high, PRICE_DIGITS),
            json_safe_float(b.low, PRICE_DIGITS),
            json_safe_float(b.close, PRICE_DIGITS),
            None if pd.isna(b.volume) else int(b.volume),
        ]
        for b in ticker_bars.itertuples()
    ]


def last_session(rows: list[list]) -> dict | None:
    """The newest bar's open, close and range, the previous close, the overnight gap (open vs previous
    close), the open-to-close move and the close-to-close change."""
    if not rows:
        return None
    day, open_, high, low, close, volume = rows[-1]
    prev_close = rows[-2][4] if len(rows) > 1 else None
    return {
        "date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "prev_close": prev_close,
        "gap": ratio(open_, prev_close),
        "open_to_close": ratio(close, open_),
        "change": ratio(close, prev_close),
    }


def range_rows(ticker_ranges: pd.DataFrame, late_of) -> list[dict]:
    """The published 50%/80% ranges per horizon, with the distance from the base close to each 80% edge."""
    out = []
    for r in ticker_ranges.sort_values("horizon_days").itertuples():
        base = json_safe_float(r.base_close)
        up, down = ratio(r.hi80, base), ratio(r.lo80, base)
        out.append(
            {
                "h": int(r.horizon_days),
                "target_date": iso_day(r.target_date),
                "made_at": iso_time(r.made_at),
                "base_close": base,
                "lo50": json_safe_float(r.lo50),
                "hi50": json_safe_float(r.hi50),
                "lo80": json_safe_float(r.lo80),
                "hi80": json_safe_float(r.hi80),
                "up80": up,
                "down80": down,
                "reward_risk": (up / -down) if up is not None and down is not None and down < 0 else None,
                "late": bool(late_of(r.as_of_date, r.made_at)),
                "notes": as_list(r.notes),
            }
        )
    return out


def group_points(groups: dict) -> list[dict]:
    """Feature-group points (percentage points of P(up)) without the baseline, largest first."""
    rows = [{"group": g, "points": json_safe_float(v)} for g, v in groups.items() if g != GROUP_BASELINE]
    return sorted(rows, key=lambda r: (-abs(r["points"] or 0.0), r["group"]))


def model_row(score, exits: dict) -> dict:
    """One horizon's model score with its explanation, as stored (model_scores contributions)."""
    explanation = (
        json.loads(score.contributions) if isinstance(score.contributions, str) else (score.contributions or {})
    )
    groups = explanation.get("groups") or {}
    news = explanation.get("news") or {}
    h = int(score.horizon_days)
    return {
        "h": h,
        "id": score.id,
        "prob_up": json_safe_float(score.prob_up),
        "prob_model": json_safe_float(score.prob_model),
        "base_rate": json_safe_float(score.base_rate),
        "calibrated": bool(score.calibrated),
        "label": score.label_convention,
        "model_id": score.model_id,
        "trained_until": iso_day(score.trained_until),
        "computed_at": iso_time(score.computed_at),
        "baseline_points": json_safe_float(groups.get(GROUP_BASELINE)),
        "groups": group_points(groups),
        "up": explanation.get("up") or [],
        "down": explanation.get("down") or [],
        "missing": explanation.get("missing") or [],
        "news_note": news.get("note"),
        "news_items": news.get("items"),
        "entry": exits.get("entry"),
        "exit": exits.get(h),
    }


def indicator_values(feature_row) -> dict:
    """The stored indicators of the as-of snapshot."""
    if feature_row is None:
        return {}
    out = {c: json_safe_float(feature_row.get(c)) for c in INDICATOR_COLUMNS}
    out["quality"] = feature_row.get("quality")
    dte = feature_row.get("days_to_earnings")
    out["days_to_earnings"] = None if dte is None or pd.isna(dte) else int(dte)
    out["warnings"] = as_list(feature_row.get("warnings"))
    return out


def same_story_key(title: str | None) -> str:
    """Lower-case words of a title: the same story from two feeds is shown once."""
    return re.sub(r"\W+", " ", (title or "").lower()).strip()


def news_rows(ticker_news: pd.DataFrame, status_of, safe_url) -> list[dict]:
    """The newest headlines (same-title copies once) with their verification status as of the cut-off."""
    seen, out = set(), []
    for n in ticker_news.itertuples():
        key = same_story_key(n.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": n.id,
                "title": n.title,
                "url": safe_url(n.url),
                "source": n.source,
                "ts": iso_time(n.ts),
                "status": status_of(n.id),
            }
        )
        if len(out) >= NEWS_PER_TICKER:
            break
    return out


def reasoning_ids(row, id_pattern) -> list[str]:
    """The evidence ids of a reasoning row plus every id its texts name, in order, once."""
    ids = as_list(row.get("evidence_ids"))
    for text in (row.get("bull_case"), row.get("bear_case"), row.get("verdict")):
        ids += id_pattern.findall(text or "")
    return list(dict.fromkeys(ids))


def reasoning_view(row, cited: dict, id_pattern) -> dict | None:
    """The forecaster's bull case, bear case, verdict and decisions, with the cited ids it names."""
    if row is None:
        return None
    ids = reasoning_ids(row, id_pattern)
    return {
        "bull": row.get("bull_case"),
        "bear": row.get("bear_case"),
        "verdict": row.get("verdict"),
        "decision_1d": row.get("decision_1d"),
        "decision_5d": row.get("decision_5d"),
        "made_at": iso_time(row.get("made_at")),
        "prompt_version": row.get("prompt_version"),
        "evidence": [{"id": i, **cited[i]} for i in ids if i in cited],
    }


def call_rows(ticker_predictions: pd.DataFrame) -> list[dict]:
    """The forecaster's stored calls (direction and stated confidence) per horizon."""
    return [
        {
            "h": int(p.horizon_days),
            "direction": p.direction,
            "confidence": json_safe_float(p.confidence),
            "made_at": iso_time(p.made_at),
        }
        for p in ticker_predictions.sort_values("horizon_days").itertuples()
    ]
