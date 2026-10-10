// Gateway mode (MB_GATEWAY=1, the second Vercel project without Vercel Authentication; docs/SPEC.md F10): only
// /slack/* (each request verified with Slack's signing secret and refused when older than 5 minutes), /mcp (GitHub
// OAuth, the owner's account only) and the OAuth routes of the MCP sign-in (/oauth/*, /.well-known/oauth-*, rewritten
// to their handlers under /mcp/oauth/) and GET /brief/{india|us}/{date}-{32 hex} (the public daily brief, C2's
// read-only handler); everything else is a 404. In the dashboard
// deployment (behind Vercel Authentication) those routes are a 404 and everything else passes.
import { NextResponse, type NextRequest } from "next/server";
import { gatewayDecision } from "./lib/tools/gateway.ts";
import { verifySlackRequest } from "./app/slack/_lib/verify.ts";

const notFound = () => new NextResponse("Not Found", { status: 404, headers: { "Cache-Control": "no-store" } });

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const gateway = process.env.MB_GATEWAY === "1";
  const decision = gatewayDecision(request.nextUrl.pathname, request.method, gateway);
  switch (decision.action) {
    case "next":
      return NextResponse.next();
    case "rewrite":
      return NextResponse.rewrite(new URL(decision.target, request.url));
    case "slack": {
      const raw = await request.clone().text();
      const verdict = await verifySlackRequest(
        process.env.SLACK_SIGNING_SECRET?.trim() || null,
        request.headers.get("x-slack-request-timestamp"),
        request.headers.get("x-slack-signature"),
        raw,
        Math.floor(Date.now() / 1000),
      );
      return verdict.ok ? NextResponse.next() : new NextResponse("invalid request", { status: 401 });
    }
    default:
      return notFound();
  }
}

export const config = { matcher: "/:path*" };
