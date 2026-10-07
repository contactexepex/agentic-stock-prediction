// Command ids as core/schema_lifecycle.py defines them:
// cmd-<received_at as YYYYMMDDTHHMMSSZ>-<first 8 hex of sha256(idempotency_key), or of the arguments as JSON with
// sorted keys for a read without a key>.
import { sha256Hex, stableJson } from "./crypto.ts";

export function compactTime(at: Date): string {
  return at.toISOString().replace(/\.\d{3}Z$/, "Z").replace(/[-:]/g, "");
}

export async function commandId(receivedAt: Date, idempotencyKey: string | null, args: unknown): Promise<string> {
  const basis = idempotencyKey ?? stableJson(args ?? {});
  return `cmd-${compactTime(receivedAt)}-${(await sha256Hex(basis)).slice(0, 8)}`;
}

export function utcDayStart(at: Date): string {
  return `${at.toISOString().slice(0, 10)}T00:00:00Z`;
}
