import type { NextConfig } from "next";

// One app, two Vercel projects (docs/SPEC.md F10): the dashboard behind Vercel Authentication, and the
// gateway (MB_GATEWAY=1) that serves only /slack/*, /mcp and the MCP OAuth routes (web/middleware.ts).
const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // Secrets are read on the server only (process.env in route handlers); nothing is exposed with NEXT_PUBLIC_.
  serverExternalPackages: ["pg"],
};

export default nextConfig;
