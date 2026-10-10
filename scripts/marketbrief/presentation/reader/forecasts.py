"""Per-company forecasts of the reader's report: ranges.py's published N+1/N+3/N+5 ranges of the as-of date (B12's
company_sources.published_ranges, the company page's rows, shown whatever a strategy's live_from), the signal model's
P(up) of the same as-of date (B10's scores_asof), and the change from the previous stored run (B12's
company_history.forecast_history). Every read is as of the build's cut-off (MB_NOW-aware): no look-ahead."""
from __future__ import annotations

from datetime import date

from marketbrief.analytics.horizon_records import scores_asof
from marketbrief.constants import reader as text
from marketbrief.contracts.horizons import horizons as configured_horizons
from marketbrief.presentation.reader import why
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import company_history, company_sources
from marketbrief.warehouse.rm_registry import BuildContext

PREVIOUS_AS_OF_SQL = "SELECT max(as_of_date) FROM ranges WHERE made_at <= ?::TIMESTAMPTZ AND as_of_date < ?::DATE"
PCT = 100.0


def day_label(value) -> str | None:
    """'Mon 12 Oct' for an ISO date (or date), None for None."""
    if value is None:
        return None
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{d:%a} {d.day} {d:%b}"


def shown_horizons() -> tuple[int, ...]:
    """The horizons the page shows: READER_HORIZONS among config/strategies.yaml's `horizons` (B10's list)."""
    return tuple(h for h in configured_horizons() if h in text.READER_HORIZONS)


def number(value, digits: int = 4) -> float | None:
    return json_safe_float(value, digits)


def scores_by_key(ctx: BuildContext, as_of: str) -> dict[tuple[str, int], dict]:
    """(ticker, horizon) -> the newest N+k model score of the as-of date computed by the cut-off."""
    rows = scores_asof(ctx.market, ctx.cutoff_time, con=ctx.con)
    return {(row["ticker"], int(row["horizon_days"])): row for row in rows if str(row["as_of_date"]) == as_of}


def ranges_by_key(ctx: BuildContext, as_of: str) -> dict[tuple[str, int], dict]:
    """(ticker, horizon) -> ranges.py's published range of the as-of date (the company page's row)."""
    return {(row["ticker"], int(row["horizon_days"])): row for row in company_sources.published_ranges(ctx, as_of)}


def latest_changes(ctx: BuildContext, as_of: str) -> dict[tuple[str, int], dict]:
    """(ticker, horizon) -> {range, score}: the change of the newest stored range and score run of the as-of date
    from the run before it (company_history), over the previous as-of date and this one."""
    previous = ctx.con.execute(PREVIOUS_AS_OF_SQL, [ctx.cutoff, as_of]).fetchone()[0]
    history = company_history.forecast_history(ctx, str(previous)[:10] if previous else as_of, as_of)
    out: dict[tuple[str, int], dict] = {}
    for ticker, kinds in history.items():
        for kind in ("ranges", "scores"):
            for row in kinds[kind]:   # by horizon then time: the last one per horizon is the newest
                if row["as_of_date"] == as_of:
                    out.setdefault((ticker, int(row["horizon_days"])), {})[kind] = row["change"]
    return out


def change_record(change: dict, sources: dict) -> dict | None:
    """The card's 'since the previous run' facts: target move (percent), P(up) move (fraction), news added."""
    rng, score = change.get("ranges"), change.get("scores")
    if not rng and not score:
        return None
    return {"since": (rng or {}).get("from_made_at") or (score or {}).get("from_computed_at"),
            "target_pct": None if not rng else number(rng.get("target_pct"), 2),
            "prob_pts": None if not score else number(score.get("prob_up"), 4),
            "news_added": [nid for nid in (score or {}).get("news_added") or [] if nid in sources]}


def forecast(rng: dict | None, score: dict | None, change: dict | None, horizon: int, sources: dict) -> dict:
    """One horizon of a card: expected price, 50%/80% range, P(up), lean, why, change."""
    prob = number(score.get("prob_up")) if score else None
    side, strength = why.lean(prob)
    base = number(rng.get("base_close")) if rng else None
    target = number(rng.get("target_price")) if rng else None
    return {
        "h": horizon, "name": f"N+{horizon}",
        "exit_date": str((rng or score or {}).get("exit_date") or "")[:10] or None,
        "exit_label": day_label((rng or score or {}).get("exit_date")),
        "entry_date": str((rng or score or {}).get("entry_date") or (rng or {}).get("session_date") or "")[:10] or None,
        "base_close": base, "target": target,
        "lo50": number(rng.get("lo50")) if rng else None, "hi50": number(rng.get("hi50")) if rng else None,
        "lo80": number(rng.get("lo80")) if rng else None, "hi80": number(rng.get("hi80")) if rng else None,
        "move_pct": None if not (base and target) else round((target / base - 1) * PCT, 2),
        "prob_up": prob, "base_rate": number(score.get("base_rate")) if score else None,
        "lean": side, "strength": strength, "why": why.why_line(score),
        "change": change_record(change, sources) if change else None,
    }


def company_forecasts(ctx: BuildContext, as_of: str, tickers: list[str], sources: dict) -> dict[str, list[dict]]:
    """ticker -> its forecasts at READER_HORIZONS (only horizons with a range or a score)."""
    ranges, scores, changes = ranges_by_key(ctx, as_of), scores_by_key(ctx, as_of), latest_changes(ctx, as_of)
    out: dict[str, list[dict]] = {}
    for ticker in tickers:
        rows = []
        for horizon in shown_horizons():
            key = (ticker, horizon)
            if key in ranges or key in scores:
                rows.append(forecast(ranges.get(key), scores.get(key), changes.get(key), horizon, sources))
        out[ticker] = rows
    return out


def recent_closes(ctx: BuildContext, as_of: str) -> dict[str, list[dict]]:
    """ticker -> its last HISTORY_SESSIONS split-adjusted closes up to the as-of date (the company page's bars)."""
    bars = company_sources.bar_rows(ctx.con, as_of, ctx.cutoff_time)
    return {ticker: [{"d": row["date"], "c": number(row["close"])} for row in rows[-text.HISTORY_SESSIONS:]]
            for ticker, rows in bars.items()}
