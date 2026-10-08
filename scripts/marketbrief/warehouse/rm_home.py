"""The Home page (B11; design/mockups/01-home/notes.md): rm.home, page_key `_`, served by
GET /api/v1/markets/{market}/home (schema HomePayload in api/schemas/home.yaml).

Payload: the page shell; B4's Company records, Agreement (top 5 active companies per horizon), open trades and
settled trades; B12's latest trade checks by the cut-off; the head-to-head picks of the session being predicted
(B2's stored picks); B13's newest end-of-day analysis and the head-to-head scoreboard rows per family and pick rule
(all horizons: "to date"); the strategies; and the News window (the same items as the News page). Every signal
stays Paper: the shell's `status.paper_label` and `go_live` say whether anything is proven. Everything is as of the
cut-off; no build time is in the payload."""

from __future__ import annotations

from marketbrief.constants.market_pages import HOME_AGREEMENT_TOP, RM_HOME
from marketbrief.constants.warehouse import MARKET_PAGE_KEY
from marketbrief.lab import reads as lab_reads
from marketbrief.warehouse import rm_common, rm_compare, rm_strategies
from marketbrief.warehouse.market_page_parts import (
    companies,
    market_mockup,
    news_selection,
    pick,
    session_date,
    shell,
    trade_checks,
)
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder
from marketbrief.warehouse.rm_watchlist import CHECK_FIELDS as WATCHLIST_CHECK_FIELDS

COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "amount", "amount_overridden",
                  "currency", "last_close", "last_close_date", "change_pct", ("agreement_n1", ("buy", "of")),
                  "open_trades")
PICK_FIELDS = ("id", "market", "ticker", "made_at", "as_of_date", "session_date", "family", "pick_rule", "status",
               "strategy_id", "strongest_basis", "horizon_days", "prediction_id", "base_close", "prob_up", "move_pct",
               "loss_pct", "costs_pct", "expected_gain_pct", "amount", "currency", "method_version")
RANKING_FIELDS = ("strategy_id", "rank", "basis", "settled_trades", "net_pnl")
EOD_PROMPT_SQL = "SELECT prompt_version FROM eod_analyses WHERE id = ? AND created_at <= ?::TIMESTAMPTZ LIMIT 1"
EOD_FIELDS = ("id", "market", "session_date", "settled_trades", "results", "summary", "cited_ids", "reason_ids",
              "prompt_version", "created_at")
TO_DATE_FIELDS = ("scope", "market", "view", "family", "pick_rule", "horizon_days", "trades", "net_pnl",
                  "mean_return_pct", "win_rate", "sample_badge", "basis", "as_of")
SETTLED_FIELDS = ("trade_id", "view", "pick_rule", "strategy_id", "family", "ticker", "horizon_days", "entry_date",
                  "exit_date", "exit_date_actual", "status", "amount", "currency", "net_pnl", "return_pct",
                  "reason_code", "settled_at")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
# the Intraday trade check's base fields (as on the Watchlist) and its detail columns (issue #78)
CHECK_FIELDS = WATCHLIST_CHECK_FIELDS + (
    "family", "pick_rule", "quality", "entry_source", "basis_factor", "entry_adj", "target_adj", "lo80_adj",
    "lo50_adj", "hi50_adj", "hi80_adj", "last_time", "sigma_1d", "elapsed_fraction", "sessions_held", "sessions_left",
    "z_since_entry", "target_reached", "target_reached_session", "high_since_entry_pct", "low_since_entry_pct", "notes")
SCOPE_PICK_RULE = "pick_rule"
VIEW_HEAD_TO_HEAD = "head_to_head"
ALL_HORIZONS = "all"


def top_agreement(ctx: BuildContext) -> dict[str, list[dict]]:
    """B4's Agreement per horizon, the active companies' first HOME_AGREEMENT_TOP by rank."""
    return {k: [row for row in rows if row["ticker"] in ctx.active][:HOME_AGREEMENT_TOP]
            for k, rows in rm_common.agreement(ctx).items()}


def head_to_head(ctx: BuildContext) -> list[dict]:
    """The head-to-head picks made by the cut-off (B2's lab/reads.picks: first row per id) of the session being
    predicted, of strategies live on that session (B4's live_rows: a rehearsal pick is never shown), active companies,
    by company, family and pick rule; with the ranking they came from and every candidate horizon (B13's candidate
    fields)."""
    day = session_date(ctx)
    out = []
    for row in rm_common.live_rows(lab_reads.picks(ctx.con, ctx.cutoff_time), "session_date"):
        if row["session_date"] != day or row["ticker"] not in ctx.active:
            continue
        item = pick(row, PICK_FIELDS)
        item["made_at"] = rm_common.iso_z(item["made_at"])
        item["ranking"] = [pick(entry, RANKING_FIELDS) for entry in row.get("ranking") or []]
        item["candidates"] = [pick(entry, rm_compare.CANDIDATE_FIELDS) for entry in row.get("candidates") or []]
        out.append(item)
    return sorted(out, key=lambda p: (p["ticker"], p["family"], p["pick_rule"], p["id"]))


def newest_eod(ctx: BuildContext) -> dict | None:
    """B13's newest end-of-day analysis written by the cut-off, or None."""
    analyses = rm_compare.eod_analyses(ctx)  # newest first, B13's record (results shaped per family and pick rule)
    if not analyses:
        return None
    newest = pick(analyses[0], EOD_FIELDS)
    found = ctx.con.execute(EOD_PROMPT_SQL, [newest["id"], ctx.cutoff]).fetchone()
    newest["prompt_version"] = found[0] if found else None
    return newest


def to_date(ctx: BuildContext) -> list[dict]:
    """The head-to-head scoreboard rows per family and pick rule over all horizons (B13's scoreboard_rows)."""
    return [pick(row, TO_DATE_FIELDS) for row in rm_strategies.scoreboard_rows(ctx)
            if row["scope"] == SCOPE_PICK_RULE and row["view"] == VIEW_HEAD_TO_HEAD
            and str(row["horizon_days"]) == ALL_HORIZONS]


def home_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.home: the market's one Home page."""
    items, _window = news_selection(ctx)
    payload = {
        **shell(ctx),
        "companies": sorted(companies(ctx, COMPANY_FIELDS), key=lambda row: row["ticker"]),
        "agreement": top_agreement(ctx),
        "head_to_head": head_to_head(ctx),
        "open_trades": rm_common.open_trades(ctx),
        "trade_checks": trade_checks(ctx, CHECK_FIELDS),
        "eod": newest_eod(ctx),
        "to_date": to_date(ctx),
        "strategies": rm_common.strategies(ctx, STRATEGY_FIELDS),
        "news": items,
        "settled_trades": [pick(row, SETTLED_FIELDS) for row in rm_common.settled_trades(ctx)],
    }
    return {MARKET_PAGE_KEY: payload}


BUILDERS = (PageBuilder(RM_HOME, "HomePayload", home_pages, owner="B11"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/home",
        table=RM_HOME,
        mockup="design/mockups/01-home/data.json",
        mockup_payload=market_mockup,
        map_paths=("$.strategies", "$.agreement"),
    ),
)
