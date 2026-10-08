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
export const NO_PROVEN_SIGNALS = "No proven strong signals today";
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
  best_expected_gain: "Best expected gain",
  highest_probability: "Highest probability",
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
export const REGIME_TIP =
  "Market mood stored by the daily run: CALM / TRENDING / EVENT_HEAVY / UNSTABLE. AI traders lower their probability in EVENT_HEAVY and UNSTABLE; rule strategies either filter those days or not.";
