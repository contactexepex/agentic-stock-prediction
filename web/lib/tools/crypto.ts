// Web Crypto helpers (work in the Edge middleware and in Node route handlers alike).

const encoder = new TextEncoder();

export function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function fromBase64url(text: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]*$/.test(text)) return null;
  const padded = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4);
  try {
    const binary = atob(padded);
    return Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    return null;
  }
}

export function hexOf(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(text: string): Promise<string> {
  return hexOf(new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text))));
}

export async function sha256Base64url(text: string): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text))));
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

export async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await hmacKey(secret);
  return hexOf(new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(message))));
}

/** Constant-time check of an HMAC-SHA256 (crypto.subtle.verify compares in constant time). */
export async function hmacVerify(secret: string, message: string, signature: Uint8Array): Promise<boolean> {
  const key = await hmacKey(secret);
  return crypto.subtle.verify("HMAC", key, signature as BufferSource, encoder.encode(message));
}

export function bytesFromHex(hex: string): Uint8Array | null {
  if (!/^(?:[0-9a-f]{2})+$/i.test(hex)) return null;
  return Uint8Array.from(hex.match(/../g) ?? [], (pair) => parseInt(pair, 16));
}

export function randomKey(prefix: string, bytes = 15): string {
  return prefix + base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

/** JSON with object keys sorted at every level (stable hashes of arguments). */
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.keys(value as Record<string, unknown>)
      .sort()
      .filter((key) => (value as Record<string, unknown>)[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

const TOKEN_PREFIX = "mb1";

/** A signed, unencrypted token: mb1.<base64url(JSON)>.<base64url(HMAC)>. Never put a secret in the payload. */
export async function signToken(secret: string, payload: Record<string, unknown>): Promise<string> {
  const body = base64url(encoder.encode(JSON.stringify(payload)));
  const key = await hmacKey(secret);
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(`${TOKEN_PREFIX}.${body}`)));
  return `${TOKEN_PREFIX}.${body}.${base64url(signature)}`;
}

/** The payload of a token signed with `secret`, or null when malformed, forged or expired (`exp` in epoch seconds). */
export async function verifyToken(
  secret: string,
  token: string,
  nowSeconds: number,
): Promise<Record<string, unknown> | null> {
  if (typeof token !== "string" || token.length > 8192) return null;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== TOKEN_PREFIX) return null;
  const signature = fromBase64url(parts[2]);
  if (!signature) return null;
  if (!(await hmacVerify(secret, `${TOKEN_PREFIX}.${parts[1]}`, signature))) return null;
  const bytes = fromBase64url(parts[1]);
  if (!bytes) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const exp = (payload as Record<string, unknown>).exp;
  if (typeof exp !== "number" || exp <= nowSeconds) return null;
  return payload as Record<string, unknown>;
}
