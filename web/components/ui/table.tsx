"use client";
// The shared data table (.md-table in a scrolling .md-table-wrap): typed columns, optional sorting with aria-sort and
// an arrow, numeric columns right-aligned with tabular figures, an empty row that says why, optional group rows and
// clickable rows (a row click follows its link; the keyboard path is the link inside the row).
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { sortBy, type SortState } from "../../lib/ui/sort.ts";
import { Icon } from "./icon.tsx";

export interface Column<R> {
  key: string;
  header: ReactNode;
  /** Words for the sort button and screen readers when the header is not plain text. */
  label?: string;
  tip?: string;
  className?: string;
  numeric?: boolean;
  /** A sort value; the column is sortable when given. */
  sortValue?: (row: R) => string | number | null | undefined;
  render: (row: R) => ReactNode;
}

export interface RowGroup<R> {
  key: string;
  title: ReactNode;
  note?: ReactNode;
  rows: R[];
}

export function sortRows<R>(rows: readonly R[], columns: readonly Column<R>[], sort: SortState): R[] {
  const column = sort ? columns.find((c) => c.key === sort.key) : undefined;
  return sort && column?.sortValue ? sortBy(rows, column.sortValue, sort.dir) : [...rows];
}

export function DataTable<R>({
  columns,
  rows,
  groups,
  rowKey,
  label,
  empty = "Nothing to show.",
  initialSort = null,
  rowHref,
  className = "",
}: {
  columns: readonly Column<R>[];
  rows?: readonly R[];
  groups?: readonly RowGroup<R>[];
  rowKey: (row: R) => string;
  label: string;
  empty?: ReactNode;
  initialSort?: SortState;
  rowHref?: (row: R) => string | null;
  className?: string;
}) {
  const [sort, setSort] = useState<SortState>(initialSort);
  const router = useRouter();
  const sections = useMemo(
    () => (groups ?? [{ key: "_", title: null, rows: [...(rows ?? [])] }]).map((g) => ({ ...g, rows: sortRows(g.rows, columns, sort) })),
    [groups, rows, columns, sort],
  );
  const total = sections.reduce((n, g) => n + g.rows.length, 0);
  const toggle = (key: string) =>
    setSort((s) => (s && s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: -1 }));
  const cellClass = (c: Column<R>) => [c.numeric ? "num md-numeric" : "", c.className ?? ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="md-table-wrap">
      <table className={`md-table tbl${className ? " " + className : ""}`} aria-label={label}>
        <thead>
          <tr>
            {columns.map((c) => {
              const sorted = sort && sort.key === c.key ? (sort.dir < 0 ? "descending" : "ascending") : undefined;
              return (
                <th key={c.key} scope="col" className={cellClass(c)} data-tip={c.sortValue ? undefined : c.tip} aria-sort={sorted}>
                  {c.sortValue ? (
                    <button type="button" className="sort" data-tip={c.tip} onClick={() => toggle(c.key)} aria-label={`Sort by ${c.label ?? (typeof c.header === "string" ? c.header : c.key)}`}>
                      {c.header}
                      {sorted ? <Icon name={sorted === "descending" ? "arrow_downward" : "arrow_upward"} /> : null}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {total === 0 ? (
            <tr>
              <td colSpan={columns.length}>
                <div className="quiet">{empty}</div>
              </td>
            </tr>
          ) : (
            sections.map((g) => [
              g.title !== null && g.rows.length ? (
                <tr key={`g-${g.key}`} className="grp">
                  <td colSpan={columns.length}>
                    {g.title}
                    {g.note ? <small>{g.note}</small> : null}
                  </td>
                </tr>
              ) : null,
              ...g.rows.map((row) => {
                const href = rowHref ? rowHref(row) : null;
                return (
                  <tr
                    key={rowKey(row)}
                    className={href ? "row" : undefined}
                    onClick={href ? (e) => { if (!(e.target as HTMLElement).closest("a, button, input, select")) router.push(href); } : undefined}
                  >
                    {columns.map((c) => (
                      <td key={c.key} className={cellClass(c)}>
                        {c.render(row)}
                      </td>
                    ))}
                  </tr>
                );
              }),
            ])
          )}
        </tbody>
      </table>
    </div>
  );
}
