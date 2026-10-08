// The Companies page's own computations (design/mockups/10-companies/notes.md "Shown but computed by the page"): the
// counts, the inactive rows' deactivation event and news, and the words of the requests and lifecycle lists.
// Presentation only.

export interface CompanyRow {
  ticker: string;
  name: string;
  state: string;
  state_since?: string | null;
  amount_overridden?: boolean;
}
export interface LifecycleEvent {
  id: string;
  event: string;
  ticker: string;
  recorded_at: string;
  effective_from: string;
  channel: string | null;
  requested_by: string | null;
  reason: string | null;
  amount: number | null;
  onboarding?: Record<string, string> | null;
}
export interface Command {
  id: string;
  tool: string;
  result: string | null;
  arguments: Record<string, unknown> | null;
  record_ids: string[];
  refusal_code: string | null;
}
export interface InactiveNews { id: string; tickers: string[] }

export const CHANNEL: Record<string, string> = {
  dashboard: "the dashboard", slack: "Slack", cli: "the command line", claude_app: "the Claude app",
  claude_code: "Claude Code", seed: "the seed (config)",
};
export const EVENT_WORDS: Record<string, string> = {
  add: "added", deactivate: "deactivated", reactivate: "reactivated", delete: "deleted", set_amount: "amount set",
};
/** A request's result word and its label tone (never colour alone: the word is always shown). */
export const RESULT: Record<string, [string, "success" | "warn" | "danger" | "neutral"]> = {
  accepted: ["accepted", "success"], pending: ["pending", "warn"], refused: ["refused", "danger"],
  duplicate: ["duplicate", "neutral"], failed: ["failed", "danger"],
};
export const TOOL: Record<string, string> = {
  add_company: "add a company", deactivate_company: "deactivate", reactivate_company: "reactivate",
  set_paper_amount: "set the paper amount", delete_company: "delete",
};
export const EVENT_TONE: Record<string, "success" | "neutral" | "info" | "danger"> = {
  add: "success", reactivate: "success", deactivate: "neutral", set_amount: "info", delete: "danger",
};

export interface CompaniesCounts { active: number; inactive: number; custom: number; pending: number }
/** The KPI counts; `localPending` = requests sent from this page that the next import has not yet logged. */
export function companiesCounts(companies: readonly CompanyRow[], commands: readonly Command[], localPending = 0): CompaniesCounts {
  const active = companies.filter((c) => c.state === "active");
  return {
    active: active.length,
    inactive: companies.filter((c) => c.state === "inactive").length,
    custom: active.filter((c) => c.amount_overridden).length,
    pending: localPending + commands.filter((c) => c.result === "pending").length,
  };
}

/** The newest deactivate event of a company (lifecycle is newest first). */
export const deactivation = (lifecycle: readonly LifecycleEvent[], ticker: string): LifecycleEvent | null =>
  lifecycle.find((e) => e.ticker === ticker && e.event === "deactivate") ?? null;

export const newsSince = <T extends InactiveNews>(items: readonly T[], ticker: string): T[] => items.filter((n) => n.tickers.includes(ticker));

/** A command's arguments as "symbol AMZN, ticker X" (the market key left out); the tool name when none. */
export function commandArguments(c: Command): string {
  const text = Object.entries(c.arguments ?? {}).filter(([k]) => k !== "market").map(([k, v]) => `${k} ${String(v)}`).join(", ");
  return text || c.tool;
}

/** The onboarding checks of a real add as "identifiers ok, not etf ok" (seed adds are not listed). */
export function onboardingWords(e: LifecycleEvent): string | null {
  if (!e.onboarding || e.channel === "seed") return null;
  return Object.entries(e.onboarding).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ");
}

/** The typed confirmation of a delete: the ticker, case-insensitive, surrounding spaces ignored. */
export const deleteConfirmed = (typed: string, ticker: string): boolean => typed.trim().toUpperCase() === ticker.toUpperCase();

/** A positive whole amount of money per paper trade, or null when the text is not one. */
export function parseAmount(text: string): number | null {
  const t = text.trim();
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const v = Number(t);
  return v >= 1 && Number.isFinite(v) ? v : null;
}

/** The reason of a deactivate or reactivate request: trimmed, at most 200 characters (the mockup's limit). */
export const REASON_MAX_CHARS = 200;
export const cleanReason = (text: string): string => text.trim().slice(0, REASON_MAX_CHARS);
