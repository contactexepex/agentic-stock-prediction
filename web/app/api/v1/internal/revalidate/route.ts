// POST /api/v1/internal/revalidate (api/openapi.yaml revalidateReadModels): called by the warehouse sync after a
// build commits (scripts/marketbrief/warehouse/revalidate.py), with REVALIDATE_SECRET.
import { revalidateTag } from "next/cache";
import { handleRevalidate } from "../../../../../lib/data/revalidate.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: Request): Promise<Response> {
  return handleRevalidate(request, process.env.REVALIDATE_SECRET?.trim() || null, (tag) => revalidateTag(tag));
}
