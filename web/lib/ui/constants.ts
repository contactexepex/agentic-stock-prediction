// Spec constants and display labels of the cockpit (B7). The numbers are the named constants of the approved mockups
// (design/mockups/_shared/shell.js), each with its source; the labels are the mockups' words. Not data.
import type { Market } from "../data/constants.ts";

/* docs/SPEC.md F7.2: the go-live bar = 2 months of forward paper trading and about 300 settled trades per strategy;
   section 7: two intraday checks per session; section 6: fewer than 20 settled trades is too few to rank; F2.3: the
   back-test runs on the 15-year history cache; F7.1: the luck test is a 95% percentile bootstrap interval;
   F4.2, section 7 and F6: an AI trader's reason, a deviation note and an EOD reason are at most 60 words. */
export const GO_LIVE_MONTHS = 2;
export const GO_LIVE_TRADES_ABOUT = 300;
export const INTRADAY_CHECKS_PER_SESSION = 2;
export const MIN_TRADES_TO_RANK = 20;
export const BACKTEST_YEARS = 15;
export const LUCK_INTERVAL_PCT = 95;
export const REASON_MAX_WORDS = 60;
/* F11 and mcp/tools.yaml (explain): the assistant's question is at most 500 characters, conversations kept 90 days.
   No money budget is enforced in code (owner, 2026-10-08: the Anthropic console limit is the only cap), so none is
   named here. */
export const ASSISTANT_QUESTION_MAX_CHARS = 500;
export const ASSISTANT_LOG_DAYS = 90;
/* News page rules (owner decision 2026-10-08, design/mockups/09-news/rationale.md). */
export const NEWS_MOVERS_MAX = 10;
export const NEWS_PAGE_SIZE = 10;
export const NEWS_RECENT_HOURS = 24;
/* The news analyst's sentiment (-1..1) reads flat between -0.05 and +0.05 (the Home page's convention). */
export const SENTIMENT_FLAT_BAND = 0.05;

/** Shown wherever no strategy is proven (the weekly review's model_skill is not true). */
export const NO_PROVEN_SIGNALS = "Not proven yet: these are tests, not tips.";
/** What "paper" means, on the Paper tag (docs/ux/plain_language_review.md section 2.0). */
export const PAPER_MEANS = "Paper = a record of what would have happened. No real money moves.";
/** The reference strategy the go-live numbers of every page belong to (rm_common.go_live), in words. */
export const REFERENCE_STRATEGY_WORDS = "The main rule strategy";
/** Why the app never says buy or sell (Home's verdict block and Help; docs/ux/plain_language_review.md section 1). */
export const WHY_NO_BUY_SELL = [
  "This app does not tell you when to buy or sell, and right now it cannot.",
  "Every strategy here is being tested on paper. Nothing has yet shown that it beats simply holding the market after costs, over enough trades and long enough to rule out luck.",
  "Until a strategy passes that test (the go-live bar), any “buy” here would be a guess dressed up as a signal.",
  "Even after a strategy passes, the app will show what the tested strategy would do and how well it has done, not instructions for your money. This is a personal research project, not investment advice.",
] as const;
/** The Help page's anchor of that section (the Home block and the assistant's decline link to it). */
export const WHY_NO_BUY_SELL_ANCHOR = "why-no-buy-sell";
/** What an expected value is (every "Expected" label's tooltip). */
export const EXPECTED_MEANS =
  "Not a loss or a gain. Nothing has happened yet. This is the average result we would expect from this trade, given its chance of going up, how far it might move, and the costs of buying and selling.";
/** The fallback Paper label when a payload carries none (the payloads' `status.paper_label` wins). */
export const PAPER_LABEL = "Paper only — no proven edge yet";
export const RESEARCH_ONLY = "Personal research project; nothing here is investment advice and nothing trades.";

export const MARKET_LABEL: Record<Market, string> = { india: "India", us: "US" };
/** Presentation only: the market's local clock label. */
export const MARKET_ZONE: Record<Market, string> = { india: "IST", us: "ET" };
export const LOCALE: Record<string, string> = { INR: "en-IN", USD: "en-US" };
export const CURRENCY_SYMBOL: Record<string, string> = { INR: "₹", USD: "$" };

