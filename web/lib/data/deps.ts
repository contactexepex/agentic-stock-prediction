// The production dependencies of the read routes: MotherDuck behind the data cache, and the wall clock. Kept apart
// from handler.ts so the node tests never load next/cache.
import { defaultStore } from "./cache.ts";
import type { ReadDeps } from "./handler.ts";

export function defaultDeps(): ReadDeps {
  return { store: defaultStore(), now: () => new Date() };
}
