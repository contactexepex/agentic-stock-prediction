import assert from "node:assert/strict";
import { test } from "node:test";
import { sessionChipAt } from "../session.ts";
import type { StatusBlock } from "../types.ts";

// Status blocks as market_status.status writes them for India (NSE 09:15-15:30 IST = 03:45-10:00 UTC): the stored
// session is the one being predicted, so it rolls to the next session after the close.
const block = (localTime: string, tradingDay: boolean, session: string, flags = { in_session: false, late_run: false }) => ({
  market: "india",
  session: {
    local_time: localTime, trading_day: tradingDay, session_date: session, previous_session: "2026-10-09", calendar_covered: true,
    session_open_utc: `${session}T03:45:00+00:00`, session_close_utc: `${session}T10:00:00+00:00`, ...flags,
  },
}) as unknown as StatusBlock;
const chip = (b: StatusBlock, iso: string) => sessionChipAt(b, Date.parse(iso)).text;

// The owner's case: built during Monday's session (in_session true), viewed later.
const monDuring = block("2026-10-12T11:30+05:30", true, "2026-10-12", { in_session: true, late_run: false });

test("a page built during the session follows the viewer's clock (05:00, 07:00 and 12:00 UTC)", () => {
  assert.equal(chip(monDuring, "2026-10-12T05:00:00Z"), "Open now");
  assert.equal(chip(monDuring, "2026-10-12T07:00:00Z"), "Open now");
  assert.equal(chip(monDuring, "2026-10-12T12:00:00Z"), "Closed for today"); // 17:30 IST, the bug
  assert.equal(chip(monDuring, "2026-10-12T10:00:00Z"), "Closed for today"); // the close itself
  assert.equal(sessionChipAt(monDuring, Date.parse("2026-10-12T12:00:00Z")).tip, "Session 12 Oct 09:15 IST–15:30 IST.");
});

test("before the open, after a close, and on a weekend", () => {
  const monEarly = block("2026-10-12T07:30+05:30", true, "2026-10-12");
  const early = sessionChipAt(monEarly, Date.parse("2026-10-12T03:00:00Z"));
  assert.deepEqual([early.state, early.text, early.bold], ["before_open", "Opens 09:15 IST", "09:15 IST"]);
  // built after Monday's close: the stored session is Tuesday's
  const monAfter = block("2026-10-12T17:30+05:30", true, "2026-10-13");
  assert.equal(chip(monAfter, "2026-10-12T13:00:00Z"), "Closed for today");
  assert.equal(chip(monAfter, "2026-10-13T02:00:00Z"), "Opens 09:15 IST");
  assert.equal(chip(monAfter, "2026-10-13T05:00:00Z"), "Open now");
  // built on Saturday: the stored session is Monday's; a page left open until Monday turns with the clock
  const sat = block("2026-10-10T11:30+05:30", false, "2026-10-12");
  assert.equal(chip(sat, "2026-10-10T06:00:00Z"), "No session today");
  assert.equal(chip(sat, "2026-10-11T06:00:00Z"), "No session today");
  assert.equal(chip(sat, "2026-10-12T03:00:00Z"), "Opens 09:15 IST");
  assert.equal(chip(sat, "2026-10-12T05:00:00Z"), "Open now");
});

test("without stored session times the stored flags decide", () => {
  const noTimes = { ...monDuring, session: { ...monDuring.session, session_open_utc: "", session_close_utc: "" } } as StatusBlock;
  assert.equal(sessionChipAt(noTimes, 0).text, "Open now");
  const holiday = { ...noTimes, session: { ...noTimes.session, trading_day: false } } as StatusBlock;
  assert.equal(sessionChipAt(holiday, 0).text, "No session today");
});
