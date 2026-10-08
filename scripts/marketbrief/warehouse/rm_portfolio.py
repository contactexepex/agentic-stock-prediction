"""The Paper portfolios page (B13; docs/ws/b13.md): rm.portfolio, page_key `_`, served by
GET /api/v1/markets/{market}/portfolios. Payload PaperPortfolios = design/mockups/07-paper-portfolios/data.json per
market (notes.md there names every key and its selection rule): the shared blocks of rm_common, the companies with
their last stored close, the head-to-head portfolios (scoreboard rows of scopes strategy and pick_rule), the open
trades and the latest intraday trade checks (B4's and B12's derivations, the same rows as rm.trades `_`), and the
owner's own paper trades and FIFO positions with the EUR view of US positions (WS4/B2's portfolio service), all as of
the cut-off. Research only: a paper trade is a record, never an order."""

from __future__ import annotations

from marketbrief.constants.warehouse import MARKET_PAGE_KEY
from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.portfolio import reads as portfolio_reads
from marketbrief.portfolio import service as portfolio_service
from marketbrief.portfolio.context import Context as PortfolioContext
from marketbrief.portfolio.settings import load_portfolio_config, market_costs
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import rm_common, rm_company
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder
from marketbrief.warehouse.rm_strategies import market_mockup, pick, scoreboard_rows

RM_PORTFOLIO = "portfolio"
VIEW_HEAD_TO_HEAD = "head_to_head"
SCOPES = ("strategy", "pick_rule")
PCT_DIGITS = 2
MONEY_DIGITS = 2
STRATEGY_PAGE_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state", "amount", "amount_overridden", "currency")
H2H_ROW_DROPPED = ("ticker", "regime", "median_reached_session", "go_live")  # 07-paper-portfolios notes.md `h2h_rows`
OWNER_TRADE_FIELDS = (
    "id",
    "market",
    "ticker",
    "side",
    "quantity",
    "price",
    "price_basis",
    "trade_date",
    "source",
    "idempotency_key",
    "entered_at",
    "note",
    "supersedes",
)
OPEN_TRADE_FIELDS = (
    "trade_id",
    "view",
    "prediction_id",
    "strategy_id",
    "family",
    "market",
    "ticker",
    "horizon_days",
    "entry_date",
    "exit_date",
    "entry_price",
    "quantity",
    "amount",
    "currency",
    "target_price",
    "lo80",
    "lo50",
    "hi50",
    "hi80",
    "last_price",
    "last_price_date",
    "unrealised_pnl",
    "unrealised_pct",
    "to_target_pct",
    "paper",
)


def companies(ctx: BuildContext) -> list[dict]:
    """The collected companies (B1's watchlist as of the cut-off) with the last stored close of the dashboard (split
    adjusted) and its date; null when the company has no stored bar."""
    last = {company["ticker"]: company.get("last") or {} for company in ctx.dashboard.get("companies") or []}
    out = []
    for company in sorted(ctx.companies, key=lambda c: c["ticker"]):
        mark = last.get(company["ticker"]) or {}
        out.append(
            {
                **pick(company, COMPANY_FIELDS),
                "last_close": json_safe_float(mark.get("close")),
                "last_close_date": mark.get("date"),
            }
        )
    return out


def h2h_rows(ctx: BuildContext) -> list[dict]:
    """The head-to-head portfolios: scoreboard rows of scopes strategy (per family) and pick_rule, forward basis."""
    return [
        {key: value for key, value in row.items() if key not in H2H_ROW_DROPPED}
        for row in scoreboard_rows(ctx)
        if row["view"] == VIEW_HEAD_TO_HEAD and row["scope"] in SCOPES
    ]


def open_trades(ctx: BuildContext) -> list[dict]:
    """Every open paper trade of the market (B4's shared derivation, rm_common.open_trades: the same rows as B12's
    rm.trades `_` and the Company records' counts), in its page fields."""
    return [pick(trade, OPEN_TRADE_FIELDS) for trade in rm_common.open_trades(ctx)]


