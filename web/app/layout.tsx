// Root layout of the cockpit app (B7): the design system's styles (unchanged copies of design/, tools/sync-design.mjs)
// plus the app's additions, and the icon sprite inlined once. No font, script or stylesheet from a CDN. Route handlers
// (/api, /slack, /mcp) do not render layouts. The design's font, Inter, is self-hosted (styles/fonts.css) and its
// latin subset preloaded.
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { ICON_SPRITE } from "../components/icons/sprite.generated.ts";
import { INTER_FONT } from "../lib/ui/vendor.ts";
import "../styles/fonts.css";
import "../styles/tokens.css";
import "../styles/components.css";
import "../styles/page.css";
import "../styles/app.css";

export const metadata: Metadata = {
  title: { default: "Market brief", template: "Market brief · %s" },
  description: "Personal research cockpit: paper strategies, AI traders and their track record per market. Research only, every signal Paper; nothing here is investment advice.",
  robots: { index: false, follow: false },
  // Favicon: a small rising chart line, inlined as a data URI (no extra route through the gateway).
  icons: { icon: { url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231e3a8a'/%3E%3Cpolyline points='6,22 12,16 17,19 26,9' fill='none' stroke='%23fff' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3Ccircle cx='26' cy='9' r='3' fill='%2334d399'/%3E%3C/svg%3E", type: "image/svg+xml" } },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href={INTER_FONT.preload} as="font" type="font/woff2" crossOrigin="anonymous" />
      </head>
      <body>
        {/* A static constant from the repo (Material Symbols sprite), never data. */}
        <div aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICON_SPRITE }} />
        {children}
      </body>
    </html>
  );
}
