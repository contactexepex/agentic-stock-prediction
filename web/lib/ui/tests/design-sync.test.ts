// The app's design copies equal design/ (tools/sync-design.mjs), and the vendored chart library is the pinned file.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { LIGHTWEIGHT_CHARTS } from "../vendor.ts";

const web = join(import.meta.dirname, "..", "..", "..");

test("design copies are current", async () => {
  const { staleCopies } = await import(join(web, "tools", "sync-design.mjs"));
  assert.deepEqual(staleCopies(), []);
});

test("the vendored chart library matches its pin, its NOTICE and the dashboard's copy", () => {
  const file = readFileSync(join(web, "public", LIGHTWEIGHT_CHARTS.src));
  const hex = createHash("sha256").update(file).digest("hex");
  assert.equal(hex, LIGHTWEIGHT_CHARTS.sha256);
  assert.equal("sha256-" + createHash("sha256").update(file).digest("base64"), LIGHTWEIGHT_CHARTS.integrity);
  const notice = readFileSync(join(web, "public", "vendor", `lightweight-charts-${LIGHTWEIGHT_CHARTS.version}`, "NOTICE"), "utf8");
  assert.ok(notice.includes(hex) && notice.includes(LIGHTWEIGHT_CHARTS.integrity));
  const dashboard = readFileSync(join(web, "..", "scripts", "marketbrief", "presentation", "dashboard", "vendor", "lightweight-charts.standalone.production.js"));
  assert.equal(createHash("sha256").update(dashboard).digest("hex"), hex);
});

test("no stylesheet or component loads anything from another origin", () => {
  for (const f of ["styles/tokens.css", "styles/components.css", "styles/page.css", "styles/app.css", "app/layout.tsx", "components/charts/candles.tsx"]) {
    const text = readFileSync(join(web, f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.ok(!/@import|url\(\s*["']?https?:|src=["']https?:/.test(text), f);
  }
});
