// The Home page's own computations (design/mockups/01-home/notes.md "Shown but computed by the page"): the KPI counts
// and sums, the head-to-head grouping and cost lines, the cumulative profit per family, the alerts and the runs
// count; the "Can I rely on this yet?" checklist and "Today in 3 lines" (docs/ux/plain_language_review.md section 3).
// Presentation only.
import {
  GO_LIVE_MONTHS, GO_LIVE_TRADES_ABOUT, INTRADAY_CHECKS_PER_SESSION, NEWS_STATUS, REFERENCE_STRATEGY_WORDS, regimeWords,
} from "../ui/constants.ts";
import { viableLine, yourViable, type Pick as CostPick } from "../ui/costs.ts";
import { firstExit } from "../ui/empty.ts";
import { fmtDate, fmtDateYear, signed } from "../ui/format.ts";
import type { GoLive, GoLiveChecks, GoLiveNearest, SkillVerdict } from "../ui/types.ts";

export { INTRADAY_CHECKS_PER_SESSION };

export type Family = "rule" | "baseline" | "ai";
export const FAMILIES: Family[] = ["rule", "baseline", "ai"];
export type PickRule = "best_expected_gain" | "highest_probability";
export const PICK_RULES: PickRule[] = ["best_expected_gain", "highest_probability"];

export interface Candidate {
  horizon_days: number;
  prob_up: number | null;
  move_pct: number | null;
  loss_pct: number | null;
  costs_pct: number | null;
  expected_gain_pct: number | null;
  your_cost_pct?: number | null;
  expected_gain_your_pct?: number | null;
  cost_viable?: boolean | null;
}
export interface HeadToHeadPick {
  id: string;
  ticker: string;
  family: Family;
  pick_rule: PickRule;
  status: string;
  strategy_id: string | null;
  horizon_days: number | null;
  expected_gain_pct: number | null;
  amount: number | null;
  candidates: Candidate[] | null;
}

/** A picked pick (status "picked") has every number of B7's cost view (lib/ui/costs.ts Pick). */
export const isPicked = (k: HeadToHeadPick): boolean => k.status === "picked";
const asPick = (k: HeadToHeadPick) => k as unknown as CostPick;
/** true / false = viable or not at the owner's cost; null = not stored (B7's yourViable). */
export const yourViableOf = (k: HeadToHeadPick): boolean | null => yourViable(asPick(k));
export const clearsMarketCosts = (k: HeadToHeadPick): boolean => (k.expected_gain_pct ?? 0) > 0;
/** The expected gain in money: expected_gain_pct x amount / 100 (notes.md). */
export const expectedGainMoney = (k: HeadToHeadPick): number | null =>
  k.expected_gain_pct == null || k.amount == null ? null : (k.expected_gain_pct * k.amount) / 100;

export interface PickSummary { picked: number; clearMarket: number; viableYours: number }
/** The KPI counts of the session's picks; the sum line's words are B7's viableLine. */
export function pickSummary(picks: readonly HeadToHeadPick[]): PickSummary {
  const picked = picks.filter(isPicked);
  return { picked: picked.length, clearMarket: picked.filter(clearsMarketCosts).length, viableYours: picked.filter((k) => yourViableOf(k) === true).length };
}
/** "n expected to beat market fees · m worth it after your fees" of the picked picks (B7's viableLine). */
export const viableLineOf = (picks: readonly HeadToHeadPick[]): string => viableLine(picks.filter(isPicked).map(asPick));

/** Picks grouped by company in payload order. */
export function groupBy<T, K extends string>(rows: readonly T[], key: (row: T) => K): [K, T[]][] {
  const out = new Map<K, T[]>();
  for (const r of rows) {
    const k = key(r);
    const list = out.get(k);
    if (list) list.push(r);
    else out.set(k, [r]);
  }
  return [...out.entries()];
}

