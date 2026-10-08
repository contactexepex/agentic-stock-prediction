// Vendored browser libraries served from web/public/vendor/ (never a CDN). Each pins its URL and its SHA-256, which
// the browser checks through Subresource Integrity; web/lib/ui/tests/design-sync.test.ts checks the files against these.

export const LIGHTWEIGHT_CHARTS = {
  version: "5.2.1",
  src: "/vendor/lightweight-charts-5.2.1/lightweight-charts.standalone.production.js",
  sha256: "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf",
  integrity: "sha256-4hzFyqAibvML2FScULnvkmYV8qTua05IY1NHelX1mM8=",
} as const;

/** Inter 5.2.8 (variable), self-hosted (public/fonts/inter-5.2.8/NOTICE); declared in styles/fonts.css. */
export const INTER_FONT = {
  version: "5.2.8",
  dir: "/fonts/inter-5.2.8",
  files: {
    "inter-latin-wght-normal.woff2": "3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62",
    "inter-latin-ext-wght-normal.woff2": "34b9c504cab7a73e37b746343a449132e56cf7b5481af2cb81dc74dcff25c956",
  },
  /** Preloaded by the root layout: the subset every page uses. */
  preload: "/fonts/inter-5.2.8/inter-latin-wght-normal.woff2",
} as const;
