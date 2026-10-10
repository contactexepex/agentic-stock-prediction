"""The reader's report data (C2, 2026-10-10): what the 20-second top of the page and the company cards show, built
only from stored data as of the run's clock (MB_NOW-aware) through the website's own readers (B4's BuildContext and
shared blocks, B12's published ranges, bars and forecast history, B10's model scores), so the page and the website
agree. `view` is view_data.gather_view's day (session, as-of date, sources, per-company news/events/calls)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.constants import reader as text
from marketbrief.constants.verification import STATUS_CONTRADICTED
from marketbrief.constants.warehouse import DEFAULT_HORIZON
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.presentation.dashboard import reads as dashboard_reads
from marketbrief.presentation.dashboard.market import index_tile, regime_view
from marketbrief.presentation.dashboard.model_info import skill_status
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.presentation.reader import why
from marketbrief.presentation.reader.forecasts import company_forecasts, day_label, recent_closes, shown_horizons
from marketbrief.presentation.reader.paper import paper_status
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext

CONTRADICTED_SQL = """SELECT DISTINCT s.ticker FROM news_status_ids_asof($cutoff::TIMESTAMPTZ) s
JOIN (SELECT DISTINCT id FROM news_asof($cutoff::TIMESTAMPTZ) WHERE first_seen_at >= $start::TIMESTAMPTZ) n
  ON n.id = s.news_id WHERE s.status = $status ORDER BY 1"""


def contradicted_tickers(ctx: BuildContext) -> set[str]:
    """Tickers with a news item first seen in the last NEWS_LOOKBACK_DAYS whose status is contradicted (as of the
    cut-off)."""
    start = ctx.cutoff_time - timedelta(days=text.NEWS_LOOKBACK_DAYS)
    rows = ctx.con.execute(CONTRADICTED_SQL, {"cutoff": ctx.cutoff, "start": start.isoformat(),
                                              "status": STATUS_CONTRADICTED}).fetchall()
    return {row[0] for row in rows}


def glance(cards: list[dict]) -> dict[str, dict]:
    """Per horizon: how many companies lean up, down or neither, and the biggest expected moves (ticker list)."""
    out = {}
    for horizon in shown_horizons():
        counts = {text.LEAN_UP: 0, text.LEAN_DOWN: 0, text.LEAN_NONE: 0, "no_score": 0}
        moves = []
        for card in cards:
            row = next((f for f in card["forecasts"] if f["h"] == horizon), None)
            if row is None or row["prob_up"] is None:
                counts["no_score"] += 1
            else:
                counts[row["lean"]] += 1
            if row is not None and row["move_pct"]:   # a 0% move is no "move"
                moves.append((abs(row["move_pct"]), card["ticker"]))
        moves.sort(key=lambda m: (-m[0], m[1]))
        out[str(horizon)] = {**counts, "moves": [ticker for _, ticker in moves[:text.TOP_MOVES]]}
    return out


def changes(cards: list[dict], sources: dict, statuses: EvidenceStatuses, cutoff: datetime) -> dict:
    """What changed since the previous run: per horizon the biggest target or P(up) moves, and the news items newly
    counted by the model (any horizon), each with its verification status as of the cut-off."""
    per_h = {}
    for horizon in shown_horizons():
        rows = []
        for card in cards:
            row = next((f for f in card["forecasts"] if f["h"] == horizon), None)
            change = (row or {}).get("change") or {}
            target, prob = change.get("target_pct"), change.get("prob_pts")
            if (target is not None and abs(target) >= text.CHANGE_MIN_TARGET_PCT) or \
                    (prob is not None and abs(prob) >= text.CHANGE_MIN_PROB_PTS):
                rows.append({"ticker": card["ticker"], "target_pct": target, "prob_pts": prob})
        rows.sort(key=lambda r: (-abs(r["target_pct"] or 0), -abs(r["prob_pts"] or 0), r["ticker"]))
        per_h[str(horizon)] = rows[:text.TOP_CHANGES]
    news, seen = [], set()
    for card in cards:
        for row in card["forecasts"]:
            for nid in ((row.get("change") or {}).get("news_added") or []):
                if (card["ticker"], nid) in seen:
                    continue
                seen.add((card["ticker"], nid))
                src = sources[nid]
                news.append({"ticker": card["ticker"], "id": nid, "title": src.get("title"), "url": src.get("url"),
                             "source": src.get("source"), "ts": src.get("ts"),
                             "status": statuses.of(nid, card["ticker"], cutoff)})
    news.sort(key=lambda n: (n["ts"] or "", n["id"]), reverse=True)
    since = sorted({(r.get("change") or {}).get("since") for c in cards for r in c["forecasts"]} - {None})
    return {"by_horizon": per_h, "news": news[:text.NEW_NEWS_LIMIT], "news_total": len(news),
            "since": since[-1] if since else None}


def market_blocks(ctx: BuildContext, as_of: str) -> dict:
    """The regime in plain words, the benchmark and volatility index (last close, 1-day and 5-session change) and
    the paper label (the latest weekly review's model_skill), as of the cut-off, with the dashboard's own readers
    (the same values as the website's Market status block, rm_common.status_block)."""
    day = date.fromisoformat(as_of)
    regime = regime_view(dashboard_reads.regime(ctx.con, day, ctx.cutoff))
    bars = dashboard_reads.bars(ctx.con, day, day - timedelta(days=text.INDEX_LOOKBACK_DAYS), ctx.cutoff)
    level = lambda key: rm_common.level_block(index_tile(ctx.cfg, key, bars))  # noqa: E731
    mood = None if regime is None else {
        "code": regime["code"], "word": text.MOOD_WORDS.get(regime["code"], regime["code"].replace("_", " ").title()),
        "plain": regime["plain"], "stress": regime["stress"]}
    return {"mood": mood, "benchmark": level(benchmark_key(ctx.cfg)), "vol_index": level(vol_index_key(ctx.cfg)),
            "paper_label": skill_status(dashboard_reads.review(ctx.con, ctx.cutoff))["label"]}


def reader_data(cfg: dict, con, cutoff_time: datetime, view: dict) -> dict:
    """The reader block embedded in the page next to the view (see the module docstring)."""
    ctx = BuildContext(cfg, con, cutoff_time)
    as_of, shown = view["as_of"], shown_horizons()
    by_ticker = {c["ticker"]: c for c in view["companies"]}
    active = [t for t in by_ticker if t in ctx.active]
    forecasts = company_forecasts(ctx, as_of, active, view["sources"])
    closes = recent_closes(ctx, as_of)
    contradicted = contradicted_tickers(ctx)
    cards = []
    for ticker in active:
        company = by_ticker[ticker]
        cards.append({"ticker": ticker, "bars": closes.get(ticker, []), "forecasts": forecasts.get(ticker, []),
                      "flags": why.flags(company.get("quality"), company.get("days_to_earnings"),
                                         ticker in contradicted)})
    statuses = EvidenceStatuses(con)
    return {
        "horizons": list(shown),
        "default_horizon": DEFAULT_HORIZON if DEFAULT_HORIZON in shown else (shown[0] if shown else None),
        "lean": {"slight": text.LEAN_SLIGHT, "clear": text.LEAN_CLEAR},
        "cutoff": cutoff_time.replace(microsecond=0).isoformat(),
        "as_of": as_of, "as_of_label": day_label(as_of),
        **market_blocks(ctx, as_of),
        "companies": cards,
        "glance": glance(cards),
        "changes": changes(cards, view["sources"], statuses, cutoff_time),
        "paper": paper_status(ctx, view["session"], set(active)),
    }
