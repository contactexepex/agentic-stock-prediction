"""The company pages' payloads (B12; docs/ws/b12.md): pure slicing of one market's records as of the cut-off
(warehouse/company_sources.CompanySources) per company, in the mockups' field lists and orders
(design/mockups/03-company/notes.md, 04-stock-strategies/notes.md). The builders are rm_company.py's."""
from __future__ import annotations

from marketbrief.constants.rm_company import (ALL_HORIZONS, BAR_FIELDS, CALENDAR_FIELDS, CHECK_FIELDS,
                                              COMPANY_ROW_FIELDS, DIGEST_FIELDS, ENRICHMENT_FIELDS,
                                              EVENT_TYPE_HOLIDAY, HEADLINE_FIELDS, LIFECYCLE_FIELDS, NEWS_FIELDS,
                                              OPEN_TRADE_FIELDS, PICK_FIELDS, PREDICTION_FIELDS, PUBLISHED_RANGE_FIELDS,
                                              REASON_DETAIL_FIELDS,
                                              REASON_FIELDS, SCOPE_STRATEGY, SCOPE_STRATEGY_COMPANY,
                                              SCOREBOARD_FIELDS, SETTLED_FIELDS, STRATEGIES_PICK_FIELDS,
                                              STRATEGIES_PREDICTION_FIELDS)
from marketbrief.lab.constants import VIEW_ACCURACY
from marketbrief.warehouse.company_sources import CompanySources


def pick(record: dict, fields: tuple[str, ...]) -> dict:
    """The listed fields of a record (a field the record lacks is null)."""
    return {name: record.get(name) for name in fields}


def lifecycle_rows(sources: CompanySources, ticker: str) -> list[dict]:
    """The company's watchlist events recorded by the cut-off, oldest first."""
    return [pick(row, LIFECYCLE_FIELDS) for row in sources.lifecycle.get(ticker, [])]


def bar_rows(sources: CompanySources, ticker: str) -> list[dict]:
    """The company's stored sessions up to the as-of date, oldest first."""
    return [pick(row, BAR_FIELDS) for row in sources.bars.get(ticker, [])]


def bars_payload(sources: CompanySources, ticker: str) -> dict:
    """rm.bars of one company."""
    return {"market": sources.market, "ticker": ticker, "as_of": sources.as_of, "bars": bar_rows(sources, ticker)}


def range_rows(sources: CompanySources, ticker: str) -> list[dict]:
    """The company's published ranges of the as-of date (ranges.py), by horizon."""
    rows = [pick(row, PUBLISHED_RANGE_FIELDS) for row in sources.ranges.get(ticker, [])]
    return sorted(rows, key=lambda row: row["horizon_days"])


def open_trade_rows(open_trades: list[dict]) -> list[dict]:
    """Open trades (the shared derivation) in page order: horizon, then trade id."""
    rows = [pick(row, OPEN_TRADE_FIELDS) for row in open_trades]
    return sorted(rows, key=lambda row: (row["ticker"], row["horizon_days"], row["trade_id"]))


def check_rows(checks: list[dict]) -> list[dict]:
    """Trade checks by ticker, then trade id."""
    return sorted((pick(row, CHECK_FIELDS) for row in checks), key=lambda row: (row["ticker"], row["trade_id"]))


def present(record: dict | None, fields: tuple[str, ...]) -> dict | None:
    """The listed keys a nested record holds (a skipped settlement's reason_detail holds only its note)."""
    return None if record is None else {name: record[name] for name in fields if name in record}


def settled_rows(settled: list[dict]) -> list[dict]:
    """Settled paper trades (every status; the page counts the skipped ones), newest exit first."""
    rows = [{**pick(row, SETTLED_FIELDS), "reason_detail": present(row.get("reason_detail"), REASON_DETAIL_FIELDS)}
            for row in settled]
    return sorted(rows, key=lambda row: (row["exit_date_actual"] or row["exit_date"], row["entry_date"],
                                         row["trade_id"]), reverse=True)


def reason_rows(reasons: list[dict]) -> list[dict]:
    """AI reasons, newest session first."""
    rows = [pick(row, REASON_FIELDS) for row in reasons]
    return sorted(rows, key=lambda row: (row["session_date"], row["kind"], row["rank"] or 0, row["id"]), reverse=True)


