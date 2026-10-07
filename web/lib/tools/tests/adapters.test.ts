import { test } from "node:test";
import assert from "node:assert/strict";
import { allowlistedFetch } from "../http.ts";
import { GithubDispatcher } from "../dispatch.ts";
import { SlackOwnerNotifier, ownerReportText } from "../notify.ts";
import { YahooSecResolver } from "../resolver.ts";
import { MotherDuckInboxStore, MotherDuckReadStore } from "../motherduck.ts";
import { redact } from "../text.ts";

type Call = { url: string; init?: RequestInit };
function recorder(answer: (url: string) => Response) {
  const calls: Call[] = [];
  const fetcher = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return answer(url);
  };
  return { calls, fetcher };
}

test("outbound fetch is limited to the HTTPS allowlist", async () => {
  const { calls, fetcher } = recorder(() => new Response("{}"));
  const safe = allowlistedFetch(fetcher);
  await safe("https://slack.com/api/views.open");
  for (const url of ["http://slack.com/api", "https://evil.example.com/", "https://slack.com.evil.example/", "https://user:pw@slack.com/"]) {
    await assert.rejects(() => safe(url), /allowlist/);
  }
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init?.redirect, "error");
});

test("the dispatch posts workflow_dispatch of onboard.yml on main with the token only in the header", async () => {
  const { calls, fetcher } = recorder(() => new Response(null, { status: 204 }));
  const dispatcher = new GithubDispatcher({ token: "github_pat_TOKEN123", repository: "contactexepex/agentic-stock-prediction", workflow: "onboard.yml", ref: "main" }, fetcher);
  assert.deepEqual(await dispatcher.dispatch(), { ok: true, reason: null });
  assert.equal(calls[0].url, "https://api.github.com/repos/contactexepex/agentic-stock-prediction/actions/workflows/onboard.yml/dispatches");
  assert.equal(calls[0].init?.body, JSON.stringify({ ref: "main" }));
  assert.equal((calls[0].init?.headers as Record<string, string>).Authorization, "Bearer github_pat_TOKEN123");
  const missing = new GithubDispatcher({ token: null, repository: "a/b", workflow: "onboard.yml", ref: "main" }, fetcher);
  assert.equal((await missing.dispatch()).ok, false);
  const refused = new GithubDispatcher({ token: "t", repository: "a/b", workflow: "onboard.yml", ref: "main" }, async () => new Response("", { status: 422 }));
  assert.deepEqual(await refused.dispatch(), { ok: false, reason: "GitHub answered 422" });
});

test("the owner report is a DM, escaped so user text cannot ping or link", async () => {
  const { calls, fetcher } = recorder(() => Response.json({ ok: true }));
  const notifier = new SlackOwnerNotifier("xoxb-test", "U0OWNER01", fetcher);
  const report = { command_id: "cmd-1", tool: "add_company", channel: "slack" as const, actor: "slack:U07ABCD123",
    result: "refused" as const, refusal_code: "validation_failed" as const, message: "<!channel> see <https://evil.example|here>" };
  assert.equal(await notifier.notify(report), true);
  const body = JSON.parse(String(calls[0].init?.body));
  assert.equal(body.channel, "U0OWNER01");
  assert.doesNotMatch(body.text, /<!channel>|<https/);
  assert.match(ownerReportText(report), /&lt;!channel&gt;/);
  assert.equal(await new SlackOwnerNotifier(null, "U0OWNER01", fetcher).notify(report), false);
});

