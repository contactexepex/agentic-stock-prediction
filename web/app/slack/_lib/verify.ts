// Slack request signing (https://api.slack.com/authentication/verifying-requests-from-slack): v0=HMAC-SHA256 of
// "v0:<timestamp>:<raw body>" with the signing secret; requests older than 5 minutes are refused (replay guard).
// Web Crypto only, so the Edge middleware and the Node route handlers share it.
import { bytesFromHex, hmacVerify } from "../../../lib/tools/crypto.ts";

export const MAX_AGE_SECONDS = 300;

export type Verdict = { ok: true } | { ok: false; reason: "no_secret" | "missing_headers" | "stale" | "bad_signature" };

export async function verifySlackRequest(
  secret: string | null,
  timestamp: string | null,
  signature: string | null,
  rawBody: string,
  nowSeconds: number,
): Promise<Verdict> {
  if (!secret) return { ok: false, reason: "no_secret" };
  if (!timestamp || !signature || !/^\d{1,12}$/.test(timestamp)) return { ok: false, reason: "missing_headers" };
  if (Math.abs(nowSeconds - Number(timestamp)) > MAX_AGE_SECONDS) return { ok: false, reason: "stale" };
  if (!signature.startsWith("v0=")) return { ok: false, reason: "bad_signature" };
  const bytes = bytesFromHex(signature.slice(3));
  if (!bytes || bytes.length !== 32) return { ok: false, reason: "bad_signature" };
  const valid = await hmacVerify(secret, `v0:${timestamp}:${rawBody}`, bytes);
  return valid ? { ok: true } : { ok: false, reason: "bad_signature" };
}

/** Reads and verifies a request; returns the raw body when it is Slack's, else null. */
export async function verifiedBody(request: Request, secret: string | null, nowSeconds: number): Promise<string | null> {
  const raw = await request.text();
  if (raw.length > 100_000) return null;
  const verdict = await verifySlackRequest(
    secret,
    request.headers.get("x-slack-request-timestamp"),
    request.headers.get("x-slack-signature"),
    raw,
    nowSeconds,
  );
  return verdict.ok ? raw : null;
}
