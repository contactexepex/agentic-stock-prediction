"""Paper-follow: a deterministic SIMULATION of "what if I had followed every Paper candidate" on stored bars.

For each of the last paper_follow.lookback_sessions as-of dates with model scores: the score of each id is the
newest computed before the open of D (D = the first session after the as-of date), the candidates are picked as
signals.candidates picks them (the farthest model_prob from 0.5, tiers.max_candidates, minus BLOCKED quality or
earnings within earnings_block_days by the feature row of that as-of date computed before the open of D). Each is
simulated open-to-close: entry at the open of D, exit at the close of the k-th session after D (N+k, decision
37; a legacy 5-day score without horizon_label: D+4), prices on today's split basis, the round-trip cost of
config/costs.yaml at the entry open. Up candidates are simulated long (net = return - cost); down candidates as
"sell if held" (avoided = -return, net of a round trip),
reported apart, never pooled. A candidate whose exit bar is not stored by the clock is pending, not scored."""
from __future__ import annotations

import pandas as pd

from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE
from marketbrief.core.calendar import next_session, session_open_utc
from marketbrief.lab.timing import exit_session, sessions_after_d
from marketbrief.model.settings import round_trip_cost
from marketbrief.portfolio import reads
from marketbrief.portfolio.constants import SIMULATED_LABEL
from marketbrief.portfolio.horizons import label_sql
from marketbrief.portfolio.signals import blocked_reason

PERCENT = 100.0


def scores_before_open(con, cfg: dict, clock) -> tuple[pd.DataFrame, int]:
    """(per id, the newest score computed before the open of its D and by the clock; the number of ids whose
    every score came at or after that open, left out)."""
    frame = con.execute(f"SELECT id, as_of_date, ticker, horizon_days, {label_sql(con, 'model_scores')}, prob_up, "
                        "computed_at FROM model_scores "
                        "WHERE computed_at <= ? ORDER BY id, computed_at DESC, prob_up", [clock]).df()
    if frame.empty:
        return frame, 0
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    opens = {day: session_open_utc(cfg, next_session(cfg, day, include=False)) for day in frame["as_of_date"].unique()}
    frame["entry_open_at"] = frame["as_of_date"].map(opens)
    ids = frame["id"].nunique()
    frame = frame[pd.to_datetime(frame["computed_at"], utc=True) < pd.to_datetime(frame["entry_open_at"], utc=True)]
    frame = frame.drop_duplicates("id", keep="first").reset_index(drop=True)
    return frame, ids - len(frame)


def blocks_before_open(con, as_of, before, clock) -> dict[str, dict]:
    """{ticker: quality and days_to_earnings} of the as-of date's newest feature row computed before `before`
    and by the clock."""
    frame = con.execute("SELECT DISTINCT ON (ticker) ticker, quality, days_to_earnings FROM features "
                        "WHERE as_of_date = ? AND computed_at < ? AND computed_at <= ? "
                        "ORDER BY ticker, computed_at DESC", [as_of, before, clock]).df()
    return {row["ticker"]: row for row in frame.to_dict("records")}


def picks(con, scores: pd.DataFrame, settings: dict, clock) -> pd.DataFrame:
    """The candidates of each as-of date (see the module docstring)."""
    chosen = []
    for as_of, rows in scores.groupby("as_of_date"):
        blocks = blocks_before_open(con, as_of, rows["entry_open_at"].iloc[0], clock)
        open_ = pd.Series([blocked_reason(blocks.get(t), settings) is None for t in rows["ticker"]], index=rows.index)
        rows = rows[open_ & (rows["prob_up"] != 0.5)]
        rows = rows.assign(distance=(rows["prob_up"] - 0.5).abs())
        rows = rows.sort_values(["distance", "ticker", "horizon_days"], ascending=[False, True, True])
        chosen.append(rows.head(settings["tiers"]["max_candidates"]))
    return pd.concat(chosen, ignore_index=True) if chosen else scores.iloc[0:0]


