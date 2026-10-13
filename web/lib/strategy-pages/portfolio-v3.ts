// The Paper portfolio page, v3 (UX3, docs/ux/paper_portfolio_redesign.md; owner approval 2026-10-12): the reader's
// questions in order (am I up or down, which bets are working, why, what does the system learn). The new parts of B13's
// rm.portfolio (all_trades.open_holds, finished_sessions, learning; GET /portfolios/open/{k} and /finished/{date}) and
// each row's `why`, in plain words. Sides are never pooled: every strategy's trades, the Rule vs AI picks and the
// owner's own trades stay apart. Pure: no React. Paper only, never advice.
import type { AllTradesRow, TradeScope } from "./all-trades.ts";
import { MINUS } from "../ui/format.ts";

export type Side = "rule" | "baseline" | "ai";
export const SIDES: readonly Side[] = ["rule", "baseline", "ai"];
export const PICK_SIDES: readonly Side[] = ["rule", "ai"];

/** Plain names of the three kinds of strategy (owner, 2026-10-12: "Baseline" is "Simple benchmarks"). */
export const SIDE_NAME: Record<Side, string> = { rule: "Rule strategies", baseline: "Simple benchmarks", ai: "AI traders" };
export const SIDE_SHORT: Record<Side, string> = { rule: "Rule", baseline: "Benchmark", ai: "AI" };
export const SIDE_ONE: Record<Side, string> = { rule: "Rule strategy", baseline: "Simple benchmark", ai: "AI trader" };
export const SIDE_ABOUT: Record<Side, string> = {
  rule: "Fixed rules on the signal model’s chance of a rise and the checked news. They buy only when that chance clears their bar.",
  baseline: "Simple yardsticks the others must beat: “Always buy”, “Follow yesterday” and “Model without news”. A clever strategy that can’t beat these has no edge.",
  ai: "AI traders reading the news, the prices, or both. Each says how likely a rise is and why, or stays out.",
};

export interface TradeWhy {
  source: "intraday_check" | "settlement";
  check_at: string | null; session_date: string | null; move_pct: number | null; market_pct: number | null;
  /** The market's part of the move (benchmark x beta), computed from the stored fractions; absent before it was added. */
  market_pull_pct?: number | null;
  sector_pct: number | null; own_pct: number | null; news_pct: number | null; company_pct: number | null;
  beta: number | null; sector_source: string | null; reason_code: string | null; note: string | null; ai_reason: string | null;
}

/** A row of B13's all_trades with UX3's fields (absent in read models built before UX3). */
export type StoryRow = AllTradesRow & {
  direction?: "up" | "down" | null; prob_up?: number | null; reason?: string | null; why?: TradeWhy | null;
  /** Open strategy rows: sessions of the hold (D to the exit) up to the latest price's session, of k + 1. */
  sessions?: { held: number; total: number } | null;
};

export interface OpenSplit {
  open: number; going_with: number; going_against: number; pending: number; flagged: number;
  profit: number | null; loss: number | null; unrealised_pnl: number | null;
}
export interface OpenHold extends OpenSplit { horizon_days: number; exit_dates: string[]; by_family: Array<OpenSplit & { family: Side }> }
export interface FinishedCounts { closed: number; wins: number; losses: number; flat: number; net_pnl_market: number | null; net_pnl_your: number | null }
export interface FinishedSession extends FinishedCounts { session_date: string; not_entered: number; by_family: Array<FinishedCounts & { family: Side }> }
export interface Learning {
  lessons: { count: number; read_by: string; newest: { id: string; prediction_id: string; ticker: string; horizon_days: number | null; lesson: string | null; written_at: string | null } | null };
  review: { id: string; iso_week: string | null; written_at: string | null; first_finding: string | null; findings: number; proposals: number } | null;
  next_review_at: string;
  rule_today: { session_date: string; predictions: number; qualifying: number; best_prob_up: number | null; bar: number | null } | null;
}
export interface HoldPage { market: string; as_of: string | null; horizon_days: number; summary: OpenHold; trades: StoryRow[]; paper: boolean }
export interface FinishedPage { market: string; as_of: string | null; session_date: string; summary: FinishedSession; trades: StoryRow[]; paper: boolean }

