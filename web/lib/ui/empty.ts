// Empty states that say when they will fill (docs/ux/plain_language_review.md section 4, L2): every "No … yet"
// names the event that fills it and, when the payload knows it, the date or time. Pure; the dates come from the
// payload (an open trade's exit_date, the status block's next post-close run), never from the browser's clock.
import { MIN_TRADES_TO_RANK } from "./constants.ts";
import { fmtDate, fmtLocal } from "./format.ts";

/** The earliest exit date of the trades (ISO date), or null when there is none. */
export function firstExit(trades: readonly { exit_date?: string | null }[]): string | null {
  const dates = trades.map((t) => t.exit_date).filter((d): d is string => !!d).sort();
  return dates[0] ?? null;
}

/** "No paper trade has finished yet. The first ones finish at the close on Tue 13 Oct; results appear at the
 *  after-close run (13 Oct 17:45 IST)." Without open trades or a next run time, the sentence says what fills it. */
export function noneFinishedYet(
  trades: readonly { exit_date?: string | null }[],
  postCloseNextAt: string | null | undefined,
  market: string,
  localTime: string | null | undefined,
  subject = "paper trade",
): string {
  const first = firstExit(trades);
  const when = first ? ` The first ones finish at the close on ${fmtDate(first)}` : " The first ones finish at the close of their exit day";
  const run = postCloseNextAt ? `; results appear at the after-close run (next: ${fmtLocal(postCloseNextAt, market, localTime, true)}).` : "; results appear at that day’s after-close run.";
  return `No ${subject} has finished yet.${when}${run}`;
}

/** "3 running · first finishes Tue 13 Oct" (or "none running yet"). */
export function runningLine(trades: readonly { exit_date?: string | null }[]): string {
  if (!trades.length) return "none running yet";
  const first = firstExit(trades);
  return `${trades.length} running${first ? ` · first finishes ${fmtDate(first)}` : ""}`;
}

/** "too early to tell: 3 of 20 finished trades" (under MIN_TRADES_TO_RANK the numbers are mostly luck). */
export function tooEarly(trades: number): string {
  return `too early to tell: ${trades} of ${MIN_TRADES_TO_RANK} finished trades`;
}

/** "finishes Tue 13 Oct" for a row that has not settled yet. */
export function finishesOn(exitDate: string | null | undefined): string {
  return exitDate ? `finishes ${fmtDate(exitDate)}` : "not finished yet";
}