def simulate(con, cfg: dict, clock, market: str, settings: dict, costs: dict) -> dict:
    """The simulated paper-follow result (positions, and per side the counts and mean returns in %)."""
    scores, late = scores_before_open(con, cfg, clock)
    if scores.empty:
        return {"label": SIMULATED_LABEL, "market": market, "as_of": clock.isoformat(), "positions": [], "sides": {},
                "late_scores": late}
    dates = sorted(scores["as_of_date"].unique())[-settings["paper_follow"]["lookback_sessions"]:]
    chosen = picks(con, scores[scores["as_of_date"].isin(dates)], settings, clock)
    bars = reads.stored_bars(con, cfg, clock, sorted(chosen["ticker"].unique()), min(dates))
    bar_index = {(row["ticker"], row["date"]): row for row in bars.to_dict("records")}
    adjust = reads.adjustments(con, clock)
    rows = [position(row, cfg, bar_index, adjust, market, costs) for row in chosen.to_dict("records")]
    return {"label": SIMULATED_LABEL, "market": market, "as_of": clock.isoformat(), "basis": LABEL_OPEN_TO_CLOSE,
            "as_of_dates": [str(dates[0]), str(dates[-1])], "late_scores": late, "positions": rows,
            "sides": {side: side_summary([r for r in rows if r["direction"] == side]) for side in ("up", "down")}}


def position(row: dict, cfg: dict, bar_index: dict, adjust, market: str, costs: dict) -> dict:
    """One simulated position: entry open of D, exit close of the k-th session after D for N+k (a legacy 5-day
    score without horizon_label: D+4); None while pending."""
    entry_day = next_session(cfg, row["as_of_date"], include=False)
    label = row.get("horizon_label")
    days = [entry_day, exit_session(cfg, entry_day, sessions_after_d(int(row["horizon_days"]),
                                                                     None if pd.isna(label) else label))]
    entry, exit_ = bar_index.get((row["ticker"], days[0])), bar_index.get((row["ticker"], days[-1]))
    side = "up" if row["prob_up"] > 0.5 else "down"
    out = {"id": row["id"], "ticker": row["ticker"], "horizon_days": int(row["horizon_days"]), "direction": side,
           "model_prob": round(float(row["prob_up"]), 4), "entry_date": str(days[0]), "exit_date": str(days[-1]),
           "ret_pct": None, "net_pct": None, "status": "pending"}
    if entry is None or exit_ is None or entry["open"] is None or entry["open"] != entry["open"]:
        return out
    entry_open = float(entry["open"]) * reads.factor_after(adjust, row["ticker"], days[0])
    exit_close = float(exit_["close"]) * reads.factor_after(adjust, row["ticker"], days[-1])
    ret = exit_close / entry_open - 1
    cost = round_trip_cost(market, costs, float(entry["open"]))
    signed = ret if side == "up" else -ret
    out.update(ret_pct=round(ret * PERCENT, 4), net_pct=round((signed - cost) * PERCENT, 4),
               cost_pct=round(cost * PERCENT, 4), hit=bool(signed > 0), status="scored")
    return out


def side_summary(rows: list[dict]) -> dict:
    """Counts, hit rate and mean net % per position and per as-of date of one side's scored positions."""
    scored = [row for row in rows if row["status"] == "scored"]
    out = {"positions": len(rows), "scored": len(scored), "pending": len(rows) - len(scored)}
    if not scored:
        return {**out, "hit_rate": None, "mean_net_pct": None, "mean_net_per_date_pct": None}
    frame = pd.DataFrame(scored)
    frame["as_of"] = frame["id"].str[:10]
    per_date = frame.groupby("as_of")["net_pct"].mean()
    return {**out, "hit_rate": round(float(frame["hit"].mean()), 4),
            "mean_net_pct": round(float(frame["net_pct"].mean()), 4),
            "dates": int(len(per_date)), "mean_net_per_date_pct": round(float(per_date.mean()), 4)}