const yahoo = (quotes: unknown[]) => Response.json({ quotes });
const secMap = Response.json({ fields: ["cik", "name", "ticker", "exchange"], data: [[789019, "MICROSOFT CORP", "MSFT", "Nasdaq"], [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"]] });

test("the resolver previews a US stock with its CIK and refuses ETFs and other exchanges", async () => {
  const { fetcher } = recorder((url) => url.includes("sec.gov") ? secMap.clone() : yahoo([
    { symbol: "MSFT", longname: "Microsoft Corporation", exchange: "NMS", quoteType: "EQUITY", sectorDisp: "Technology" },
  ]));
  const resolved = await new YahooSecResolver(fetcher, "market-brief research").resolve("us", "MSFT", null);
  assert.deepEqual(resolved, { ok: true, preview: { market: "us", symbol: "MSFT", name: "Microsoft Corporation", exchange: "NASDAQ",
    sector: "Technology", yahoo: "MSFT", nse_symbol: null, cik: "0000789019", amount: 1000, amount_is_default: true, currency: "USD" } });
  const brk = recorder((url) => url.includes("sec.gov") ? secMap.clone() : yahoo([{ symbol: "BRK-B", longname: "Berkshire Hathaway Inc.", exchange: "NYQ", quoteType: "EQUITY" }]));
  const berkshire = await new YahooSecResolver(brk.fetcher, "ua").resolve("us", "BRK.B", 2000);
  assert.equal(berkshire.ok && berkshire.preview.cik, "0001067983");
  assert.equal(berkshire.ok && berkshire.preview.amount, 2000);
  const etf = recorder(() => yahoo([{ symbol: "SPY", longname: "SPDR S&P 500 ETF Trust", exchange: "PCX", quoteType: "ETF" }]));
  assert.deepEqual(await new YahooSecResolver(etf.fetcher, null).resolve("us", "SPY", null),
    { ok: false, code: "validation_failed", message: "SPY is an ETF; only common stocks can be added" });
  const otc = recorder(() => yahoo([{ symbol: "ABCD", longname: "Abcd Inc", exchange: "PNK", quoteType: "EQUITY" }]));
  assert.equal((await new YahooSecResolver(otc.fetcher, null).resolve("us", "ABCD", null)).ok, false);
});

test("the resolver previews an NSE stock and refuses BSE-only symbols", async () => {
  const nse = recorder(() => yahoo([{ symbol: "HDFCBANK.NS", longname: "HDFC Bank Limited", exchange: "NSI", quoteType: "EQUITY", sector: "Financial Services" }]));
  const resolved = await new YahooSecResolver(nse.fetcher, null).resolve("india", "HDFCBANK", null);
  assert.equal(resolved.ok && resolved.preview.exchange, "NSE");
  assert.equal(resolved.ok && resolved.preview.nse_symbol, "HDFCBANK");
  assert.equal(resolved.ok && resolved.preview.amount, 100000);
  assert.equal(nse.calls.some((call) => call.url.includes("sec.gov")), false);
  const bse = recorder(() => yahoo([{ symbol: "ABCLTD.BO", longname: "Abc Ltd", exchange: "BSE", quoteType: "EQUITY" }]));
  assert.deepEqual(await new YahooSecResolver(bse.fetcher, null).resolve("india", "ABCLTD", null),
    { ok: false, code: "validation_failed", message: "ABCLTD is listed on BSE only; only NSE stocks can be added" });
});

test("MotherDuck stores send one parameterised statement per read and never take a table name from input", async () => {
  const seen: { text: string; values: unknown[] }[] = [];
  const query = async (text: string, values: unknown[]) => {
    seen.push({ text, values });
    return { rows: [{ market: "us", page_key: "_", as_of: new Date("2026-10-07T01:00:00Z"), cutoff: null, built_at: null,
      schema_version: "1", source_commit: null, payload_sha256: null, payload: "{\"a\":1}" }] };
  };
  const store = new MotherDuckReadStore(query);
  const row = await store.readModel("home", "us", "_");
  assert.deepEqual(row?.payload, { a: 1 });
  assert.equal(row?.as_of, "2026-10-07T01:00:00.000Z");
  assert.match(seen[0].text, /FROM rm\.home WHERE market = \$1 AND page_key = \$2$/);
  assert.deepEqual(seen[0].values, ["us", "_"]);
  await assert.rejects(() => store.readModel("home; DROP TABLE x", "us", "_"), /unknown read model/);
});

test("the inbox store claims a key once with ON CONFLICT DO NOTHING and reads the existing row otherwise", async () => {
  const statements: string[] = [];
  let inserted = false;
  const query = async (text: string) => {
    statements.push(text);
    if (text.startsWith("INSERT INTO inbox.requests")) {
      const rows = inserted ? [] : [{ inbox_id: "k" }];
      inserted = true;
      return { rows };
    }
    return { rows: [{ inbox_id: "key-000001", kind: "watchlist_events", tool: "reactivate_company", market: "us", arguments: "{}",
      preview: null, channel: "slack", submitted_by: "slack:U1", agent: "slack-gateway", command_id: "cmd-1",
      submitted_at: "2026-10-07T10:00:00Z", args_sha256: "f".repeat(64) }] };
  };
  const inbox = new MotherDuckInboxStore(query);
  const row = { inbox_id: "key-000001", kind: "watchlist_events", tool: "reactivate_company", market: "us", arguments: {}, preview: null,
    channel: "slack" as const, submitted_by: "slack:U1", agent: "slack-gateway", command_id: "cmd-1", submitted_at: "2026-10-07T10:00:00Z", args_sha256: "f".repeat(64) };
  assert.deepEqual(await inbox.claimRequest(row), { claimed: true, existing: null });
  const again = await inbox.claimRequest(row);
  assert.equal(again.claimed, false);
  assert.equal(again.existing?.command_id, "cmd-1");
  assert.match(statements[0], /ON CONFLICT \(inbox_id\) DO NOTHING RETURNING inbox_id$/);
});

test("redaction removes configured secrets and common token shapes", () => {
  const text = redact("a md-SECRET-value-123 b xoxb-12345-67890-abcdefghij c ghp_abcdefghijklmnopqrstuvwxyz1234 d sk-ant-api03-abcdefghijk", ["md-SECRET-value-123"]);
  assert.equal(text, "a [redacted] b [redacted] c [redacted] d [redacted]");
});
