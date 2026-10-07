// In-memory MotherDuck, GitHub, Slack and resolver fakes for the offline tests. Nothing here reaches the network.
import { ToolLayer } from "../executor.ts";
import type {
  AgentUsage, CommandLogRow, CompanyPreview, CompanyResolver, Dispatcher, InboxRequest, InboxStore, OwnerNotifier,
  OwnerReport, ReadModelRow, ReadStore, ResolveResult, ToolSettings,
} from "../types.ts";
import type { SlackApi } from "../../../app/slack/_lib/api.ts";
import type { SlackDeps } from "../../../app/slack/_lib/commands.ts";

export const SECRETS = {
  MOTHERDUCK_READ_TOKEN: "md-read-SECRET-1234567890",
  MOTHERDUCK_INBOX_TOKEN: "md-inbox-SECRET-0987654321",
  GITHUB_DISPATCH_TOKEN: "github_pat_SECRETSECRETSECRET123456",
  SLACK_SIGNING_SECRET: "slack-signing-SECRET-abcdef",
  SLACK_BOT_TOKEN: "xoxb-1111-2222-SECRETSECRET",
  GITHUB_OAUTH_CLIENT_SECRET: "gh-oauth-client-SECRET-xyz",
  SESSION_SECRET: "session-secret-at-least-32-characters-long-SECRET",
};
export const SECRET_VALUES = Object.values(SECRETS);

export class FakeInbox implements InboxStore {
  /** One list for both inbox tables (company_commands and requests): keys are unique across both, and the budget counts
   * both, as in the real claim statements; tests/test_b5_tools.py checks the two-table SQL on DuckDB. */
  requests: InboxRequest[] = [];
  commands: CommandLogRow[] = [];
  /** Rows in insertion order = updated_at order; like the real SQL, the newest row per agent (and per '*') counts. */
  controls: { agent: string; enabled: boolean }[] = [];
  down = false;
  failAppend = false;

  async usage(agent: string, sinceIso: string): Promise<AgentUsage> {
    if (this.down) throw new Error(`connection to pg failed password=${SECRETS.MOTHERDUCK_INBOX_TOKEN}`);
    const writes = this.requests.filter((row) => row.agent === agent && row.submitted_at >= sinceIso).length;
    const reads = this.commands.filter((row) => row.agent === agent && (row.kind === "read" || row.kind === "read_ai") &&
      row.received_at >= sinceIso).length;
    const newest = new Map<string, boolean>();
    for (const row of this.controls) if (row.agent === agent || row.agent === "*") newest.set(row.agent, row.enabled);
    return { writes, reads, enabled: newest.size ? [...newest.values()].every(Boolean) : null };
  }

  async claimRequest(row: InboxRequest, budget: { sinceIso: string; limit: number }) {
    if (this.down) throw new Error("inbox down");
    const existing = this.requests.find((item) => item.inbox_id === row.inbox_id) ?? null;
    if (existing) return { claimed: false, existing };
    const used = this.requests.filter((item) => item.agent === row.agent && item.submitted_at >= budget.sinceIso).length;
    if (used >= budget.limit) return { claimed: false, existing: null };
    this.requests.push(structuredClone(row));
    return { claimed: true, existing: null };
  }

  async appendCommand(row: CommandLogRow) {
    if (this.failAppend) throw new Error("append failed");
    this.commands.push(structuredClone(row));
  }

  async findCommand(id: string) {
    return this.commands.find((row) => row.id === id) ?? null;
  }
}

export class FakeReadStore implements ReadStore {
  rows = new Map<string, ReadModelRow>();
  calls: string[] = [];
  error: Error | null = null;

  put(table: string, market: string, pageKey: string, payload: unknown) {
    this.rows.set(`${table}|${market}|${pageKey}`, {
      market, page_key: pageKey, as_of: "2026-10-07T01:00:00Z", cutoff: "2026-10-07T01:00:00Z", built_at: "2026-10-07T01:05:00Z",
      schema_version: "1", source_commit: "abc1234", payload_sha256: "0".repeat(64), payload,
    });
  }

  async readModel(table: string, market: string, pageKey: string) {
    this.calls.push(`${table}|${market}|${pageKey}`);
    if (this.error) throw this.error;
    return this.rows.get(`${table}|${market}|${pageKey}`) ?? null;
  }
}

export class FakeDispatcher implements Dispatcher {
  calls = 0;
  fail = false;
  async dispatch() {
    this.calls += 1;
    return this.fail ? { ok: false, reason: "GitHub answered 500" } : { ok: true, reason: null };
  }
}

