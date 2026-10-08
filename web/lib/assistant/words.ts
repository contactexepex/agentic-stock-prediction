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
      return "Stopped: too much to read for one answer";
    case "pending":
      return "Not finished";
    default:
      return "Failed";
  }
}
