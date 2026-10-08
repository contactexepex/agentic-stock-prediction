// Stable sorting of table rows (components/ui/table.tsx): missing values always last, ties keep the input order.

export type SortValue = string | number | null | undefined;
export type SortState = { key: string; dir: 1 | -1 } | null;

export function compareValues(a: SortValue, b: SortValue): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
}

/** Rows sorted by `value` in direction `dir` (1 ascending, -1 descending); nulls last in both directions. */
export function sortBy<R>(rows: readonly R[], value: (row: R) => SortValue, dir: 1 | -1): R[] {
  return rows
    .map((row, i) => ({ row, i, v: value(row) }))
    .sort((x, y) => {
      const missing = x.v === null || x.v === undefined || y.v === null || y.v === undefined;
      return (missing ? compareValues(x.v, y.v) : dir * compareValues(x.v, y.v)) || x.i - y.i;
    })
    .map((x) => x.row);
}
