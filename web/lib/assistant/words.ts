// Plain words for an answer's state and its cited record kinds (shared by Slack, the panel and page 11; the mockup's
// presentation rules, design/mockups/11-assistant/notes.md).
import type { AnswerRecord } from "./types.ts";

const KIND_WORDS: Record<string, string> = {
  paper_trades_settled: "settled paper trade",
  strategy_predictions: "paper prediction",
  head_to_head_picks: "head-to-head pick",
  trade_checks: "intraday trade check",
  trade_reasons_ai: "AI trade reason",
  eod_analyses: "end-of-day analysis",
  research_reviews: "weekly research review",
  news: "news item",
  news_impact: "news-impact row",
  results_digests: "results digest",
  filings: "filing",
  announcements: "exchange announcement",
  events: "calendar event",
  model_scores: "signal-model score",
  ranges: "price range",
  scoreboard: "scoreboard row",
  market_status: "market status",
  company: "company record",
  record: "stored record",
};

export function kindWords(kind: string): string {
  return KIND_WORDS[kind] ?? "stored record";
}

export function stateWords(answer: Pick<AnswerRecord, "status" | "declined">): string {
  switch (answer.status) {
    case "answered":
      return "Answered from the data";
    case "not_in_data":
      return "Not in the data";
    case "declined":
      return answer.declined === "advice" ? "Declined: no advice on real trades" : "Declined";
    case "stopped":
      return "Stopped: out of time for one answer";
    case "pending":
      return "Not finished";
    default:
      return "Failed";
  }
}

/** The page a cited record's kind lives on (lib/ui/routes.ts page keys); the mockup's map, with news on the News page. */
const KIND_PAGE: Record<string, string> = {
  paper_trades_settled: "portfolios",
  trade_reasons_ai: "compare",
  eod_analyses: "compare",
  head_to_head_picks: "compare",
  research_reviews: "compare",
  strategy_predictions: "lab",
  scoreboard: "lab",
  model_scores: "lab",
  news: "news",
  news_impact: "news",
  announcements: "news",
  filings: "news",
  events: "news",
  results_digests: "news",
  trade_checks: "portfolios",
  ranges: "watchlist",
  market_status: "home",
  company: "companies",
};

export function kindPage(kind: string): string {
  return KIND_PAGE[kind] ?? "help";
}

/** The icon of a cited record's kind (design/system/icons.svg ids without ms-). */
export function kindIcon(kind: string): string {
  const page = kindPage(kind);
  return ({ portfolios: "account_balance_wallet", compare: "layers", lab: "science", news: "newspaper", watchlist: "format_list_bulleted", home: "home", companies: "apartment" } as Record<string, string>)[page] ?? "description";
}