export interface SettledTrade { view: string; family: Family; exit_date_actual: string | null; net_pnl: number | null }
export interface ProfitSeries { family: Family; points: number[] }
/**
 * The cumulative profit after costs per family by settlement day, from the settled trades of the accuracy view (the
 * Rule vs AI chart). Trades without an actual exit date never settled with money and are left out.
 */
export function cumulativeProfit(trades: readonly SettledTrade[], families: readonly Family[] = ["rule", "ai", "baseline"]): { days: string[]; series: ProfitSeries[]; trades: number } {
  const rows = trades.filter((r) => r.view === "accuracy" && r.exit_date_actual);
  const days = [...new Set(rows.map((r) => r.exit_date_actual as string))].sort();
  const series = families.map((family) => {
    let acc = 0;
    return {
      family,
      points: days.map((d) => {
        acc += rows.filter((r) => r.family === family && r.exit_date_actual === d).reduce((s, r) => s + (r.net_pnl ?? 0), 0);
        return acc;
      }),
    };
  });
  return { days, series, trades: rows.length };
}

export interface EodFamily { trades: number; wins: number; net_pnl: number | null }
/** The family that led the last close: the highest net profit among families with trades (ties all lead). */
export function eodLeaders(results: Partial<Record<Family, EodFamily>>): Set<Family> {
  const withTrades = FAMILIES.filter((f) => (results[f]?.trades ?? 0) > 0);
  if (!withTrades.length) return new Set();
  const best = Math.max(...withTrades.map((f) => results[f]?.net_pnl ?? Number.NEGATIVE_INFINITY));
  return new Set(withTrades.filter((f) => (results[f]?.net_pnl ?? Number.NEGATIVE_INFINITY) === best));
}

export interface RunState { at: string | null; ok: boolean | null; next_at?: string | null; new_items?: number | null }
export interface Runs { pre_open: RunState; intraday: RunState[]; post_close: RunState; news: RunState }
/** Runs ok of the day's expected runs: pre-open, the intraday checks, post-close and the latest news run. */
export function runsOk(runs: Runs): { ok: number; total: number } {
  const all = [runs.pre_open, ...runs.intraday.slice(0, INTRADAY_CHECKS_PER_SESSION), runs.post_close, runs.news];
  return { ok: all.filter((r) => r.ok === true).length, total: 1 + INTRADAY_CHECKS_PER_SESSION + 1 + 1 };
}

/* ---- "Can I rely on this yet?" and "Today in 3 lines" (docs/ux/plain_language_review.md section 3) ---------------- */

/** One line of the checklist: met (true), not met (false) or not measurable yet (null). */
export interface RelyCheck { key: string; what: string; met: boolean | null; detail: string }

const unknownWord = (met: boolean | null, yes: string, no: string, unknown: string) => (met === true ? yes : met === false ? no : unknown);

/** The checklist of the go-live bar for the reference strategy, plus the weekly review's model skill. */
export function relyChecks(goLive: GoLive, checks: GoLiveChecks | null | undefined, skill: SkillVerdict | null | undefined): RelyCheck[] {
  const done = Math.max(0, GO_LIVE_TRADES_ABOUT - goLive.trades_needed);
  const earliest = checks?.earliest_date ? ` (earliest: ${fmtDateYear(checks.earliest_date)})` : "";
  return [
    { key: "trades", what: "Enough finished trades", met: goLive.trades_needed === 0, detail: `${done} of about ${GO_LIVE_TRADES_ABOUT} (${REFERENCE_STRATEGY_WORDS.toLowerCase()})` },
    { key: "months", what: "Long enough", met: goLive.months_forward >= GO_LIVE_MONTHS, detail: `${goLive.months_forward.toFixed(1)} of ${GO_LIVE_MONTHS} months${earliest}` },
    { key: "baseline", what: "Beats “always buy” after your fees, beyond luck", met: goLive.beats_best_baseline, detail: unknownWord(goLive.beats_best_baseline, "yes", "not yet", "not measurable yet") },
    { key: "drawdown", what: "Losses stay within the limit", met: checks?.drawdown_within_limit ?? null, detail: unknownWord(checks?.drawdown_within_limit ?? null, "yes", "no: the biggest fall is over the limit", "not measured yet") },
    { key: "regimes", what: "Works in calm and jumpy markets", met: checks?.holds_in_calm_and_volatile ?? null, detail: unknownWord(checks?.holds_in_calm_and_volatile ?? null, "yes", "not in both", "not enough data yet") },
    {
      key: "skill", what: "The model shows real skill (weekly review)", met: skill ? skill.state === "shown" : null,
      detail: skill ? (skill.state === "shown" ? `Yes. ${skill.why}` : `No. ${skill.why}`) : "no weekly review yet",
    },
  ];
}

