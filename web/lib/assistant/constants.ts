// The assistant's fixed settings (docs/SPEC.md F11; mcp/tools.yaml `explain`; design/mockups/_shared/shell.js holds the
// same numbers for the pages). Changing one is an owner decision: the budget figures are the spec's.
import { getTool } from "../tools/registry.ts";

/** F11: "calling the Claude API (Sonnet)"; mcp/tools.yaml explain budget.model: sonnet -> the current Sonnet. */
export const MODEL = "claude-sonnet-5-5";

/** USD per million tokens of MODEL (claude-api skill price table, cached 2026-10-06): input, 5-minute cache write
 * (1.25 x input), cache read, output. Thinking tokens are billed as output. */
export const PRICE_PER_MTOK = { input: 2.0, cache_write: 2.5, cache_read: 0.2, output: 10.0 } as const;

const explainTool = getTool("explain");
const explainBudget = (explainTool?.budget ?? {}) as { daily_usd?: number; monthly_usd_cap?: number };

/** Code-side caps (F11): about $0.65 a day and the $20 monthly hard cap, both enforced before every model call. */
export const DAILY_USD = explainBudget.daily_usd ?? 0.65;
export const MONTHLY_USD = explainBudget.monthly_usd_cap ?? 20;

/** mcp/tools.yaml explain question.max_length. */
export const QUESTION_MAX = explainTool?.inputs.question?.max_length ?? 500;

/** F11: conversations are kept 90 days in MotherDuck schema `app` (an operational log, not a fact store). */
export const RETENTION_DAYS = 90;

/** One question may cost at most this much; it is reserved against the day and month before the first model call. */
export const QUESTION_USD = 0.1;

/** Per model call: the most output (thinking included) one call may write. */
export const MAX_TOKENS = 1500;

/** At most this many model calls per question (the last one may not call tools) and tool calls in all. */
export const MAX_ROUNDS = 4;
export const MAX_TOOL_CALLS = 6;

/** No new model call starts after this long (the route's maxDuration is 60 s; one call has 25 s, no retry). */
export const DEADLINE_MS = 30000;
export const CALL_TIMEOUT_MS = 25000;

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
