"""The weekly research director's inputs (docs/SPEC.md F6.2), as of the run's clock (Saturday 10:00 local).

The week = the ISO week of the last completed session (Monday to Sunday dates). Inputs, each with the ids the
director may cite:
- leaders: per family (rule, baseline, ai) the strategies ranked by net P&L after costs on their accuracy-view trades
  settled by now, to date and this week (deterministic; the full scoreboard with the luck test is session B2's);
- news_impact rows of the week (F3, written by B2's weekly study; "not enough events yet" rows included);
- the week's eod_analyses and trade_reasons_ai, and the lessons written in the week;
- the registry (strategy ids and their live_from) and the text of each config file a proposal may change."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.core import paths
from marketbrief.traders.constants import PROPOSAL_FILES
from marketbrief.traders.registry import load_registry
from marketbrief.traders.settle_step import records

LEADERS_SQL = """
SELECT t.family, t.strategy_id, count(*) AS trades, round(sum(t.net_pnl), 2) AS net_pnl,
       sum(CASE WHEN t.net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
       round(sum(t.net_pnl) / nullif(sum(t.amount), 0) * 100, 2) AS return_pct
FROM paper_trades_settled t
WHERE t.view = 'accuracy' AND t.status = 'settled' AND t.settled_at <= ?::TIMESTAMPTZ
  AND t.exit_date_actual BETWEEN ?::DATE AND ?::DATE
  AND NOT EXISTS (SELECT 1 FROM paper_trades_settled s WHERE s.supersedes = t.id AND s.settled_at <= ?::TIMESTAMPTZ)
GROUP BY t.family, t.strategy_id ORDER BY t.family, net_pnl DESC, trades DESC, t.strategy_id"""
WEEK_SQL = {
    "news_impact": "SELECT * FROM news_impact WHERE iso_week = ? AND computed_at <= ?::TIMESTAMPTZ ORDER BY id",
    "eod_analyses": "SELECT * FROM eod_analyses WHERE session_date BETWEEN ?::DATE AND ?::DATE "
                    "AND created_at <= ?::TIMESTAMPTZ ORDER BY id",
    "trade_reasons_ai": "SELECT * FROM trade_reasons_ai WHERE session_date BETWEEN ?::DATE AND ?::DATE "
                        "AND created_at <= ?::TIMESTAMPTZ ORDER BY id",
    "lessons": "SELECT * FROM lessons WHERE CAST(written_at AS DATE) BETWEEN ?::DATE AND ?::DATE "
               "AND written_at <= ?::TIMESTAMPTZ ORDER BY id",
}
EPOCH = date(2000, 1, 1)


def iso_week(day: date) -> tuple[str, date, date]:
    """('2026-W41', Monday, Sunday) of a day."""
    year, week, weekday = day.isocalendar()
    monday = day - timedelta(days=weekday - 1)
    return f"{year}-W{week:02d}", monday, monday + timedelta(days=6)


def plain(rows: list[dict]) -> list[dict]:
    """Dates and timestamps as ISO text (JSON-ready)."""
    return [{key: value.isoformat() if isinstance(value, (date, datetime)) else value for key, value in row.items()}
            for row in rows]


def leaders(con, start: date, end: date, now: datetime) -> list[dict]:
    """Per family and strategy: trades, wins, net P&L and return % of the accuracy trades that exited in the window."""
    stamp = now.isoformat()
    return plain(records(con, LEADERS_SQL, [stamp, start.isoformat(), end.isoformat(), stamp]))


def director_facts(con, market: str, last_session: date, now: datetime) -> dict:
    """Everything the director reads and may cite."""
    week, monday, sunday = iso_week(last_session)
    stamp = now.isoformat()
    window = [monday.isoformat(), sunday.isoformat(), stamp]
    registry = load_registry()
    return {
        "id": f"rr-{market}-{week}", "market": market, "iso_week": week, "period_start": monday.isoformat(),
        "period_end": sunday.isoformat(), "as_of": stamp,
        "leaders_to_date": leaders(con, EPOCH, sunday, now), "leaders_week": leaders(con, monday, sunday, now),
        "news_impact": plain(records(con, WEEK_SQL["news_impact"], [week, stamp])),
        "eod_analyses": plain(records(con, WEEK_SQL["eod_analyses"], window)),
        "trade_reasons_ai": plain(records(con, WEEK_SQL["trade_reasons_ai"], window)),
        "lessons": plain(records(con, WEEK_SQL["lessons"], window)),
        "strategies": [{"id": s["id"], "family": s["family"], "threshold": s["threshold"],
                        "live_from": s["live_from"]} for s in registry["strategies"]],
        "config_files": {name: (paths.CODE / name).read_text(encoding="utf-8") for name in PROPOSAL_FILES},
    }


def citable(facts: dict) -> dict[str, dict]:
    """Every id the director may cite -> the record it names (its numbers may be quoted)."""
    out: dict[str, dict] = {}
    for kind in ("news_impact", "eod_analyses", "trade_reasons_ai", "lessons"):
        for row in facts[kind]:
            out[row["id"]] = row
    for scope in ("leaders_to_date", "leaders_week"):
        for row in facts[scope]:
            out.setdefault(row["strategy_id"], {}).update({f"{scope}.{k}": v for k, v in row.items()})
    for row in facts["strategies"]:
        out.setdefault(row["id"], {}).update({"threshold": row["threshold"]})
    return out
