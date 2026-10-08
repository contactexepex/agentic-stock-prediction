// The company page's watchlist commands (B15): preview then submit through B11's routes, with one Idempotency-Key.
import { test } from "node:test";
import assert from "node:assert/strict";
import { newKey, pendingWords, previewCommand, submitCommand, type CompanyCommand } from "../commands.ts";

type Call = { url: string; init: RequestInit };
const fake = (status: number, body: unknown, calls: Call[]) => async (url: string, init: RequestInit) => {
  calls.push({ url, init });
  return new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
};
const deactivate: CompanyCommand = { tool: "deactivate_company", arguments: { ticker: "TCS" } };

test("the key is a UUID the API's Idempotency-Key pattern accepts", () => {
  const key = newKey();
  assert.match(key, /^[A-Za-z0-9-]{16,64}$/);
  assert.notEqual(key, newKey());
});

test("preview posts the tool and arguments with the key and returns the summary", async () => {
  const calls: Call[] = [];
  const out = await previewCommand("india", deactivate, "k-1234567890123456", fake(200, { tool: "deactivate_company", summary: "Deactivate TCS (india).", preview: null, arguments: {}, paper: true }, calls));
  assert.deepEqual(out, { ok: true, summary: "Deactivate TCS (india)." });
  assert.equal(calls[0].url, "/api/v1/markets/india/companies/preview");
  assert.equal(calls[0].init.method, "POST");
  assert.equal((calls[0].init.headers as Record<string, string>)["Idempotency-Key"], "k-1234567890123456");
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), deactivate);
});

test("submit sends the confirmed summary with the same key; pending and duplicate are accepted", async () => {
  const calls: Call[] = [];
  const out = await submitCommand("us", deactivate, "Deactivate TCS.", "k-1234567890123456", fake(202, { result: "pending", inbox_id: "k-1234567890123456", refusal_code: null, message: null }, calls));
  assert.ok(out.ok);
  assert.equal(calls[0].url, "/api/v1/markets/us/companies/commands");
  assert.equal(JSON.parse(String(calls[0].init.body)).confirmed_summary, "Deactivate TCS.");
  const again = await submitCommand("us", deactivate, "Deactivate TCS.", "k", fake(200, { result: "duplicate", inbox_id: "k" }, []));
  assert.ok(again.ok);
});

test("refusals and failures carry the API's message; nothing pretends to be recorded", async () => {
  const stale = await submitCommand("india", deactivate, "old", "k", fake(422, { result: "refused", refusal_code: "validation_failed", message: "The summary changed since the preview, so nothing was written; preview again" }, []));
  assert.equal(stale.ok, false);
  assert.match((stale as { message: string }).message, /preview again/);
  const down = await previewCommand("india", deactivate, "k", fake(503, { title: "Service unavailable", status: 503 }, []));
  assert.deepEqual(down, { ok: false, message: "Service unavailable" });
  const notJson = await previewCommand("india", deactivate, "k", fake(500, "<html>", []));
  assert.match((notJson as { message: string }).message, /HTTP 500/);
  const offline = await submitCommand("india", deactivate, "s", "k", async () => { throw new TypeError("network"); });
  assert.equal(offline.ok, false);
  assert.match((offline as { message: string }).message, /not known whether the request was recorded/);
  assert.equal((offline as { unknown: boolean }).unknown, true);
  const gateway = await submitCommand("india", deactivate, "s", "k", fake(502, "<html>bad gateway</html>", []));
  assert.equal((gateway as { unknown: boolean }).unknown, true, "an unreadable answer leaves the outcome unknown");
  assert.equal((stale as { unknown: boolean }).unknown, false);
});

test("pending words name the change and the request", () => {
  const amount: CompanyCommand = { tool: "set_paper_amount", arguments: { ticker: "TCS", amount: 50000 } };
  assert.equal(pendingWords(amount, { result: "pending", inbox_id: "abcdef12-xyz" }, (x) => `₹${x}`), "set the amount to ₹50000 (pending, request abcdef12)");
  assert.equal(pendingWords(deactivate, { result: "duplicate", inbox_id: null }, String), "deactivate (already requested)");
});
