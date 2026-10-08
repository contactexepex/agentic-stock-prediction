// A head-to-head pick's two cost views (design/mockups/_shared/shell.js pickCand, yourViable, viableLine): the
// market-cost expected gain it was ranked on, and decision 51's viability at the owner's own cost. Pure.

export interface PickCandidate {
  horizon_days: number;
  your_cost_pct?: number | null;
  expected_gain_your_pct?: number | null;
  cost_viable?: boolean | null;
}

export interface Pick {
  horizon_days: number;
  prob_up: number;
  move_pct: number;
  loss_pct: number;
  costs_pct: number;
  expected_gain_pct: number;
  amount: number;
  candidates?: PickCandidate[];
}

/** The candidate row of the pick's own horizon (it carries the your-cost view), or null. */
export function pickCandidate(pick: Pick): PickCandidate | null {
  return (pick.candidates ?? []).find((c) => c.horizon_days === pick.horizon_days) ?? null;
}

/** true / false at the owner's cost, or null when the your-cost view is not stored. */
export function yourViable(pick: Pick): boolean | null {
  const c = pickCandidate(pick);
  return c && c.cost_viable != null ? c.cost_viable : null;
}

/** "1 clears market costs · none viable at your cost" for a list of picks. */
export function viableLine(picked: readonly Pick[]): string {
  const market = picked.filter((k) => k.expected_gain_pct > 0).length;
  const yours = picked.filter((k) => yourViable(k) === true).length;
  const known = picked.filter((k) => yourViable(k) != null).length;
  const left = market ? `${market} clear${market === 1 ? "s" : ""} market costs` : "none clears market costs";
  const right = known ? (yours ? `${yours} viable at your cost` : "none viable at your cost") : "your-cost view not stored";
  return `${left} · ${right}`;
}

/** The pages of a list: 1-based page numbers, the slice, and whether previous / next exist. */
export function pageSlice<T>(items: readonly T[], page: number, size: number): { page: number; pages: number; rows: T[] } {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const at = Math.min(Math.max(1, Math.floor(page)), pages);
  return { page: at, pages, rows: items.slice((at - 1) * size, at * size) };
}
