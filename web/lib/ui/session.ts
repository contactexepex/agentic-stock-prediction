// The session chip's state at view time (owner bug 2026-10-12: the chip read "Open now" at 17:30 IST because the
// stored `in_session` / `late_run` flags are the warehouse build's, frozen at its cut-off). The state comes from the
// stored session_open_utc / session_close_utc against the viewer's clock; every time is shown on the market's clock
// (fmtLocal), never the viewer's. Pure.
import { fmtLocal } from "./format.ts";
import type { StatusBlock } from "./types.ts";

export type SessionState = "no_session" | "before_open" | "open" | "closed";

export interface SessionChipWords {
  state: SessionState;
  open: boolean;
  /** "Opens 09:15 IST", "Open now", "Closed for today", "No session today". */
  text: string;
  /** The part to show in bold ("09:15 IST" or "Open now"), or null. */
  bold: string | null;
  tip: string;
}

/** The chip at `nowMs` (epoch milliseconds). Without stored session times it falls back to the stored flags. */
export function sessionChipAt(status: StatusBlock, nowMs: number): SessionChipWords {
  const s = status.session, m = status.market, lt = s.local_time;
  const tip = `Session ${fmtLocal(s.session_open_utc, m, lt)}–${fmtLocal(s.session_close_utc, m, lt)}.`;
  if (!s.trading_day) return { state: "no_session", open: false, text: "No session today", bold: null, tip };
  const open = Date.parse(s.session_open_utc), close = Date.parse(s.session_close_utc);
  const state: SessionState = Number.isNaN(open) || Number.isNaN(close)
    ? (s.in_session ? "open" : s.late_run ? "closed" : "before_open")
    : nowMs < open ? "before_open" : nowMs < close ? "open" : "closed";
  if (state === "open") return { state, open: true, text: "Open now", bold: "Open now", tip };
  if (state === "closed") return { state, open: false, text: "Closed for today", bold: null, tip };
  const at = fmtLocal(s.session_open_utc, m, lt);
  return { state, open: false, text: `Opens ${at}`, bold: at, tip };
}
