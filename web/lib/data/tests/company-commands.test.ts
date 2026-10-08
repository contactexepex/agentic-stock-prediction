// The Companies page's command routes (B11, lib/data/company-commands.ts) on B5's real tool layer with its offline
// fakes: the preview writes nothing; a command is written only when the confirmed summary is the one the server's own
// preview gives now (add_company's identifiers re-resolved, never taken from the browser); delete needs the typed
// ticker; the body never sets the market, the key or the identity; gateway mode refuses; outcomes map to statuses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { dashboardContext } from "../../tools/identity.ts";
import { rig } from "../../tools/tests/fakes.ts";
import { STALE_SUMMARY, previewCompanyCommand, submitCompanyCommand } from "../company-commands.ts";

const KEY = "key-0123456789abcdef";
const BASE = "https://omenix.vercel.app/api/v1/markets/us/companies";

function post(path: string, body: unknown, headers: Record<string, string> = {}): Request {
  return new Request(`${BASE}/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": KEY, ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const dashboard = () => rig({ gatewayMode: false });

async function previewed(r: ReturnType<typeof rig>, tool: string, args: Record<string, unknown>, market = "us") {
  const response = await previewCompanyCommand(post("preview", { tool, arguments: args }), market, r.layer, dashboardContext());
  return { status: response.status, body: await response.json() };
}

test("preview of add_company resolves the identifiers and writes nothing", async () => {
  const r = dashboard();
  const { status, body } = await previewed(r, "add_company", { symbol: "MSFT" });
  assert.equal(status, 200);
  assert.equal(body.tool, "add_company");
  assert.match(body.summary, /^Add Microsoft Corporation \(NASDAQ, Technology, Yahoo MSFT, CIK 0000789019\)/);
  assert.equal(body.preview.cik, "0000789019");
  assert.deepEqual(body.arguments, { symbol: "MSFT" });
  assert.equal(body.paper, true);
  // the keys of CompanyCommandPreview and ResolvedCompany (api/schemas/companies.yaml; tests/test_b11_commands.py)
  assert.deepEqual(Object.keys(body).sort(), ["arguments", "paper", "preview", "summary", "tool"]);
  assert.deepEqual(Object.keys(body.preview).sort(), ["amount", "amount_is_default", "cik", "currency", "exchange",
    "market", "name", "nse_symbol", "sector", "symbol", "yahoo"]);
  assert.equal(r.inbox.requests.length, 0);
  assert.equal(r.dispatcher.calls, 0);
});

test("a confirmed add is written with the server's resolved identifiers, and a retry answers duplicate", async () => {
  const r = dashboard();
  const { body: shown } = await previewed(r, "add_company", { symbol: "MSFT", amount: 2500 });
  const confirm = () => submitCompanyCommand(post("commands", { tool: "add_company", arguments: { symbol: "MSFT", amount: 2500 },
    confirmed_summary: shown.summary }), "us", r.layer, dashboardContext());
  const first = await confirm();
  assert.equal(first.status, 202);
  const receipt = await first.json();
  assert.equal(receipt.result, "pending");
  assert.equal(receipt.inbox_id, KEY);
  assert.deepEqual(Object.keys(receipt).sort(), ["budget_left", "command_id", "inbox_id", "message", "paper",
    "record_ids", "refusal_code", "result"]);   // CompanyCommandReceipt
  assert.equal(r.inbox.requests.length, 1);
  const stored = r.inbox.requests[0];
  assert.equal(stored.tool, "add_company");
  assert.equal(stored.market, "us");
  assert.equal(stored.channel, "dashboard");
  assert.equal(stored.submitted_by, "dashboard:owner");
  assert.equal(stored.preview?.amount, 2500);
  assert.equal(stored.preview?.amount_is_default, false);
  assert.equal(r.resolver.calls.length, 2);   // preview, then again on the server before the write
  const again = await confirm();
  assert.equal(again.status, 200);
  assert.equal((await again.json()).result, "duplicate");
  assert.equal(r.inbox.requests.length, 1);
});

test("a summary other than the server's preview is refused and nothing is written", async () => {
  const r = dashboard();
  const response = await submitCompanyCommand(post("commands", { tool: "deactivate_company", arguments: { ticker: "AAPL" },
    confirmed_summary: "Deactivate MSFT (US)" }), "us", r.layer, dashboardContext());
  assert.equal(response.status, 422);
  const body = await response.json();
  assert.equal(body.message, STALE_SUMMARY);
  assert.equal(body.refusal_code, "validation_failed");
  assert.equal(r.inbox.requests.length, 0);
  assert.ok(r.inbox.commands.some((row) => row.tool === "deactivate_company" && row.result === "refused"));
});

test("deactivate, reactivate and change amount go through with their preview's summary", async () => {
  const cases: [string, Record<string, unknown>][] = [
    ["deactivate_company", { ticker: "AAPL", reason: "too quiet" }],
    ["reactivate_company", { ticker: "AAPL" }],
    ["set_paper_amount", { ticker: "AAPL", amount: null }],
    ["set_paper_amount", { ticker: "AAPL", amount: 750 }],
  ];
  for (const [tool, args] of cases) {
    const r = dashboard();
    const { status, body } = await previewed(r, tool, args);
    assert.equal(status, 200, tool);
    assert.equal(body.preview, null);
    const response = await submitCompanyCommand(post("commands", { tool, arguments: args, confirmed_summary: body.summary }),
      "us", r.layer, dashboardContext());
    assert.equal(response.status, 202, tool);
    assert.deepEqual(r.inbox.requests[0].arguments, { ...args, market: "us", idempotency_key: KEY });
  }
});

test("delete needs the ticker typed in confirm", async () => {
  const r = dashboard();
  const wrong = await previewed(r, "delete_company", { ticker: "AAPL", confirm: "aapl" });
  assert.equal(wrong.status, 422);
  assert.match(wrong.body.message, /confirm must equal the ticker/);
  const args = { ticker: "AAPL", confirm: "AAPL" };
  const { body } = await previewed(r, "delete_company", args);
  assert.match(body.summary, /^Delete AAPL \(US\) everywhere/);
  const response = await submitCompanyCommand(post("commands", { tool: "delete_company", arguments: args,
    confirmed_summary: body.summary }), "us", r.layer, dashboardContext());
  assert.equal(response.status, 202);
  assert.equal(r.inbox.requests.length, 1);
});

test("an ETF is refused at the preview (logged and reported)", async () => {
  const r = dashboard();
  const { status, body } = await previewed(r, "add_company", { symbol: "SPY" });
  assert.equal(status, 422);
  assert.equal(body.result, "refused");
  assert.match(body.message, /ETF/);
  assert.equal(r.notifier.reports.length, 1);
});

test("refused before the tool layer: unknown market, cross-site, not JSON; body refusals are logged", async () => {
  const r = dashboard();
  const good = { tool: "reactivate_company", arguments: { ticker: "AAPL" }, confirmed_summary: "x" };
  const cases: [Request, string, number][] = [
    [post("commands", good), "eu", 404],
    [post("commands", good, { origin: "https://evil.example" }), "us", 403],
    [post("commands", good, { "content-type": "text/plain" }), "us", 415],
    [post("commands", "{not json"), "us", 422],
    [post("commands", [good]), "us", 422],
    [post("commands", { ...good, submitted_by: "someone" }), "us", 422],
    [post("commands", { ...good, tool: "add_paper_trade" }), "us", 422],
    [post("commands", { ...good, tool: "get_news" }), "us", 422],
    [new Request(`${BASE}/commands`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(good) }), "us", 422],
    [post("commands", { ...good, arguments: { ticker: "AAPL", market: "india" } }), "us", 422],
    [post("commands", { ...good, arguments: { ticker: "AAPL", idempotency_key: "other-key-123456" } }), "us", 422],
    [post("commands", { ...good, arguments: "AAPL" }), "us", 422],
    [post("commands", { tool: "reactivate_company", arguments: { ticker: "AAPL" } }), "us", 422],
  ];
  for (const [request, market, status] of cases) {
    assert.equal((await submitCompanyCommand(request, market, r.layer, dashboardContext())).status, status);
  }
  assert.equal(r.inbox.requests.length, 0);
  // the probes (unknown market, cross-site, content type) are not logged; the 10 body refusals are
  assert.equal(r.inbox.commands.filter((row) => row.result === "refused").length, 10);
  const preview = await previewCompanyCommand(post("preview", good), "us", r.layer, dashboardContext());
  assert.equal(preview.status, 422);   // confirmed_summary is not a preview field
});

test("gateway mode refuses the dashboard identity", async () => {
  const r = rig({ gatewayMode: true });
  const { status, body } = await previewed(r, "reactivate_company", { ticker: "AAPL" });
  assert.equal(status, 403);
  assert.equal(body.refusal_code, "unknown_actor");
  assert.equal(r.inbox.requests.length, 0);
});
