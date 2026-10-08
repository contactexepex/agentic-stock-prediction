// Vendored browser libraries served from web/public/vendor/ (never a CDN). Each pins its URL and its SHA-256, which
// the browser checks through Subresource Integrity; web/lib/ui/tests/design-sync.test.ts checks the files against these.

export const LIGHTWEIGHT_CHARTS = {
  version: "5.2.1",
  src: "/vendor/lightweight-charts-5.2.1/lightweight-charts.standalone.production.js",
  sha256: "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf",
  integrity: "sha256-4hzFyqAibvML2FScULnvkmYV8qTua05IY1NHelX1mM8=",
} as const;
