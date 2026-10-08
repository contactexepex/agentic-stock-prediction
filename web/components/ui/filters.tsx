"use client";
// Filter chips, the pager and the search box of the mockups' toolbars (News feed, Watchlist, Paper portfolios):
// toggle buttons with aria-pressed, a pager with aria-current on the page shown, and a labelled search input.
import type { ReactNode } from "react";
import { Icon } from "./icon.tsx";

export interface ChipOption<V> {
  value: V;
  label: ReactNode;
  tip?: string;
}

/** A row of filter chips (.md-chip.filter); one is pressed. */
export function FilterChips<V extends string>({ label, options, value, onChange }: { label: string; options: readonly ChipOption<V>[]; value: V | null; onChange: (value: V) => void }) {
  return (
    <div className="mb-chips" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className="md-chip filter" aria-pressed={o.value === value} data-tip={o.tip} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** "Page 2 of 5 · 43 stories, 10 a page" with Previous / 1..n / Next. */
export function Pager({ page, pages, summary, onPage }: { page: number; pages: number; summary?: ReactNode; onPage: (page: number) => void }) {
  const button = (text: string, to: number | null, current = false) => (
    <button key={text} type="button" className="md-btn outlined small" aria-current={current ? "page" : undefined} disabled={to === null} onClick={to === null ? undefined : () => onPage(to)}>
      {text}
    </button>
  );
  return (
    <div className="pager">
      <span>{summary ?? `Page ${page} of ${pages}`}</span>
      <div className="pg" role="group" aria-label="Pages">
        {button("Previous", page > 1 ? page - 1 : null)}
        {Array.from({ length: pages }, (_, i) => button(String(i + 1), i + 1, i + 1 === page))}
        {button("Next", page < pages ? page + 1 : null)}
      </div>
    </div>
  );
}

/** The toolbar's search box with its icon. */
export function SearchInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <span className="search">
      <Icon name="search" />
      <input type="search" aria-label={label} placeholder={placeholder ?? label} value={value} onChange={(e) => onChange(e.target.value)} />
    </span>
  );
}
