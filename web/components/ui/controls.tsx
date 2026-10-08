"use client";
// Pill tabs (.md-segmented): a group of toggle buttons with aria-pressed, used for the horizon selector N+1..N+5
// (decision 39: a page opens on N+1), cost views, switches. Keyboard: Tab to the group, arrows move between options.
import type { KeyboardEvent, ReactNode } from "react";
import { horizonLabel, horizonWords } from "../../lib/ui/format.ts";

export interface SegmentOption<V> {
  value: V;
  label: ReactNode;
  tip?: string;
}

export function Segmented<V extends string | number>({
  label,
  options,
  value,
  onChange,
  dense = true,
  light = true,
}: {
  label: string;
  options: readonly SegmentOption<V>[];
  value: V;
  onChange: (value: V) => void;
  dense?: boolean;
  light?: boolean;
}) {
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const buttons = Array.from(event.currentTarget.querySelectorAll("button"));
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    const next = (at + (event.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length;
    buttons[next].focus();
    event.preventDefault();
  };
  return (
    <div className={["md-segmented", dense ? "dense" : "", light ? "light" : ""].filter(Boolean).join(" ")} role="group" aria-label={label} onKeyDown={onKey}>
      {options.map((option) => (
        <button key={String(option.value)} type="button" aria-pressed={option.value === value} data-tip={option.tip} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** The horizon selector: N+1..N+5 from the payload's `horizons`. */
export function HorizonTabs({ horizons, value, onChange }: { horizons: readonly number[]; value: number; onChange: (k: number) => void }) {
  const options = horizons.map((k) => ({ value: k, label: horizonLabel(k), tip: `N+${k}: sell at ${horizonWords(k)}.` }));
  return <Segmented label="Horizon" options={options} value={value} onChange={onChange} />;
}
