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