export type Going = "with" | "against" | "pending";

/** An open trade against its prediction, on the price since the buy (a "down" call flips it), as B13's index counts. */
export function goingOf(row: StoryRow): Going {
  const entry = row.entry_price, last = row.exit_or_last_price;
  if (row.price_pending || entry === null || last === null) return "pending";
  const moved = last - entry;
  return (row.direction === "down" ? moved < 0 : moved > 0) ? "with" : "against";
}

/** The split of open rows, computed as B13's OpenSplit (for the Rule vs AI picks, which have no index of their own). */
export function splitOf(rows: StoryRow[]): OpenSplit {
  const pnl = rows.map((r) => r.unrealised_pnl).filter((v): v is number => v !== null && v !== undefined);
  const sum = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) * 100) / 100 : null);
  return {
    open: rows.length,
    going_with: rows.filter((r) => goingOf(r) === "with").length,
    going_against: rows.filter((r) => goingOf(r) === "against").length,
    pending: rows.filter((r) => goingOf(r) === "pending").length,
    flagged: rows.filter((r) => r.check?.flagged).length,
    profit: sum(pnl.filter((v) => v > 0)),
    loss: sum(pnl.filter((v) => v < 0)),
    unrealised_pnl: sum(pnl),
  };
}

/** The open rows of one scope grouped by hold, shortest first. */
export function byHold(rows: StoryRow[], scope: TradeScope): Map<number, StoryRow[]> {
  const out = new Map<number, StoryRow[]>();
  for (const r of rows) {
    if (r.scope !== scope || r.state !== "open" || !r.horizon_days) continue;
    out.set(r.horizon_days, [...(out.get(r.horizon_days) ?? []), r]);
  }
  return new Map([...out.entries()].sort((a, b) => a[0] - b[0]));
}

/** One line of a list: identical trades of strategies of the same side (same company, buy, entry and result, e.g.
 * "Always buy" and "Follow yesterday" buying the same stock) shown once, their results added. */
export interface MergedRow { key: string; rows: StoryRow[]; first: StoryRow; total: number | null }

export function mergeRows(rows: StoryRow[]): MergedRow[] {
  const groups = new Map<string, StoryRow[]>();
  for (const r of rows) {
    const result = r.state === "open" ? r.unrealised_pnl : r.pnl_market;
    const key = [r.ticker, r.family, r.horizon_days, r.entry_date, r.exit_date, r.entry_price, r.exit_or_last_price, r.state, r.outcome, result].join("|");
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  return [...groups.entries()].map(([key, rs]) => {
    const vals = rs.map((r) => (r.state === "open" ? r.unrealised_pnl : r.pnl_market)).filter((v): v is number => v !== null && v !== undefined);
    return { key, rows: rs, first: rs[0], total: vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) * 100) / 100 : null };
  });
}

/** A list's order: losing first (flagged first, then the biggest loss), else the biggest gain first. */
export function ordered(rows: MergedRow[], going: Going): MergedRow[] {
  const v = (m: MergedRow) => m.total ?? 0;
  if (going === "against") return [...rows].sort((a, b) => Number(!!b.first.check?.flagged) - Number(!!a.first.check?.flagged) || v(a) - v(b) || a.key.localeCompare(b.key));
  return [...rows].sort((a, b) => v(b) - v(a) || a.key.localeCompare(b.key));
}

/** A signed percent with a true minus sign, one decimal, halves rounded away from zero (1.45 -> 1.5, which toFixed
 * alone gets wrong for products like 1.0 x 1.45): "−2.9%"; a value that rounds to zero is "0.0%". */
export function pct1(x: number): string {
  const r = Math.round(Math.abs(x) * 10 + 1e-9) / 10;
  return (r === 0 ? "" : x > 0 ? "+" : MINUS) + r.toFixed(1) + "%";
}

/** Why an open trade moved, in one plain line, from its latest intraday check: the market's pull on this stock
 * (the benchmark's move times the stock's beta), its own move (the residual) and its sector. Null without a check. */
