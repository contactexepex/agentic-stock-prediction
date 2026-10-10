// Fixture answers of the UI harness for GET /api/v1/markets/{market}/<endpoint>: the endpoint's envelope with the
// approved mockup's payload (design/mockups/<page>/data.json `markets[market]`), as contract 2.0 serves it. A case can
// answer any read itself with `api(rest, market, url)` returning {status, body} (or undefined to use the default), or
// force a state with `apiStatus` (e.g. 503 to see the error state, or "slow" to answer after 4 s and see the loading state).
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PAGES } from "../../lib/ui/routes.ts";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const cache = new Map();

/** The mockup's payload of a market (keys starting with "_" are the mockup's notes and are left out). */
export function mockupPayload(mockup, market) {
  if (!cache.has(mockup)) {
    // Python's json writes NaN for a missing float; JSON has no NaN, so it is read as null (what the API would send).
    const text = readFileSync(join(repo, "design", "mockups", mockup, "data.json"), "utf8").replace(/: NaN\b/g, ": null");
    cache.set(mockup, JSON.parse(text));
  }
  const data = cache.get(mockup).markets?.[market];
  if (!data) return null;
  return Object.fromEntries(Object.entries(data).filter(([k]) => !k.startsWith("_")));
}

/** The 03-company mockup keeps one payload per company under `pages[ticker]`; the endpoint serves the market's shared
 *  keys plus that company's payload (B12), so does the fixture. Null for a company the mockup does not have. */
export function companyPayload(marketPayload, ticker) {
  const { pages, default_ticker: _defaultTicker, ...shared } = marketPayload;
  const one = pages?.[ticker];
  return one ? { ...shared, ...one } : null;
}

export function envelope(market, pageKey, payload) {
  const text = JSON.stringify(payload);
  return {
    market,
    page_key: pageKey,
    as_of: payload.as_of ?? null,
    cutoff: payload.cutoff ?? "2026-10-07T11:00:00Z",
    built_at: payload.built_at ?? payload.freshness?.built_at ?? "2026-10-07T10:31:00Z",
    schema_version: "2.0.0",
    source_commit: "fixture",
    payload_sha256: createHash("sha256").update(text).digest("hex"),
    payload,
  };
}

const json = (status, body, headers = {}) => ({ status, contentType: status < 400 ? "application/json" : "application/problem+json", headers, body: JSON.stringify(body) });
export const problem = (status, title, detail, market) =>
  json(status, { title, status, detail, ...(status === 503 && market ? { fallback_links: [`https://omenix.vercel.app/${market}`] } : {}) });

const ROUTES = PAGES.filter((p) => p.endpoint).map((p) => ({
  page: p,
  pattern: new RegExp("^" + p.endpoint.replace("{ticker}", "([A-Z0-9.&-]{1,20})") + "$"),
}));

export async function apiFixture(url, c) {
  const { pathname } = new URL(url);
  const m = /^\/api\/v1\/markets\/([^/]+)\/(.+)$/.exec(pathname);
  if (!m) return problem(404, "Not found", "No fixture for " + pathname);
  const [, market, rest] = m;
  if (c.apiStatus === "slow") await new Promise((r) => setTimeout(r, 4000)); // the page shows its loading state first
  if (typeof c.apiStatus === "number") return problem(c.apiStatus, c.apiStatus === 503 ? "Data service unavailable" : "Request failed", c.apiStatus === 503 ? "The read models cannot be read right now; try again shortly." : undefined, market);
  if (c.api) {
    const own = await c.api(rest, market, url);
    if (own) return json(own.status ?? 200, own.body);
  }
  if (market !== "india" && market !== "us") return problem(404, "Not found", "Unknown market");
  if (rest === "status") {
    const home = mockupPayload("01-home", market);
    const payload = { ...home.status, freshness: home.status.freshness };
    const env = envelope(market, "_", payload);
    return json(200, env, { ETag: `"${env.payload_sha256}"` });
  }
  for (const { page, pattern } of ROUTES) {
    const hit = pattern.exec(rest);
    if (!hit) continue;
    let payload = mockupPayload(page.mockup, market);
    if (!payload) return problem(404, "Not found", "No mockup data for " + market);
    if (page.key === "company") {
      payload = companyPayload(payload, hit[1]);
      if (!payload) return problem(404, "Not found", `No mockup company ${hit[1]} in ${market}`);
    }
    const env = envelope(market, hit[1] ?? "_", payload);
    return json(200, env, { ETag: `"${env.payload_sha256}"` });
  }
  return problem(404, "Not found", "No fixture for " + rest);
}