export class FakeNotifier implements OwnerNotifier {
  reports: OwnerReport[] = [];
  async notify(report: OwnerReport) {
    this.reports.push(structuredClone(report));
    return true;
  }
}

export const MSFT: CompanyPreview = {
  market: "us", symbol: "MSFT", name: "Microsoft Corporation", exchange: "NASDAQ", sector: "Technology", yahoo: "MSFT",
  nse_symbol: null, cik: "0000789019", amount: 1000, amount_is_default: true, currency: "USD",
};

export class FakeResolver implements CompanyResolver {
  calls: string[] = [];
  answers = new Map<string, ResolveResult>([
    ["us:MSFT", { ok: true, preview: MSFT }],
    ["us:SPY", { ok: false, code: "validation_failed", message: "SPY is an ETF; only common stocks can be added" }],
  ]);
  async resolve(market: "india" | "us", symbol: string, amount: number | null): Promise<ResolveResult> {
    this.calls.push(`${market}:${symbol}`);
    const answer = this.answers.get(`${market}:${symbol}`);
    if (!answer) return { ok: false, code: "validation_failed", message: `${symbol} was not found` };
    if (answer.ok && amount !== null) return { ok: true, preview: { ...answer.preview, amount, amount_is_default: false } };
    return answer;
  }
}

export interface Rig {
  layer: ToolLayer;
  inbox: FakeInbox;
  reads: FakeReadStore;
  dispatcher: FakeDispatcher;
  notifier: FakeNotifier;
  resolver: FakeResolver;
  now: { value: Date };
}

export function rig(settings: Partial<ToolSettings> = {}): Rig {
  const inbox = new FakeInbox();
  const reads = new FakeReadStore();
  const dispatcher = new FakeDispatcher();
  const notifier = new FakeNotifier();
  const resolver = new FakeResolver();
  const now = { value: new Date("2026-10-07T10:00:00Z") };
  const layer = new ToolLayer({
    readStore: reads, inbox, dispatcher, notifier, resolver, clock: () => now.value,
    settings: { gatewayMode: true, secrets: SECRET_VALUES, ...settings },
  });
  return { layer, inbox, reads, dispatcher, notifier, resolver, now };
}

export class FakeSlack implements SlackApi {
  opened: { triggerId: string; view: any }[] = [];
  updated: { viewId: string; view: any }[] = [];
  responses: { url: string; body: any }[] = [];
  posts: { channel: string; text: string; ts: string }[] = [];
  edits: { channel: string; ts: string; text: string }[] = [];
  postFails = false;
  async viewsOpen(triggerId: string, view: unknown) {
    this.opened.push({ triggerId, view });
    return true;
  }
  async viewsUpdate(viewId: string, view: unknown) {
    this.updated.push({ viewId, view });
    return true;
  }
  async respond(url: string, body: unknown) {
    this.responses.push({ url, body });
    return true;
  }
  async postMessage(channel: string, text: string) {
    if (this.postFails) return null;
    const ts = `1791400000.${String(this.posts.length + 1).padStart(6, "0")}`;
    this.posts.push({ channel, text, ts });
    return ts;
  }
  async updateMessage(channel: string, ts: string, text: string) {
    this.edits.push({ channel, ts, text });
    return true;
  }
}

export const CHANNEL = "C0C6REB7QS2";
export const USER = "U07ABCD123";

export function slackRig(settings: Partial<ToolSettings> = {}) {
  const base = rig(settings);
  const slack = new FakeSlack();
  const deferred: Promise<void>[] = [];
  let counter = 0;
  const deps: SlackDeps = {
    tools: base.layer, slack, channelId: CHANNEL,
    defer: (task) => { deferred.push(task()); },
    newKey: () => `slk-testkey${String(++counter).padStart(4, "0")}`,
  };
  const settle = async () => {
    while (deferred.length) await deferred.shift();
  };
  return { ...base, slack, deps, settle };
}

export function commandParams(command: string, text: string, overrides: Record<string, string> = {}) {
  return new URLSearchParams({
    command, text, user_id: USER, channel_id: CHANNEL, trigger_id: "trig.123",
    response_url: "https://hooks.slack.com/commands/T0/1/abc", ...overrides,
  });
}

/** Every string a test can observe, to scan for secrets. */
export function observable(...values: unknown[]): string {
  return JSON.stringify(values);
}
