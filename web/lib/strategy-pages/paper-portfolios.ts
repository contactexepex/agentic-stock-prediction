// The Paper portfolios page's own presentation logic (B16; design/mockups/07-paper-portfolios, notes.md "Shown but
// computed by the page"): the KPI sums, the open trades filtered and grouped by strategy, and the add-trade form's
// request (body, Idempotency-Key, the receipt's words). A paper trade is a record, never an order. Pure.
import { FAMILY_ORDER, type Family, type ScoreboardRow, type Strategy } from "./scoreboard.ts";

export interface OpenTrade {
  trade_id: string;
  view: "accuracy" | "head_to_head";
  strategy_id: string;
  family: Family;
  ticker: string;
  horizon_days: number;
  entry_date: string;
  exit_date: string;
  entry_price: number;
  target_price: number;
  lo80: number;
  lo50: number;
  hi50: number;
  hi80: number;
  last_price: number | null;
  last_price_date: string | null;
  unrealised_pnl: number | null;
  unrealised_pct: number | null;
  to_target_pct: number | null;
}

export interface TradeCheck {
  id: string;
  check_at: string;
  trade_id: string;
  last_price: number | null;
  ret_since_entry_pct: number | null;
  band: string | null;
  flags: string[];
  flagged: boolean;
  high_since_entry_pct: number | null;
  low_since_entry_pct: number | null;
}

export interface OwnerTrade {
  id: string;
  ticker: string;
  side: "buy" | "sell";
  quantity: number | null;
  price: number | null;
  price_basis: "open" | "close" | "manual";
  trade_date: string;
  source: string;
  entered_at: string;
  note: string | null;
  supersedes: string | null;
}

export interface EurView {
  quantity: number;
  mark_date: string;
  eurusd_at_buy: number;
  eurusd_now: number;
  fx_fee_rate: number;
  cost_usd: number;
  value_usd: number;
  cost_eur: number;
  value_eur: number;
  fx_effect_eur: number;
  pnl_eur: number;
  note: string;
}

export interface OwnerPosition {
  ticker: string;
  quantity: number;
  avg_price: number;
  last_close: number | null;
  last_close_date: string | null;
  cost: number;
  value: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  eur_view: EurView | null;
}

export interface PortfolioCompany {
  ticker: string;
  name: string;
  state: string;
  amount?: number;
  last_close?: number | null;
  last_close_date?: string | null;
}

export interface PaperPortfoliosPayload {
  market: string;
  name: string;
  currency: string;
  as_of: string | null;
  strategies: Record<string, Strategy>;
  companies: PortfolioCompany[];
  h2h_rows: ScoreboardRow[];
  open_trades: OpenTrade[];
  trade_checks: TradeCheck[];
  owner: { trades: OwnerTrade[]; positions: OwnerPosition[]; default_amount: number; paper: boolean };
}

export const SOURCE: Readonly<Record<string, string>> = {
  dashboard: "the dashboard", slack: "Slack", cli: "the command line", claude_app: "the Claude app", claude_code: "Claude Code",
};

/** Sums of numbers that may be missing: null when none is known. */
function sumKnown(values: ReadonlyArray<number | null>): number | null {
  const known = values.filter((value): value is number => value !== null);
  return known.length ? known.reduce((total, value) => total + value, 0) : null;
}

export function openSummary(payload: PaperPortfoliosPayload): { open: number; unrealised: number | null; flagged: number } {
  return {
    open: payload.open_trades.length,
    unrealised: sumKnown(payload.open_trades.map((trade) => trade.unrealised_pnl)),
    flagged: payload.trade_checks.filter((check) => check.flagged).length,
  };
}

export function positionsSummary(positions: readonly OwnerPosition[]): { count: number; value: number | null; pnl: number | null } {
  return { count: positions.length, value: sumKnown(positions.map((p) => p.value)), pnl: sumKnown(positions.map((p) => p.pnl)) };
}

export function familyH2hRow(rows: readonly ScoreboardRow[], family: Family): ScoreboardRow | null {
  return rows.find((row) => row.scope === "strategy" && row.family === family && row.horizon_days === "all") ?? null;
}

export function pickRuleRow(rows: readonly ScoreboardRow[], family: Family, rule: string): ScoreboardRow | null {
  return rows.find((row) => row.scope === "pick_rule" && row.family === family && row.pick_rule === rule
    && row.horizon_days === "all") ?? null;
}

