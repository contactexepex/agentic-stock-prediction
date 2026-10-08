// The data cache in front of the warehouse (ARCHITECTURE.md section 7): each row is cached under the tag
// rm:<table>:<market>:<page_key> with a daily safety-net revalidate; the sync revalidates the changed keys through
// POST /api/v1/internal/revalidate, so unchanged pages cost no MotherDuck compute. A failed read is not cached.
import { unstable_cache } from "next/cache";
import { CACHE_REVALIDATE_SECONDS, cacheTag } from "./constants.ts";
import { motherDuckStore, type RowStore } from "./store.ts";
import type { StoredRow } from "./serve.ts";

export class CachedRowStore implements RowStore {
  readonly inner: RowStore;

  constructor(inner: RowStore) {
    this.inner = inner;
  }

  read(table: string, market: string, pageKey: string): Promise<StoredRow | null> {
    const tag = cacheTag(table, market, pageKey);
    return unstable_cache(() => this.inner.read(table, market, pageKey), [tag],
      { tags: [tag], revalidate: CACHE_REVALIDATE_SECONDS })();
  }
}

let shared: RowStore | null = null;

/** The store the routes use: MotherDuck behind the data cache (one per server instance). */
export function defaultStore(): RowStore {
  shared ??= new CachedRowStore(motherDuckStore());
  return shared;
}
