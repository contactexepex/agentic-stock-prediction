// Text helpers: secret redaction, Slack escaping, money in the market currency.

/** Replaces every secret value (and common token shapes) in `text` with [redacted]. */
export function redact(text: string, secrets: string[]): string {
  let out = text;
  for (const secret of secrets) {
    if (secret && secret.length >= 6) out = out.split(secret).join("[redacted]");
  }
  return out
    .replace(/xox[abposr]-[A-Za-z0-9-]{10,}/g, "[redacted]")
    .replace(/\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}/g, "[redacted]")
    .replace(/\bsk-ant-[A-Za-z0-9_-]{10,}/g, "[redacted]")
    .replace(/\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, "[redacted]");
}

/** Argument names whose values are never logged. */
const SECRET_NAME = /token|secret|password|authorization|cookie|api[_-]?key/i;

/** Arguments as logged: secret-named keys dropped, strings redacted and capped, at most 4000 characters of JSON. */
export function loggableArguments(args: unknown, secrets: string[]): unknown {
  if (!args || typeof args !== "object" || Array.isArray(args)) return null;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(args as Record<string, unknown>).slice(0, 30)) {
    const safeKey = key.slice(0, 64);
    if (SECRET_NAME.test(safeKey)) continue;
    if (typeof value === "string") out[safeKey] = redact(value.slice(0, 500), secrets);
    else if (typeof value === "number" || typeof value === "boolean" || value === null) out[safeKey] = value;
    else out[safeKey] = "[omitted]";
  }
  const json = JSON.stringify(out);
  return json.length <= 4000 ? out : { truncated: true };
}

/** Escapes `&`, `<` and `>` for Slack mrkdwn, so user text cannot ping (<!channel>, <@U...>) or make a labelled link
 * (<url|label>). Bare URLs still auto-link and `*_~` still format. */
export function slackEscape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export const CURRENCY: Record<"india" | "us", "INR" | "USD"> = { india: "INR", us: "USD" };
export const DEFAULT_AMOUNT: Record<"india" | "us", number> = { india: 100000, us: 1000 }; // decisions 26, 44

export function money(market: "india" | "us", amount: number): string {
  const locale = market === "india" ? "en-IN" : "en-US";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: CURRENCY[market],
    maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
  }).format(amount);
}
