// Formatters of the cockpit, ported from the approved mockups' shared script (design/mockups/_shared/shell.js) so the
// pages read the same: dates in UTC calendar terms, the market's local clock from the payload's own offset, signed
// numbers with a true minus sign, money in the market's locale. Pure functions, no DOM; null shows as an em dash.
import { CURRENCY_SYMBOL, LOCALE, MARKET_ZONE } from "./constants.ts";

export const DASH = "—";
const MINUS = "−";
export const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export const DOW_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
export const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const dayOf = (iso: string) => new Date(iso.slice(0, 10) + "T00:00:00Z");

/** "Wed 7 Oct" (or "7 Oct" without the weekday) of an ISO date or time, read as its calendar date. */
export function fmtDate(iso: string | null | undefined, withWeekday = true): string {
  if (!iso) return DASH;
  const d = dayOf(iso);
  return (withWeekday ? DOW[d.getUTCDay()] + " " : "") + d.getUTCDate() + " " + MONTH[d.getUTCMonth()];
}

/** "7 Oct 2026". */
export function fmtDateYear(iso: string | null | undefined): string {
  return iso ? fmtDate(iso, false) + " " + iso.slice(0, 4) : DASH;
}

/** Minutes east of UTC of an ISO local time ending in +HH:MM or -HH:MM (0 when it has none). */
export function offsetMinutes(localTime: string | null | undefined): number {
  const m = /([+-])(\d\d):(\d\d)$/.exec(localTime ?? "");
  return m ? (m[1] === "-" ? -1 : 1) * (60 * Number(m[2]) + Number(m[3])) : 0;
}

/** "09:15 IST" (or "7 Oct 09:15 IST") of a UTC time on the market's clock; the offset comes from the payload's
 *  `status.session.local_time`, so the page never guesses daylight saving. */
export function fmtLocal(iso: string | null | undefined, market: string, localTime: string | null | undefined, withDate = false): string {
  if (!iso) return DASH;
  const t = new Date(new Date(iso).getTime() + offsetMinutes(localTime) * 60000);
  if (Number.isNaN(t.getTime())) return DASH;
  const hm = `${String(t.getUTCHours()).padStart(2, "0")}:${String(t.getUTCMinutes()).padStart(2, "0")}`;
  const zone = (MARKET_ZONE as Record<string, string>)[market] ?? "UTC";
  return (withDate ? `${t.getUTCDate()} ${MONTH[t.getUTCMonth()]} ` : "") + `${hm} ${zone}`;
}

/** A signed number: "+1.20%", "−0.40%", "0.00%". */
export function signed(x: number | null | undefined, decimals = 2, unit = "%"): string {
  if (x === null || x === undefined || Number.isNaN(x)) return DASH;
  return (x > 0 ? "+" : x < 0 ? MINUS : "") + Math.abs(x).toFixed(decimals) + unit;
}

/** A fraction as a percent: 0.553 -> "55%" (or "55.3%" with one decimal). */
export function pct(x: number | null | undefined, decimals = 0): string {
  return x === null || x === undefined || Number.isNaN(x) ? DASH : (x * 100).toFixed(decimals) + "%";
}

/** Decimals a money amount shows in its currency (whole rupees, cents for dollars). */
export const moneyDecimals = (currency: string) => (currency === "INR" ? 0 : 2);

/** "₹1,00,000", "−$12.50", or with `sign` "+$12.50". */
export function money(currency: string, x: number | null | undefined, decimals = 0, sign = false): string {
  if (x === null || x === undefined || Number.isNaN(x)) return DASH;
  const s = Math.abs(x).toLocaleString(LOCALE[currency] ?? "en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const lead = sign ? (x > 0 ? "+" : x < 0 ? MINUS : "") : x < 0 ? MINUS : "";
  return lead + (CURRENCY_SYMBOL[currency] ?? "") + s;
}

/** A price with two decimals in the market's locale, no symbol. */
export function price(currency: string, x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return DASH;
  return x.toLocaleString(LOCALE[currency] ?? "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** "up" | "down" | "flat" of a number's sign (the `.mb-delta` classes). */
export const direction = (x: number) => (x > 0 ? "up" : x < 0 ? "down" : "flat");

/** "N+3". */
export const horizonLabel = (k: number) => `N+${k}`;
/** What horizon k means in words (decision 37). */
export function horizonWords(k: number): string {
  return k === 1 ? "the next session’s close" : `the close of the ${["", "1st", "2nd", "3rd", "4th", "5th"][k] ?? `${k}th`} session after the open`;
}

/** Sentiment class of a score: up above +band, dn below -band, else flat. */
export function sentimentClass(v: number | null | undefined, band: number): "up" | "dn" | "flat" {
  if (v === null || v === undefined) return "flat";
  return v > band ? "up" : v < -band ? "dn" : "flat";
}

/** x position (0..64) of a probability on the odds meter, which spans 0.30..0.70 and clamps to its ends. */
export function oddsPosition(p: number): number {
  return Math.max(4, Math.min(60, ((p - 0.3) / 0.4) * 64));
}
