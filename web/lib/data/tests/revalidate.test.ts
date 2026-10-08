// POST /api/v1/internal/revalidate (lib/data/revalidate.ts): the secret in constant time, the body checked, one tag
// per changed key.
import { test } from "node:test";
import assert from "node:assert/strict";
import { handleRevalidate, MAX_KEYS } from "../revalidate.ts";

const SECRET = "s3cret-value";
const post = (body: unknown, secret: string | null = SECRET) => new Request("https://app.test/api/v1/internal/revalidate", {
  method: "POST", body: typeof body === "string" ? body : JSON.stringify(body),
  headers: secret === null ? {} : { "x-revalidate-secret": secret },
});

test("the changed keys' tags are revalidated once each", async () => {
  const tags: string[] = [];
  const keys = [
    { table: "status", market: "us", page_key: "_" },
    { table: "status", market: "us", page_key: "_" },
    { table: "stock", market: "india", page_key: "M&M" },
  ];
  const response = await handleRevalidate(post({ build_id: "b1", keys }), SECRET, (tag) => tags.push(tag));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { revalidated: 2 });
  assert.deepEqual(tags, ["rm:status:us:_", "rm:stock:india:M&M"]);
});

test("a missing or wrong secret, or no secret configured, is a 401 and revalidates nothing", async () => {
  const tags: string[] = [];
  const body = { build_id: "b1", keys: [] };
  for (const [given, expected] of [[null, SECRET], ["wrong", SECRET], [SECRET, null], ["s3cret-valuX", SECRET]]) {
    const response = await handleRevalidate(post(body, given), expected, (tag) => tags.push(tag));
    assert.equal(response.status, 401);
  }
  assert.deepEqual(tags, []);
});

test("a bad body is a 422", async () => {
  const bad = [
    "not json", { keys: [] }, { build_id: "b", keys: "x" },
    { build_id: "b", keys: Array.from({ length: MAX_KEYS + 1 }, () => ({ table: "a", market: "us", page_key: "_" })) },
    { build_id: "b", keys: [{ table: "rm.x;", market: "us", page_key: "_" }] },
    { build_id: "b", keys: [{ table: "x", market: "eu", page_key: "_" }] },
    { build_id: "b", keys: [{ table: "x", market: "us", page_key: "a b" }] },
  ];
  for (const body of bad) {
    assert.equal((await handleRevalidate(post(body), SECRET, () => undefined)).status, 422, JSON.stringify(body));
  }
});
