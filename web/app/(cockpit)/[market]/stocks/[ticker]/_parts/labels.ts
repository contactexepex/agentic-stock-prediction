// Words of the company page (design/mockups/03-company/template.html): the automatic reason codes of a settled trade
// (F1.10, decision 43), the calendar event types and the kinds of the EOD analyst's notes. Presentation only.

/** Reason code -> [short words, explanation]. */
export const REASON: Record<string, readonly [string, string]> = {
  market_up: ["market lift", "The market explains most of the move (beta × benchmark move)."],
  market_down: ["market drag", "The market explains most of the move (beta × benchmark move)."],
  sector_lift: ["sector lift", "The sector moved beyond the market."],
  sector_drag: ["sector drag", "The sector moved beyond the market."],
  news_positive: ["news", "Verified news inside the window with the same sign as the rest of the move."],
  news_negative: ["news", "Verified news inside the window with the same sign as the rest of the move."],
  company_specific: ["company specific", "What is left after market, sector and news."],
  target_reached: ["target reached", "A high in the window reached the target."],
  range_missed: ["range missed", "The exit close fell outside the 80% range."],
};
export const reasonWords = (code: string | null | undefined): readonly [string, string] =>
  code ? REASON[code] ?? [code.replace(/_/g, " "), ""] : ["not given", ""];

/** Calendar event type -> words. */
export const EVENT_TYPE: Record<string, string> = {
  rbi_policy: "RBI policy", fomc: "Fed decision", cpi: "US inflation (CPI)", jobs_report: "US jobs report",
  fno_expiry: "F&O expiry", weekly_expiry: "weekly expiry", opex: "options expiry", triple_witching: "triple witching",
  index_rebalance: "index rebalance", budget: "budget", earnings: "results", ex_dividend: "ex-dividend",
  holiday: "market closed",
};
export const eventWords = (type: string) => EVENT_TYPE[type] ?? type;

/** EOD analyst note kind -> [words, label tone]. */
export const NOTE_KIND: Record<string, readonly [string, "info" | "success" | "warn" | "neutral"]> = {
  head_to_head: ["Head-to-head", "info"], biggest_win: ["Biggest win", "success"], biggest_miss: ["Biggest miss", "warn"],
};

export const plural = (n: number, one: string, many = one + "s") => (n === 1 ? one : many);
