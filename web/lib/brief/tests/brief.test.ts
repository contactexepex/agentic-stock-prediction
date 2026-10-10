// The public brief (lib/brief/brief.ts): slug checks before any read, the constant-time token check, headers, 404s.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { BRIEF_HEADERS, briefResponse, parseBrief, tokenMatches } from "../brief.ts";
import { DownRowStore, MemoryRowStore, row } from "../../data/tests/fakes.ts";

const TOKEN = "0123456789abcdef0123456789abcdef";
const sha = (value: string) => createHash("sha256").update(value).digest("hex");
const page = "<!doctype html><title>Brief</title>";
const store = () => new MemoryRowStore().put("brief", row({
  market: "india", page_key: "2026-10-12", payload: { session: "2026-10-12", token_sha256: sha(TOKEN), html: page } }));

test("the right token serves the stored page with noindex, a strict CSP and no caching", async () => {
  const response = await briefResponse(store(), "india", `2026-10-12-${TOKEN}`);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), page);
  for (const [name, value] of Object.entries(BRIEF_HEADERS)) assert.equal(response.headers.get(name), value);
  assert.match(response.headers.get("content-security-policy") ?? "", /default-src 'none'.*form-action 'none'/);
  assert.equal(response.headers.get("x-robots-tag"), "noindex, nofollow");
});

test("a wrong, missing or malformed token, market or date is a 404, and a malformed one never reaches the store", async () => {
  const wrong = TOKEN.replace(/.$/, "0");
  const s = store();
  for (const [market, slug] of [["india", `2026-10-12-${wrong}`], ["us", `2026-10-12-${TOKEN}`],
                                ["india", `2026-10-11-${TOKEN}`]]) {
    const response = await briefResponse(s, market, slug);
    assert.equal(response.status, 404, `${market}/${slug}`);
    assert.equal(response.headers.get("x-robots-tag"), "noindex, nofollow");
  }
  const reads = s.reads.length;
  for (const [market, slug] of [["india", "2026-10-12"], ["india", `2026-10-12-${TOKEN.toUpperCase()}`],
                                ["india", `2026-10-12-${TOKEN}0`], ["india", `2026-10-12-${TOKEN.slice(1)}`],
                                ["uk", `2026-10-12-${TOKEN}`], ["india", `2026-13-45-${TOKEN}`],
                                ["india", `../2026-10-12-${TOKEN}`], ["india", ""]]) {
    assert.equal((await briefResponse(s, market, slug)).status, 404, `${market}/${slug}`);
  }
  assert.equal(s.reads.length, reads);   // checked before any read
});

test("a stored row without a usable hash, a session mismatch or no html is a 404", async () => {
  for (const payload of [{ session: "2026-10-12", token_sha256: "x", html: page },
                         { session: "2026-10-12", token_sha256: sha(TOKEN).toUpperCase(), html: page },
                         { session: "2026-10-11", token_sha256: sha(TOKEN), html: page },
                         { session: "2026-10-12", token_sha256: sha(TOKEN) }]) {
    const s = new MemoryRowStore().put("brief", row({ market: "india", page_key: "2026-10-12", payload }));
    assert.equal((await briefResponse(s, "india", `2026-10-12-${TOKEN}`)).status, 404);
  }
});

test("the warehouse being down is a 503 with no driver text", async () => {
  const response = await briefResponse(new DownRowStore(), "india", `2026-10-12-${TOKEN}`);
  assert.equal(response.status, 503);
  assert.doesNotMatch(await response.text(), /error|stack|postgres/i);
});

test("parseBrief and tokenMatches", () => {
  assert.deepEqual(parseBrief("us", `2026-10-12-${TOKEN}`), { market: "us", session: "2026-10-12", token: TOKEN });
  assert.equal(tokenMatches(TOKEN, sha(TOKEN)), true);
  assert.equal(tokenMatches(TOKEN, sha("other")), false);
  assert.equal(tokenMatches(TOKEN, null), false);
});