def trade_lists(sources: CompanySources, ticker: str, open_trades: list[dict]) -> dict:
    """The company's open trades (`open_trades`: the shared derivation's rows of this company), latest trade checks,
    settled trades and AI reasons."""
    return {"open_trades": open_trade_rows(open_trades),
            "trade_checks": check_rows(sources.checks.get(ticker, [])),
            "settled": settled_rows(sources.settled.get(ticker, [])),
            "reasons": reason_rows(sources.reasons.get(ticker, []))}


def exit_day(row: dict) -> str:
    """The session a settled trade exited (its actual exit, else the planned one)."""
    return row["exit_date_actual"] or row["exit_date"]


def since(rows: list[dict], first_day: str | None, day_of) -> list[dict]:
    """The rows whose day (`day_of`) is on or after `first_day` (all rows when None)."""
    return rows if first_day is None else [row for row in rows if day_of(row) >= first_day]


def trades_payload(sources: CompanySources, ticker: str, open_trades: list[dict], first_day: str | None) -> dict:
    """rm.trades of one company: its open trades and latest checks, and the settled trades and AI reasons of the
    sessions from `first_day` (docs/SPEC.md section 4: the last 60 sessions)."""
    lists = trade_lists(sources, ticker, open_trades)
    return {"market": sources.market, "ticker": ticker, "as_of": sources.as_of, **lists,
            "settled": since(lists["settled"], first_day, exit_day),
            "reasons": since(lists["reasons"], first_day, lambda row: row["session_date"])}


def market_trades_payload(sources: CompanySources, open_trades: list[dict], first_day: str | None) -> dict:
    """rm.trades page_key _: every open trade of the market, the rows of the market's latest check and the settled
    trades that exited from `first_day` (docs/SPEC.md section 4: the last 5 sessions), newest exit first."""
    settled = [row for rows in sources.settled.values() for row in rows]
    return {"market": sources.market, "as_of": sources.as_of, "open_trades": open_trade_rows(open_trades),
            "trade_checks": check_rows(sources.market_checks),
            "settled": since(settled_rows(settled), first_day, exit_day)}


def lifecycle_payload(sources: CompanySources, ticker: str, day: str) -> dict:
    """rm.lifecycle `<ticker>:<day>`: the path of the company's predictions made for session `day` (docs/SPEC.md
    section 2 "Lifecycle of a prediction", docs/DATA_CATALOGUE.md: made -> checks -> settled -> explained): the
    strategy predictions and head-to-head picks made for the session, every intraday trade check of those
    predictions' trades on any session so far, their settled trades and the AI reasons about those trades, as stored
    by the cut-off."""
    predictions = [row for row in sources.all_predictions.get(ticker, []) if row["session_date"] == day]
    picks = [row for row in sources.all_picks.get(ticker, []) if row["session_date"] == day]
    made = {row["id"] for row in predictions} | {row["prediction_id"] for row in picks if row.get("prediction_id")}
    checks = [row for row in sources.all_checks.get(ticker, []) if row.get("prediction_id") in made]
    settled = [row for row in settled_rows(sources.settled.get(ticker, [])) if row["prediction_id"] in made]
    trades = {row["trade_id"] for row in checks} | {row["trade_id"] for row in settled}
    return {
        "market": sources.market,
        "ticker": ticker,
        "session_date": day,
        "predictions": sorted((pick(row, PREDICTION_FIELDS) for row in predictions),
                              key=lambda row: (row["strategy_id"], row["horizon_days"])),
        "head_to_head": sorted((pick(row, PICK_FIELDS) for row in picks),
                               key=lambda row: (row["family"], row["pick_rule"])),
        "trade_checks": sorted((pick(row, CHECK_FIELDS) for row in checks),
                               key=lambda row: (row["check_at"], row["trade_id"])),
        "settled": settled,
        "reasons": [row for row in reason_rows(sources.reasons.get(ticker, [])) if row["trade_id"] in trades],
    }


def pick_rows(sources: CompanySources, ticker: str, fields: tuple[str, ...]) -> list[dict]:
    """The company's head-to-head picks for the session being predicted, by family then pick rule."""
    return sorted((pick(row, fields) for row in sources.picks.get(ticker, [])),
                  key=lambda row: (row["family"], row["pick_rule"]))


def prediction_rows(sources: CompanySources, ticker: str, fields: tuple[str, ...]) -> list[dict]:
    """The company's strategy predictions of the as-of date, by strategy then horizon."""
    return sorted((pick(row, fields) for row in sources.predictions.get(ticker, [])),
                  key=lambda row: (row["strategy_id"], row["horizon_days"]))


