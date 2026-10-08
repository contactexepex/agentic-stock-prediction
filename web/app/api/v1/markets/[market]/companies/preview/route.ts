// POST /api/v1/markets/{market}/companies/preview (api/paths/companies.yaml previewCompanyCommand; B11): the summary
// the owner confirms before a company command, through B5's tool layer with the dashboard identity. Nothing is written.
// Refused in gateway mode (middleware and the tool layer).
import { previewCompanyCommand } from "../../../../../../../lib/data/company-commands.ts";
import { dashboardContext, toolLayerFromEnv } from "../../../../../../../lib/tools/index.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return previewCompanyCommand(request, (await params).market, toolLayerFromEnv(), dashboardContext());
}
