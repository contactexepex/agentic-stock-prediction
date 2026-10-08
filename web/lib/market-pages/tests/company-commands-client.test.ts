// The Companies dialogs' client against a fake fetch: one key on both calls, the summary sent back verbatim, the stale
// summary and refusals told apart.
import { test } from "node:test";
import assert from "node:assert/strict";
import { newIdempotencyKey, previewCommand, refusalWords, STALE_SUMMARY, submitCommand, type CommandPreview } from "../company-commands-client.ts";

type Call = { url: string; init: RequestInit };
function fakeFetch(replies: [number, unknown][]): { fetcher: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetcher = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const [status, body] = replies.shift() ?? [500, null];
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { fetcher, calls };
}
const receipt = (result: string, message: string | null = null) => ({ command_id: "c1", result, refusal_code: null, message, inbox_id: null, record_ids: [], budget_left: 3, paper: true });
const preview: CommandPreview = { tool: "delete_company", summary: "Delete TCS for good", preview: null, arguments: { ticker: "TCS", confirm: "TCS" }, paper: true };

test("the key fits the routes' pattern", () => {
  assert.match(newIdempotencyKey(), /^[A-Za-z0-9_-]{8,64}$/);
  assert.equal(newIdempotencyKey(() => "1234-abcd"), "dash-1234abcd");
});

test("preview then submit send one key and the summary verbatim", async () => {
  const { fetcher, calls } = fakeFetch([[200, preview], [202, receipt("pending")]]);
  const p = await previewCommand("india", "dash-key00001", "delete_company", { ticker: "TCS", confirm: "TCS" }, fetcher);
  assert.ok(p.ok);
  const s = await submitCommand("india", "dash-key00001", p.ok ? p.preview : preview, fetcher);
  assert.equal(s.kind, "recorded");
  assert.deepEqual(calls.map((c) => c.url), ["/api/v1/markets/india/companies/preview", "/api/v1/markets/india/companies/commands"]);
  for (const c of calls) assert.equal((c.init.headers as Record<string, string>)["idempotency-key"], "dash-key00001");
  assert.deepEqual(JSON.parse(String(calls[1].init.body)), { tool: "delete_company", arguments: { ticker: "TCS", confirm: "TCS" }, confirmed_summary: "Delete TCS for good" });
});

test("a duplicate is recorded; a stale summary and refusals are told apart", async () => {
  assert.equal((await submitCommand("us", "k".repeat(8), preview, fakeFetch([[200, receipt("duplicate")]]).fetcher)).kind, "recorded");
  assert.equal((await submitCommand("us", "k".repeat(8), preview, fakeFetch([[422, receipt("refused", STALE_SUMMARY)]]).fetcher)).kind, "stale");
  const refused = await submitCommand("us", "k".repeat(8), preview, fakeFetch([[422, receipt("refused", "AMZN is an ETF")]]).fetcher);
  assert.equal(refused.kind, "refused");
  assert.equal(refusalWords(422, refused.kind === "refused" ? refused.receipt : null), "AMZN is an ETF");
  const p = await previewCommand("us", "k".repeat(8), "add_company", { symbol: "SPY" }, fakeFetch([[429, receipt("refused")]]).fetcher);
  assert.deepEqual(p.ok ? null : [p.status, refusalWords(p.status, p.receipt)], [429, "Today's budget for changes is used up."]);
  assert.equal(refusalWords(500, null), "The request failed (HTTP 500); nothing was confirmed.");
});

test("the stale-summary message is B11's route message, word for word (#288)", async () => {
  const route = await import("../../data/company-commands.ts");
  assert.equal(STALE_SUMMARY, route.STALE_SUMMARY);
});