/** "Closest to passing: Model + news (rule): 12 of about 300 finished trades" when it is not the reference itself. */
export function nearestLine(nearest: GoLiveNearest | null | undefined, referenceId: string): string | null {
  if (!nearest || nearest.strategy_id === referenceId) return null;
  const done = Math.max(0, GO_LIVE_TRADES_ABOUT - nearest.trades_needed);
  return `Closest to passing: ${nearest.name} (${nearest.family === "ai" ? "AI trader" : "rule strategy"}), ${done} of about ${GO_LIVE_TRADES_ABOUT} finished trades, ${nearest.months_forward.toFixed(1)} of ${GO_LIVE_MONTHS} months.`;
}

export interface SoFar { finished: number; won: number; lost: number; net: number | null }
/** Finished paper trades with money (net after market fees): count, won (> 0), lost (< 0) and their net sum. */
export function tradesSoFar(settled: readonly { net_pnl: number | null }[]): SoFar {
  const rows = settled.filter((t) => t.net_pnl != null) as { net_pnl: number }[];
  return {
    finished: rows.length,
    won: rows.filter((t) => t.net_pnl > 0).length,
    lost: rows.filter((t) => t.net_pnl < 0).length,
    net: rows.length ? rows.reduce((s, t) => s + t.net_pnl, 0) : null,
  };
}

/** Line 1 of "Today in 3 lines": the market mood, the benchmark's last move and the followed companies up and down. */
export function moodLine(
  regime: string | null | undefined,
  benchmark: { name: string; change_pct: number | null; close_date: string } | null | undefined,
  companies: readonly { state: string; change_pct?: number | null }[],
): string {
  const active = companies.filter((c) => c.state === "active" && c.change_pct != null);
  const up = active.filter((c) => (c.change_pct as number) > 0).length;
  const down = active.filter((c) => (c.change_pct as number) < 0).length;
  const index = benchmark && benchmark.change_pct != null ? ` ${benchmark.name} moved ${signed(benchmark.change_pct)} on ${fmtDate(benchmark.close_date)}` : "";
  const moves = active.length ? `${index ? ";" : ""} ${up} of the ${active.length} companies you follow rose, ${down} fell.` : index ? "." : "";
  return `Market mood: ${regimeWords(regime)}.${index}${moves}`;
}

/** Line 2: how many paper trades the session being predicted opens and when the first running ones finish. */
export function tradesLine(openTrades: readonly { entry_date: string; exit_date: string }[], sessionDate: string | null | undefined): string {
  if (!openTrades.length) return "No paper trade is running.";
  const today = sessionDate ? openTrades.filter((t) => t.entry_date === sessionDate).length : 0;
  const first = firstExit(openTrades);
  const running = `${openTrades.length} paper trade${openTrades.length === 1 ? "" : "s"} running`;
  const opened = today ? `, ${today} of them opened on ${fmtDate(sessionDate)}` : "";
  return `${running}${opened}; the first finishes at the close on ${fmtDate(first)}.`;
}

/** Line 3: the top market mover's headline and its check status ("market-wide" when it has none). */
export function storyLine(top: { title: string; status?: string | null } | undefined): string {
  if (!top) return "No market-moving story in the last 3 days.";
  const word = top.status ? (NEWS_STATUS[top.status] ?? [top.status])[0] : "market-wide";
  return `The story that mattered: “${top.title}” (${word}).`;
}
