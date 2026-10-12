// The session chip's state at view time (owner bug 2026-10-12: the chip read "Open now" at 17:30 IST because the
// stored `in_session` / `late_run` flags are the warehouse build's, frozen at its cut-off). The state comes from the
// stored session_open_utc / session_close_utc against the viewer's clock; every time is shown on the market's clock
// (fmtLocal), never the viewer's. Pure.
import { fmtLocal, offsetMinutes } from "./format.ts";
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

/** The market-local calendar date (YYYY-MM-DD) of `ms`, on the UTC offset of the status block's local time. */
const marketDate = (ms: number, localTime: string): string =>
  new Date(ms + offsetMinutes(localTime) * 60000).toISOString().slice(0, 10);

/** The chip at `nowMs` (epoch milliseconds). The stored session is the one being predicted: the build day's own
 *  session until its close, then the next session (after a close, on a weekend or a holiday). So:
 *  - between its open and close: "Open now"; after its close: "Closed for today";
 *  - before its open on its own date: "Opens HH:MM";
 *  - before its open on an earlier date: that date has no session left. It is the build day ("Closed for today" when
 *    the build day was a session day, else "No session today") or a day between the build and the session, which
 *    has no session by construction ("No session today").
 *  Without stored session times it falls back to the stored flags. */
export function sessionChipAt(status: StatusBlock, nowMs: number): SessionChipWords {
  const s = status.session, m = status.market, lt = s.local_time;
  const tip = `Session ${fmtLocal(s.session_open_utc, m, lt, true)}–${fmtLocal(s.session_close_utc, m, lt)}.`;
  const open = Date.parse(s.session_open_utc), close = Date.parse(s.session_close_utc);
  const closedToday: SessionChipWords = { state: "closed", open: false, text: "Closed for today", bold: null, tip };
  const none: SessionChipWords = { state: "no_session", open: false, text: "No session today", bold: null, tip };
  const isOpen: SessionChipWords = { state: "open", open: true, text: "Open now", bold: "Open now", tip };
  if (Number.isNaN(open) || Number.isNaN(close)) return !s.trading_day ? none : s.in_session ? isOpen : closedToday;
  if (nowMs >= close) return closedToday;
  if (nowMs >= open) return isOpen;
  const today = marketDate(nowMs, lt);
  if (today === s.session_date.slice(0, 10)) {
    const at = fmtLocal(s.session_open_utc, m, lt);
    return { state: "before_open", open: false, text: `Opens ${at}`, bold: at, tip };
  }
  return today === lt.slice(0, 10) && s.trading_day ? closedToday : none;
}
