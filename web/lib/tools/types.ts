// Types of the governed tool layer (docs/SPEC.md F10; mcp/tools.yaml; ARCHITECTURE.md section 10).
// Research only: no tool places, routes or simulates a broker order; paper trades are records.

export type Channel = "dashboard" | "slack" | "claude_code" | "claude_app";
export type ToolKind = "read" | "read_ai" | "write";
export type CommandResult = "accepted" | "pending" | "refused" | "duplicate" | "failed";
export type RefusalCode =
  | "not_allowed_in_channel"
  | "unknown_actor"
  | "budget_exceeded"
  | "kill_switch"
  | "validation_failed"
  | "duplicate_key"
  | "ambiguous";

export interface InputSpec {
  type: string | string[];
  enum?: (string | number)[];
  pattern?: string;
  required?: boolean;
  default?: unknown;
  description?: string;
  max_length?: number;
  minimum?: number;
  exclusive_minimum?: number;
  format?: string;
}

export interface ToolDefinition {
  name: string;
  kind: ToolKind;
  description: string;
  inputs: Record<string, InputSpec>;
  output?: unknown;
  confirm?: "summary" | "typed";
  writes?: string[];
  validator?: string;
  refuses?: string[];
  uses_tools?: string[];
  budget?: unknown;
  channels: Record<Channel, boolean | string>;
}

export interface AgentDefinition {
  agent: string;
  channels: Channel[];
  enabled: boolean;
  tools: string[];
  daily_write_budget: number;
  daily_read_budget: number;
  fail_to: string;
}

/** Who is calling, set only by a channel adapter from the channel's own authentication (identity.ts). */
export interface CallContext {
  readonly channel: Channel;
  readonly actor: string;
  readonly agent: string;
}

export type ToolArgs = Record<string, unknown>;

/** Identifiers resolved for an add request, shown to the caller before Confirm (F8.7). */
export interface CompanyPreview {
  market: "india" | "us";
  symbol: string;
  name: string;
  exchange: string;
  sector: string | null;
  yahoo: string;
  nse_symbol: string | null;
  cik: string | null;
  amount: number;
  amount_is_default: boolean;
  currency: "INR" | "USD";
}

export interface ToolOutcome {
  command_id: string;
  tool: string | null;
  result: CommandResult;
  refusal_code: RefusalCode | null;
  message: string | null;
  data?: unknown;
  record_ids: string[];
  inbox_id: string | null;
  budget_left: number | null;
}

export interface PreviewOutcome {
  ok: boolean;
  outcome?: ToolOutcome;          // set when refused (logged and reported)
  summary?: string;               // plain words, set when ok
  preview?: CompanyPreview | null; // add_company only
  args?: ToolArgs;                // the validated arguments
}

export interface CommandLogRow {
  id: string;
  market: string | null;
  received_at: string;
  channel: Channel;
  actor: string;
  agent: string;
  tool: string | null;
  kind: ToolKind | null;
  arguments: unknown;
  idempotency_key: string | null;
  result: CommandResult;
  refusal_code: RefusalCode | null;
  message: string | null;
  record_ids: string[];
  budget_left: number | null;
  completed_at: string;
}

/** What the tool layer compares when a key is already stored (either inbox table). */
export interface StoredRequest {
  inbox_id: string;
  tool: string;
  submitted_by: string;
  command_id: string;
  args_sha256: string;
}

/** One write request. kind watchlist_events -> inbox.company_commands (B1's importer; submitted_by is its actor
 * column); kind portfolio_trades -> inbox.requests (B2's `portfolio.py import-inbox`). */
export interface InboxRequest {
  inbox_id: string;
  kind: string;
  tool: string;
  market: string;
  arguments: ToolArgs;
  preview: CompanyPreview | null;
  channel: Channel;
  submitted_by: string;
  agent: string;
  command_id: string;
  submitted_at: string;
  args_sha256: string;
  /** The Slack message the onboarding reply threads under (slack channel only), else null. */
  slack_channel: string | null;
  slack_ts: string | null;
}

export interface ReadModelRow {
  market: string;
  page_key: string;
  as_of: string | null;
  cutoff: string | null;
  built_at: string | null;
  schema_version: string | null;
  source_commit: string | null;
  payload_sha256: string | null;
  payload: unknown;
}

export interface AgentUsage {
  writes: number;
  reads: number;
  /** false when the inbox `controls` table switched the agent (or '*') off; null when no row. */
  enabled: boolean | null;
}

export interface ReadStore {
  readModel(table: string, market: string, pageKey: string): Promise<ReadModelRow | null>;
}

export interface InboxStore {
  usage(agent: string, sinceIso: string): Promise<AgentUsage>;
  /** Inserts the request in one statement unless its inbox_id exists or the agent already has `limit` requests since
   * `sinceIso`. Not claimed: `existing` is the stored row of that key, or null when the day budget was the reason. */
  claimRequest(row: InboxRequest, budget: { sinceIso: string; limit: number }): Promise<{ claimed: boolean; existing: StoredRequest | null }>;
  appendCommand(row: CommandLogRow): Promise<void>;
  findCommand(id: string): Promise<CommandLogRow | null>;
}

export interface Dispatcher {
  dispatch(): Promise<{ ok: boolean; reason: string | null }>;
}

export interface OwnerReport {
  command_id: string;
  tool: string | null;
  channel: Channel;
  actor: string;
  result: CommandResult;
  refusal_code: RefusalCode | null;
  message: string | null;
}

export interface OwnerNotifier {
  notify(report: OwnerReport): Promise<boolean>;
}

export type ResolveResult =
  | { ok: true; preview: CompanyPreview }
  | { ok: false; code: "validation_failed" | "ambiguous"; message: string };

export interface CompanyResolver {
  resolve(market: "india" | "us", symbol: string, amount: number | null): Promise<ResolveResult>;
}

export interface ToolSettings {
  /** MB_GATEWAY=1: the dashboard channel is refused (it is only served behind Vercel Authentication). */
  gatewayMode: boolean;
  /** Secret values to scrub from every message, log row and report. */
  secrets: string[];
}

export interface ToolDeps {
  readStore: ReadStore;
  inbox: InboxStore;
  dispatcher: Dispatcher;
  notifier: OwnerNotifier;
  resolver: CompanyResolver;
  clock: () => Date;
  settings: ToolSettings;
}

export interface ExecuteOptions {
  /** The caller confirmed the summary of a `confirm: summary` tool (Slack Confirm, MCP confirmation token, dashboard). */
  confirmedSummary?: boolean;
  /** The preview the caller confirmed (add_company). */
  preview?: CompanyPreview | null;
  /** Slack only: the visible "request received" message the confirm step posted in #market-brief; stored with the
   * request so B6's onboarding confirmation replies in its thread (docs/ws/b6.md, "Function for B5 and B1"). */
  slackThread?: { channel: string; ts: string } | null;
}