export function openCause(why: TradeWhy | null | undefined, benchmark: string): string | null {
  if (!why || why.source !== "intraday_check" || why.market_pct === null || why.own_pct === null) return null;
  const pull = why.market_pull_pct ?? (why.beta === null ? why.market_pct : why.market_pct * why.beta);
  const own = why.own_pct, fell = (why.move_pct ?? pull + own) < 0;
  const sector = why.sector_pct === null ? "" : ` Its sector ${pct1(why.sector_pct)}.`;
  const verb = fell ? "Fell" : "Rose";
  if (Math.abs(own) > Math.abs(pull)) {
    return `${verb} mostly on its own (${pct1(own)}); the market added ${pct1(pull)}.${sector}`;
  }
  return `${verb} with the whole market (${benchmark} ${pct1(why.market_pct)}, so ${pct1(pull)} for this stock); ${pct1(own)} on its own.${sector}`;
}

export const REASON_WORDS: Readonly<Record<string, string>> = {
  market: "the whole market", sector: "its sector", news: "news about it", company: "the company itself",
};

/** Why a finished trade ended where it did, in one plain line, from B2's automatic reason. Null without one. */
export function settledCause(why: TradeWhy | null | undefined): string | null {
  if (!why || why.source !== "settlement" || why.move_pct === null) return null;
  const parts: Array<[string, number | null]> = [["market", why.market_pct], ["sector", why.sector_pct], ["news", why.news_pct], ["company", why.company_pct]];
  const shown = parts.filter(([, v]) => v !== null && Math.abs(v) >= 0.05).map(([k, v]) => `${k} ${pct1(v as number)}`);
  const main = why.reason_code && REASON_WORDS[why.reason_code] ? `, mostly ${REASON_WORDS[why.reason_code]}` : "";
  return `Moved ${pct1(why.move_pct)}${main}.${shown.length ? ` Parts: ${shown.join(", ")}.` : ""}`;
}

/** Why the rule strategies have no trade, in plain words, from the learning block's rule_today (the line is for a
 * session where none of their predictions cleared the bar: `ruleStayedOut`). */
export const ruleStayedOut = (rule: Learning["rule_today"] | null | undefined) => !!rule && rule.qualifying === 0;

export function ruleNoneWords(rule: Learning["rule_today"] | null | undefined): { line: string; tip: string } {
  const line = "No trades today: the signal model saw no clear rise";
  if (!rule || rule.best_prob_up === null || rule.bar === null) return { line, tip: "Rule strategies buy only when the signal model’s chance of a rise clears their bar." };
  const best = Math.round(rule.best_prob_up * 100), bar = Math.round(rule.bar * 100);
  return {
    line,
    tip: `Rule strategies buy only when the signal model gives a rise at least a ${bar}% chance. On the newest session the highest chance was ${best}%, so ${rule.qualifying ? `${rule.qualifying} of their ${rule.predictions} predictions cleared it` : `none of their ${rule.predictions} predictions cleared it`}. Staying out is a result too.`,
  };
}

/** The prediction behind a strategy trade: an accuracy trade is `acc:<prediction id>`, a head-to-head trade
 * `h2h:<pick rule>:<prediction id>` (B4's open-trade ids). Null for the owner's own trades. */
export function predictionIdOf(row: StoryRow): string | null {
  if (row.scope === "mine") return null;
  if (row.id.startsWith("acc:")) return row.id.slice(4);
  if (row.id.startsWith("h2h:")) {
    const rest = row.id.slice(4), at = rest.indexOf(":");
    return at < 0 ? null : rest.slice(at + 1);
  }
  return null;
}

/** The "Full story" link's hash on the company page's lifecycle view of the entry session. */
export const storyHash = (row: StoryRow) => `#story=${encodeURIComponent(predictionIdOf(row) ?? "")}&trade=${encodeURIComponent(row.id)}`;

/** The hash's prediction and trade ids (null when absent). */
export function parseStoryHash(hash: string): { prediction: string | null; trade: string | null } {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  return { prediction: params.get("story"), trade: params.get("trade") };
}
