// The production dependencies of the read routes: MotherDuck behind the data cache, and the wall clock. Kept apart
// from handler.ts so the node tests never load next/cache.
import { defaultStore } from "./cache.ts";
import { MARKET_PAGE_KEY } from "./constants.ts";
import type { ReadDeps } from "./handler.ts";
import { syncTimeFor } from "./serve.ts";

export function defaultDeps(): ReadDeps {
  const store = defaultStore();
  return {
    store,
    now: () => new Date(),
    syncedAt: async (market, table, pageKey) =>
      syncTimeFor(await store.read("status", market, MARKET_PAGE_KEY), table, pageKey),
  };
}
