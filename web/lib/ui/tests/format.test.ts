import assert from "node:assert/strict";
import { test } from "node:test";
import { fmtDate, fmtDateYear, fmtLocal, horizonWords, money, offsetMinutes, oddsPosition, pct, price, sentimentClass, signed } from "../format.ts";

test("dates read as calendar dates", () => {
  assert.equal(fmtDate("2026-10-07"), "Wed 7 Oct");
  assert.equal(fmtDate("2026-10-07T23:59:00Z", false), "7 Oct");
  assert.equal(fmtDateYear("2026-10-07"), "7 Oct 2026");
  assert.equal(fmtDate(null), "—");
});

test("local clock comes from the payload's offset", () => {
  assert.equal(offsetMinutes("2026-10-07T17:30+05:30"), 330);
  assert.equal(offsetMinutes("2026-10-07T08:00-04:00"), -240);
  assert.equal(fmtLocal("2026-10-07T03:45:00Z", "india", "2026-10-07T17:30+05:30"), "09:15 IST");
  assert.equal(fmtLocal("2026-10-07T13:30:00Z", "us", "2026-10-07T08:00-04:00", true), "7 Oct 09:30 ET");
  assert.equal(fmtLocal(null, "us", null), "—");
});

test("signed numbers use a true minus and always a sign", () => {
  assert.equal(signed(1.2), "+1.20%");
  assert.equal(signed(-0.4), "−0.40%");
  assert.equal(signed(0), "0.00%");
  assert.equal(signed(null), "—");
  assert.equal(pct(0.553, 1), "55.3%");
  assert.equal(pct(null), "—");
});

test("money in the market's locale", () => {
  assert.equal(money("INR", 100000), "₹1,00,000");
  assert.equal(money("USD", -12.5, 2), "−$12.50");
  assert.equal(money("USD", 12.5, 2, true), "+$12.50");
  assert.equal(price("INR", 1218), "1,218.00");
  assert.equal(money("USD", undefined), "—");
});

test("horizons, sentiment and odds", () => {
  assert.equal(horizonWords(1), "the next session’s close");
  assert.equal(horizonWords(3), "the close of the 3rd session after the open");
  assert.equal(sentimentClass(0.05, 0.05), "flat");
  assert.equal(sentimentClass(0.06, 0.05), "up");
  assert.equal(sentimentClass(-0.2, 0.05), "dn");
  assert.equal(oddsPosition(0.5), 32);
  assert.equal(oddsPosition(0.9), 60);
  assert.equal(oddsPosition(0.1), 4);
});
