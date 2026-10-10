// RFC 9457 problem responses of the /api/v1 routes (api/openapi.yaml Problem). Never any driver or secret text.
import { fallbackLinks } from "./constants.ts";

export interface Problem {
  type?: string;
  title: string;
  status: number;
  detail?: string;
  fallback_links?: string[];
}

const NO_STORE = { "Cache-Control": "no-store", "Content-Type": "application/problem+json" };

export function problem(status: number, title: string, detail?: string, market?: string): Response {
  const body: Problem = { title, status };
  if (detail) body.detail = detail;
  if (market && status === 503) body.fallback_links = fallbackLinks(market);
  return new Response(JSON.stringify(body), { status, headers: NO_STORE });
}

export const notFound = (detail: string) => problem(404, "Not found", detail);
export const unavailable = (market: string) =>
  problem(503, "Data service unavailable", "The read models cannot be read right now; try again shortly.",
    market);
export const invalid = (detail: string) => problem(422, "Invalid request", detail);
export const unauthorized = () => problem(401, "Unauthorized");