def scoreboard_rows(sources: CompanySources, scope: str, ticker: str | None, fields: tuple[str, ...],
                    all_horizons_only: bool) -> list[dict]:
    """Accuracy-view scoreboard rows of a scope (the company's for strategy_company), by strategy then horizon."""
    rows = [pick(row, fields) for row in sources.scoreboard
            if row["scope"] == scope and row["view"] == VIEW_ACCURACY and row.get("ticker") == ticker
            and (not all_horizons_only or row["horizon_days"] == ALL_HORIZONS)]
    return sorted(rows, key=lambda row: (row["strategy_id"], str(row["horizon_days"])))


def news_row(item: dict) -> dict:
    """A news item with the fields the company page carries."""
    return {**pick(item, NEWS_FIELDS),
            "enrichment": None if item.get("enrichment") is None else pick(item["enrichment"], ENRICHMENT_FIELDS),
            "headline_history": [pick(entry, HEADLINE_FIELDS) for entry in item.get("headline_history") or []]}


def company_news(news: list[dict]) -> list[dict]:
    """B11's news items of the company (status as of the company), newest first."""
    return sorted((news_row(row) for row in news),
                  key=lambda row: (row["published_at"] or row["first_seen_at"], row["id"]), reverse=True)


def company_events(events: list[dict], ticker: str) -> list[dict]:
    """From the session being predicted: the company's own events, the market's major events and closed days."""
    rows = [pick(row, CALENDAR_FIELDS) for row in events
            if row.get("ticker") == ticker
            or (row.get("ticker") is None and (row.get("major") or row.get("type") == EVENT_TYPE_HOLIDAY))]
    return sorted(rows, key=lambda row: (row["date"], row["type"], row["name"]))


def digest_rows(sources: CompanySources, ticker: str) -> list[dict]:
    """The company's results digests, newest release first."""
    return sorted((pick(row, DIGEST_FIELDS) for row in sources.digests.get(ticker, [])),
                  key=lambda row: (row["release_at"], row["id"]), reverse=True)


def stock_payload(sources: CompanySources, ticker: str, shared: dict, blocks: dict) -> dict:
    """rm.stock of one company, the whole 03 page: `shared` = the market blocks (header, status, horizons,
    default_horizon, reference_strategy, go_live, strategies, companies); `blocks` = the company's shared records:
    `company` its Company record, `agreement` its rows per horizon ("1".."5"), `open_trades` its open trades, `news`
    B11's items about it, `events` B11's calendar from the session being predicted."""
    return {
        **shared,
        "ticker": ticker,
        "company": blocks["company"],
        "lifecycle": lifecycle_rows(sources, ticker),
        "agreement": blocks["agreement"],
        "head_to_head": pick_rows(sources, ticker, PICK_FIELDS),
        "predictions": prediction_rows(sources, ticker, PREDICTION_FIELDS),
        "published_ranges": range_rows(sources, ticker),
        **trade_lists(sources, ticker, blocks["open_trades"]),
        "news": company_news(blocks["news"]),
        "results": digest_rows(sources, ticker),
        "events": company_events(blocks["events"], ticker),
        "bars": bar_rows(sources, ticker),
        "on_company": scoreboard_rows(sources, SCOPE_STRATEGY_COMPANY, ticker, COMPANY_ROW_FIELDS, True),
    }


def stock_strategies_payload(sources: CompanySources, ticker: str, shared: dict, blocks: dict) -> dict:
    """rm.stock_strategies of one company: `shared` = the market blocks (header, status, horizons, default_horizon,
    go_live, strategies with their descriptions and parameters); `blocks` = its `company` and `agreement`."""
    return {
        **shared,
        "ticker": ticker,
        "company": blocks["company"],
        "agreement": blocks["agreement"],
        "head_to_head": pick_rows(sources, ticker, STRATEGIES_PICK_FIELDS),
        "predictions": prediction_rows(sources, ticker, STRATEGIES_PREDICTION_FIELDS),
        "on_company": scoreboard_rows(sources, SCOPE_STRATEGY_COMPANY, ticker, SCOREBOARD_FIELDS, False),
        "overall": scoreboard_rows(sources, SCOPE_STRATEGY, None, SCOREBOARD_FIELDS, True),
    }
