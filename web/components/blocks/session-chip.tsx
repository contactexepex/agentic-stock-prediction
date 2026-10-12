"use client";
// The session chip of the page head, decided at view time (lib/ui/session.ts) and re-checked every minute, so a page
// left open turns from "Open now" to "Closed for today" at the close. Before the first client tick (server render,
// hydration) it shows the state at the build's cut-off, so the server and client markup agree.
import { useEffect, useState } from "react";
import { sessionChipAt } from "../../lib/ui/session.ts";
import type { StatusBlock } from "../../lib/ui/types.ts";

const TICK_MS = 60_000;

export function SessionChip({ status, cutoff }: { status: StatusBlock; cutoff?: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);
  const cutoffMs = cutoff ? Date.parse(cutoff) : NaN;
  const chip = sessionChipAt(status, now ?? (Number.isNaN(cutoffMs) ? Date.parse(status.session.local_time) : cutoffMs));
  return (
    <span className="md-chip" data-tip={chip.tip}>
      <span className={`dot${chip.open ? " open" : ""}`} aria-hidden="true" />
      {chip.bold === null ? chip.text : chip.bold === chip.text ? <b>{chip.text}</b> : <span>{chip.text.slice(0, chip.text.length - chip.bold.length)}<b>{chip.bold}</b></span>}
    </span>
  );
}
