// POST /api/v1/markets/{market}/companies/commands (api/paths/companies.yaml createCompanyCommand; B11): a confirmed
// company command (add, deactivate, reactivate, change amount, delete) through B5's tool layer with the dashboard
// identity; pending in the inbox until company.py import-inbox. Refused in gateway mode (middleware and the tool layer).
import { submitCompanyCommand } from "../../../../../../../lib/data/company-commands.ts";
import { dashboardContext, toolLayerFromEnv } from "../../../../../../../lib/tools/index.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return submitCompanyCommand(request, (await params).market, toolLayerFromEnv(), dashboardContext());
}