def trade_checks(ctx: BuildContext) -> list[dict]:
    """The rows of the market's latest intraday trade check by the cut-off: B12's rm_company.market_trade_checks
    (schema TradeCheck), the same list as rm.trades `_`, whole (the 07 page reads its subset of the fields)."""
    return rm_company.market_trade_checks(ctx)


def portfolio_context(ctx: BuildContext) -> PortfolioContext:
    """The portfolio service's context at the build's cut-off (its every read is as of that clock)."""
    return PortfolioContext(
        ctx.market, ctx.cfg, ctx.con, ctx.cutoff_time, load_portfolio_config(), market_costs(ctx.market)
    )


def owner_trades(context: PortfolioContext) -> list[dict]:
    """Every paper trade row the owner entered by the cut-off (active, cancelled and corrected), oldest first; the
    channel identity (submitted_by, command_id) is left out."""
    frame = portfolio_reads.trade_rows(context.con, context.clock)
    out = []
    for record in frame.to_dict("records"):
        row = {
            name: (None if record.get(name) != record.get(name) else record.get(name)) for name in OWNER_TRADE_FIELDS
        }
        row["trade_date"] = None if row["trade_date"] is None else str(row["trade_date"])[:10]
        row["entered_at"] = rm_common.iso_z(row["entered_at"])
        row["quantity"] = json_safe_float(row["quantity"])
        row["price"] = json_safe_float(row["price"])
        out.append(row)
    return out


def owner_positions(context: PortfolioContext) -> list[dict]:
    """The owner's open positions (FIFO, marked to the latest stored close by the cut-off) in the catalogue's fields,
    before costs, each with its EUR view (US) or null."""
    report = portfolio_service.positions_report(context)
    eur = {row["ticker"]: row for row in report.get("eur_view") or []}
    out = []
    for position in report["positions"]:
        cost, value = position["cost_value"], position["market_value"]
        pnl = None if value is None else round(value - cost, MONEY_DIGITS)
        out.append(
            {
                "market": context.market,
                "ticker": position["ticker"],
                "quantity": position["quantity"],
                "avg_price": position["avg_price"],
                "last_close": position["mark"],
                "last_close_date": position["mark_date"],
                "currency": context.cfg.get("currency"),
                "cost": cost,
                "value": value,
                "pnl": pnl,
                "pnl_pct": None if pnl is None or not cost else round(pnl / cost * 100, PCT_DIGITS),
                "eur_view": eur.get(position["ticker"]),
            }
        )
    return out


def owner(ctx: BuildContext) -> dict:
    """The owner's paper portfolio of the market as of the cut-off."""
    context = portfolio_context(ctx)
    return {
        "trades": owner_trades(context),
        "positions": owner_positions(context),
        "default_amount": DEFAULT_AMOUNT[ctx.market],
        "paper": True,
    }


def portfolio_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.portfolio: the market's one Paper portfolios page."""
    return {
        MARKET_PAGE_KEY: {
            **rm_common.header(ctx),
            "status": rm_common.status_block(ctx),
            **rm_common.horizons(ctx),
            "go_live": rm_common.go_live(ctx),
            "strategies": rm_common.strategies(ctx, STRATEGY_PAGE_FIELDS),
            "companies": companies(ctx),
            "h2h_rows": h2h_rows(ctx),
            "open_trades": open_trades(ctx),
            "trade_checks": trade_checks(ctx),
            "owner": owner(ctx),
        }
    }


BUILDERS = (PageBuilder(RM_PORTFOLIO, "PaperPortfolios", portfolio_pages, owner="B13"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/portfolios",
        table=RM_PORTFOLIO,
        mockup="design/mockups/07-paper-portfolios/data.json",
        mockup_payload=market_mockup,
        map_paths=("$.strategies",),
    ),
)