export interface OpenFilter {
  family: Family | null;
  view: "accuracy" | "head_to_head" | null;
}

/** The open trades passing the filter, grouped by strategy: rule strategies, baselines, AI traders, then by id. */
export function groupOpenTrades(trades: readonly OpenTrade[], strategies: Record<string, Strategy>, filter: OpenFilter):
  Array<{ id: string; trades: OpenTrade[]; unrealised: number | null }> {
  const kept = trades.filter((trade) => (!filter.family || trade.family === filter.family) && (!filter.view || trade.view === filter.view));
  const groups = new Map<string, OpenTrade[]>();
  for (const trade of kept) {
    const list = groups.get(trade.strategy_id);
    if (list) list.push(trade);
    else groups.set(trade.strategy_id, [trade]);
  }
  const familyOf = (id: string, list: OpenTrade[]) => strategies[id]?.family ?? list[0].family;
  return [...groups.entries()]
    .sort(([a, x], [b, y]) => FAMILY_ORDER[familyOf(a, x)] - FAMILY_ORDER[familyOf(b, y)] || a.localeCompare(b))
    .map(([id, list]) => ({ id, trades: list, unrealised: sumKnown(list.map((trade) => trade.unrealised_pnl)) }));
}

/** The newest check of each trade (by check time). */
export function latestChecks(checks: readonly TradeCheck[]): Map<string, TradeCheck> {
  const out = new Map<string, TradeCheck>();
  for (const check of checks) {
    const seen = out.get(check.trade_id);
    if (!seen || seen.check_at < check.check_at) out.set(check.trade_id, check);
  }
  return out;
}

/* ---------- the add-trade form ---------- */

export interface TradeForm {
  ticker: string;
  side: "buy" | "sell";
  quantity: string;
  trade_date: string;
  price_basis: "open" | "close" | "manual";
  price: string;
  note: string;
}

export const NOTE_MAX = 200;

/** The request body of POST /markets/{m}/paper-trades (only the body fields the route accepts), or the reasons the
 * form cannot be sent yet. The server (B5's tool layer, WS4's import) decides; this only catches what the form can. */
export function tradeRequest(form: TradeForm, currency: string, activeTickers: ReadonlySet<string>):
  { body: Record<string, unknown> } | { errors: string[] } {
  const errors: string[] = [];
  if (!activeTickers.has(form.ticker)) errors.push("Choose an active company.");
  const quantity = Number(form.quantity);
  if (!(quantity > 0) || !Number.isFinite(quantity)) errors.push("Shares must be a number above zero.");
  else if (currency === "INR" && !Number.isInteger(quantity)) errors.push("Whole shares only in India.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.trade_date)) errors.push("Give the session date.");
  let price: number | null = null;
  if (form.price_basis === "manual") {
    price = Number(form.price);
    if (form.price.trim() === "" || !(price > 0) || !Number.isFinite(price)) errors.push("A typed price must be a number above zero.");
  }
  if (form.note.length > NOTE_MAX) errors.push(`The note is at most ${NOTE_MAX} characters.`);
  if (errors.length) return { errors };
  const body: Record<string, unknown> = { ticker: form.ticker, side: form.side, quantity, trade_date: form.trade_date, price_basis: form.price_basis };
  if (price !== null) body.price = price;
  if (form.note.trim()) body.note = form.note.trim();
  return { body };
}

export interface Receipt {
  command_id?: string | null;
  result: string;
  refusal_code?: string | null;
  message?: string | null;
  inbox_id?: string | null;
}

export type ReceiptState = "pending" | "duplicate" | "refused" | "retry";

/** What the form says for a response (docs/ws/b13.md batch 2): 202 pending, 200 the receipt of an earlier identical
 * request, 429 and 503 try again later (same key), anything else refused with the layer's message. */
export function receiptState(status: number): ReceiptState {
  if (status === 202) return "pending";
  if (status === 200) return "duplicate";
  if (status === 429 || status === 503) return "retry";
  return "refused";
}

/** One Idempotency-Key per opened form, reused on a retry (crypto.randomUUID where available). */
export function newIdempotencyKey(random: () => string = randomId): string {
  return `web-${random()}`;
}

/** 32 random hex digits: crypto.randomUUID where the page is a secure context, else crypto.getRandomValues. */
function randomId(): string {
  const c = globalThis.crypto;
  if (typeof c.randomUUID === "function") return c.randomUUID().replace(/-/g, "");
  return Array.from(c.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}
