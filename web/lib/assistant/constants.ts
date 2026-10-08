// The assistant's fixed settings (docs/SPEC.md F11; mcp/tools.yaml `explain`; design/mockups/_shared/shell.js holds the
// same numbers for the pages). Owner decision 2026-10-08: no money budget in code (the Anthropic console's workspace
// spend limit is the only one); every question's cost is logged and the spend shown.
import { getTool } from "../tools/registry.ts";

/** F11: "calling the Claude API (Sonnet)"; mcp/tools.yaml explain budget.model: sonnet -> the current Sonnet. */
export const MODEL = "claude-sonnet-5-5";

/** Refusal fallback (owner decision 2026-10-08: on). Pinned with the array form, not `"default"`, so its price is known
 * and the logged cost exact: Claude Sonnet 5, the model `"default"` routes Sonnet 5.5's cyber and frontier_llm declines to
 * (claude-api skill), at the same price as MODEL. */
export const FALLBACK_MODEL = "claude-sonnet-5";
export const FALLBACK_BETA = "server-side-fallback-2026-06-01";

export interface Price {
  input: number;
  cache_write: number;
  cache_read: number;
  output: number;
}

/** USD per million tokens (claude-api skill price table, cached 2026-10-06): input, 5-minute cache write (1.25 x input),
 * cache read, output. Thinking tokens are billed as output. */
export const PRICES: Record<string, Price> = {
  [MODEL]: { input: 2.0, cache_write: 2.5, cache_read: 0.2, output: 10.0 },
  [FALLBACK_MODEL]: { input: 2.0, cache_write: 2.5, cache_read: 0.2, output: 10.0 },
};

/** Any other model an attempt reports is logged at the dearest listed price (Claude Fable 5.1: $10 / $50; its cache
 * write at 1.25 x and its cache read at 0.1 x input, both rounded up), so an unexpected model never under-counts. */
export const UNKNOWN_MODEL_PRICE: Price = { input: 10.0, cache_write: 12.5, cache_read: 1.0, output: 50.0 };

const explainTool = getTool("explain");

/** mcp/tools.yaml explain question.max_length. */
export const QUESTION_MAX = explainTool?.inputs.question?.max_length ?? 500;

/** F11: conversations are kept 90 days in MotherDuck schema `app` (an operational log, not a fact store). */
export const RETENTION_DAYS = 90;

/** Per model call: the most output (thinking included) one call may write. */
export const MAX_TOKENS = 1500;

/** At most this many model calls per question (the last one may not call tools) and tool calls in all. */
export const MAX_ROUNDS = 4;
export const MAX_TOOL_CALLS = 6;

/** Counted from the question's arrival: no model call starts and no read runs after DEADLINE_MS; one call has
 * CALL_TIMEOUT_MS and no retry. So the model work ends within 25 + 20 = 45 s of arrival; the closing log statements
 * (answer, spend; each under B5's 5 s statement timeout) and the tool layer's command-log row follow, against the
 * route's 60 s maxDuration. A log slower than that can still be cut off: the question then stays "pending". */
export const DEADLINE_MS = 25000;
export const CALL_TIMEOUT_MS = 20000;

/** Multi-turn (owner decision 2026-10-08): a question carries at most the last HISTORY_TURNS finished questions and
 * answers of its conversation, as plain text, each answer cut to HISTORY_ANSWER_CHARS (a question is at most
 * QUESTION_MAX). So the history adds at most 4 x (500 + 1000) = 6,000 characters of quoted text to a request, plus about
 * 80 characters of framing per turn (about 6,400 in all). */
export const HISTORY_TURNS = 4;
export const HISTORY_ANSWER_CHARS = 1000;

/** Slack /ask cannot pass a conversation id, so it continues the asker's latest conversation in the market when that
 * conversation's last question is this recent. */
export const SLACK_CONVERSATION_MINUTES = 30;

/** A conversation id: the id of its first question. */
export const CONVERSATION_PATTERN = /^ask-(india|us)-\d{4}-\d{2}-\d{2}-[0-9a-f]{10}$/;

/** A read tool's result is cut to this many characters before the model sees it (it is told so). */
export const TOOL_RESULT_MAX_CHARS = 16000;

/** The read tools the assistant may use (mcp/agents/assistant.yaml), in a fixed order so the prompt prefix is stable. */
export const READ_TOOLS = [
  "get_overview", "get_company", "get_scoreboard", "compare_rule_vs_ai", "get_news", "get_trades",
] as const;

/** Record kinds a citation may name (docs/DATA_CATALOGUE.md); the page links each kind to the page where it lives. */
export const CITED_KINDS = [
  "paper_trades_settled", "strategy_predictions", "head_to_head_picks", "trade_checks", "trade_reasons_ai",
  "eod_analyses", "research_reviews", "news", "news_impact", "results_digests", "filings", "announcements", "events",
  "model_scores", "ranges", "scoreboard", "market_status", "company", "record",
] as const;
export type CitedKind = (typeof CITED_KINDS)[number];

/** The agent whose kill switch (mcp/agents/assistant.yaml enabled; inbox.controls) stops every answer. */
export const AGENT = "assistant";