export type Family = "rule" | "baseline" | "ai";
/** Family -> [plural label, icon, swatch class suffix]. */
export const FAMILY: Record<Family, readonly [string, string, string]> = {
  rule: ["Rule strategies", "settings", "r"],
  baseline: ["Baselines", "trending_flat", "b"],
  ai: ["AI traders", "bolt", "a"],
};
export const FAMILY_SHORT: Record<Family, string> = { rule: "Rule", baseline: "Baseline", ai: "AI" };
/** The label tone of each family (`.mb-label.<tone>`). */
export const FAMILY_TONE: Record<Family, string> = { rule: "", baseline: "warn", ai: "info" };
export const PICK_RULE: Record<string, string> = {
  best_expected_gain: "Biggest expected gain",
  highest_probability: "Highest chance",
};
/** Band -> [words, state class]. */
export const BAND: Record<string, readonly [string, string]> = {
  below80: ["below the 80% range", "flag"],
  below50: ["below the 50% range", ""],
  inside50: ["inside the 50% range", "ok"],
  above50: ["above the 50% range", ""],
  above80: ["above the 80% range", "flag"],
};
export const BAND_SHORT: Record<string, string> = {
  below80: "below 80%", below50: "below 50%", inside50: "inside 50%", above50: "above 50%", above80: "above 80%",
};
export const FLAG: Record<string, string> = {
  outside_range: "outside its range", far_from_target: "far from its target", against_prediction: "against the prediction",
};
export const FLAG_SHORT: Record<string, string> = {
  outside_range: "outside range", far_from_target: "far from target", against_prediction: "against prediction",
};
/** Verification status -> [word, explanation, icon or null] (DESIGN.md 3b). */
export const NEWS_STATUS: Record<string, readonly [string, string, string | null]> = {
  confirmed_primary: ["confirmed", "A primary document (exchange filing, company release) confirms it. Can be the main evidence of a call.", "verified_user"],
  corroborated: ["corroborated", "Two or more independent outlets reported it on their own. Can be the main evidence of a call.", "check"],
  single_source: ["single source", "One independent origin so far. Lowers a call’s confidence; cannot be the main evidence.", "warning"],
  unverified: ["unverified", "No vetted outlet read yet. Lowers confidence; cannot be the main evidence.", null],
  rumour: ["rumour", "Reported as a rumour or from unnamed sources. Never supports a call.", "close"],
  promotional: ["promotional", "A paid, promotional or opinion item. Never supports a call.", "close"],
  contradicted: ["contradicted", "A checked claim conflicts with a primary document. Can only widen a range.", "close"],
};
/** The statuses that can carry a call as its main evidence. */
export const CAN_CARRY = ["confirmed_primary", "corroborated"] as const;
export const REGIME_TIP = "How the whole market has behaved lately. Some strategies sit out the busy and jumpy days.";
/** The market mood (regime code) in words. */
export const REGIME_WORDS: Record<string, string> = {
  CALM: "calm", TRENDING: "trending", EVENT_HEAVY: "busy with events", UNSTABLE: "jumpy",
};
export const regimeWords = (code: string | null | undefined): string =>
  code ? REGIME_WORDS[code] ?? code.toLowerCase().replace(/_/g, " ") : "not known yet";
/** A story's materiality as the reader's word. */
export const importanceWords = (materiality: string | null | undefined): string =>
  `importance: ${materiality ?? "not scored"}`;
/** A calendar event's type in words (config/events.yaml types and the company events); others: underscores as spaces. */
export const EVENT_TYPE_WORDS: Record<string, string> = {
  earnings: "results", ex_dividend: "ex-dividend", budget: "budget", cpi: "inflation figures", fno_expiry: "options expiry",
  weekly_expiry: "weekly options expiry", opex: "options expiry", triple_witching: "quarterly options expiry",
  fomc: "US central-bank decision", rbi_policy: "RBI rate decision", jobs_report: "jobs report",
  index_rebalance: "index reshuffle",
};
export const eventTypeWords = (type: string): string => EVENT_TYPE_WORDS[type] ?? type.replace(/_/g, " ");
/** A command's refusal code as a sentence (mcp/tools.yaml refusal_codes and lifecycle/constants.py REFUSE_*). */
export const REFUSAL_WORDS: Record<string, string> = {
  not_allowed_in_channel: "This command is not allowed from this channel.",
  unknown_actor: "The sign-in could not be matched to the owner.",
  budget_exceeded: "Today’s limit for this kind of request is used up.",
  kill_switch: "This kind of request is switched off for now.",
  validation_failed: "The request did not pass its checks.",
  duplicate_key: "This request was already sent; it is recorded once.",
  ambiguous: "The request was unclear, so nothing was done.",
  etf: "This symbol is a fund (ETF), not a company.",
  bse_only: "This company trades only on BSE; the app follows NSE companies.",
  unknown_symbol: "This symbol was not found.",
  already_active: "This company is already on the list.",
  deleted_needs_new_add: "This company was deleted; add it again to follow it.",
};
export const refusalWords = (code: string): string => REFUSAL_WORDS[code] ?? code.replace(/_/g, " ");
