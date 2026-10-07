// Fixed names of the deployment (orchestrator, 2026-10-07; docs/ws/b5.md). Not secrets, so not environment variables.
export const GATEWAY_URL = "https://market-brief-gateway.vercel.app";   // Vercel project market-brief-gateway (MB_GATEWAY=1)
export const APP_URL = "https://market-brief-app.vercel.app";           // Vercel project market-brief-app (Vercel Authentication)
export const SLACK_CHANNEL_ID = "C0C6REB7QS2";                          // #market-brief (config/settings.yaml slack_channel_id)
export const GITHUB_REPOSITORY = "contactexepex/agentic-stock-prediction";
export const DISPATCH_WORKFLOW = "onboard.yml";
export const DISPATCH_REF = "main";
export const MOTHERDUCK_PG_HOST = "pg.eu-central-1-aws.motherduck.com";
export const READ_DATABASE = "market_brief";
export const INBOX_DATABASE = "market_brief_inbox";
/** OAuth redirect URIs a dynamically registered MCP client may use (the Claude app's callbacks). */
export const ALLOWED_REDIRECTS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"];
/** Identifying User-Agent for www.sec.gov (no email: the repository's public URL). */
export const SEC_USER_AGENT = "market-brief research (https://github.com/contactexepex/agentic-stock-prediction)";
