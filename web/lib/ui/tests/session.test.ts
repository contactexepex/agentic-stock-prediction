import assert from "node:assert/strict";
import { test } from "node:test";
import { sessionChipAt } from "../session.ts";
import type { StatusBlock } from "../types.ts";

// An India session day, 12 Oct 2026: NSE 09:15-15:30 IST = 03:45-10:00 UTC. The stored flags are a sync made during
// market hours (in_session true), the frozen state the owner saw at 17:30 IST.
const india = {
  market: "india",
  session: {
    local_time: "2026-10-12T09:41:00+05:30", trading_day: true, session_date: "2026-10-12", previous_session: "2026-10-09",
    calendar_covered: true, session_open_utc: "2026-10-12T03:45:00+00:00", session_close_utc: "2026-10-12T10:00:00+00:00",
    in_session: true, late_run: false,
  },
} as unknown as StatusBlock;

const at = (iso: string) => sessionChipAt(india, Date.parse(iso));

test("the India chip follows the viewer's clock, on IST", () => {
  assert.deepEqual([at("2026-10-12T05:00:00Z").state, at("2026-10-12T05:00:00Z").text], ["open", "Open now"]);
  const late = at("2026-10-12T12:00:00Z");
  assert.deepEqual([late.state, late.text, late.open], ["closed", "Closed for today", false]);
  const early = sessionChipAt({ ...india, session: { ...india.session, in_session: false } }, Date.parse("2026-10-12T03:00:00Z"));
  assert.deepEqual([early.state, early.text, early.bold], ["before_open", "Opens 09:15 IST", "09:15 IST"]);
  assert.equal(at("2026-10-12T07:00:00Z").text, "Open now");
  assert.equal(at("2026-10-12T10:00:00Z").text, "Closed for today"); // the close itself is closed
  assert.equal(late.tip, "Session 09:15 IST–15:30 IST.");
});

test("no session today, and the stored flags when the times are missing", () => {
  assert.equal(sessionChipAt({ ...india, session: { ...india.session, trading_day: false } }, Date.parse("2026-10-12T05:00:00Z")).text, "No session today");
  const noTimes = { ...india, session: { ...india.session, session_open_utc: "", session_close_utc: "" } } as StatusBlock;
  assert.equal(sessionChipAt(noTimes, 0).state, "open");
});
