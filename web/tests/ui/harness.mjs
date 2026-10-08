// The UI test harness of the cockpit (B7, Wave 4). Runs the built app (`next start`, after `npm run build`) with every
// /api/v1 read answered from a fixture (default: the page's approved mockup data, design/mockups/<page>/data.json, as
// the endpoint's envelope), and for each case at each width:
//   - fails on console errors or warnings, page errors, any request that leaves the app's origin (no CDN, no font),
//     horizontal page overflow, elements past the viewport edge, and missing expected texts or selectors;
//   - checks the keyboard path (the first Tab stop is the skip link) and that the Paper rules show;
//   - writes app-<width>-full.png and, where the mockup has a screenshot at that width, compare-<width>.png (the mockup
//     left, the app right) for the side-by-side review against the mockup. The comparison is for review: pixel
//     equality is not required, so it never fails the run.
// Usage (from web/): node tests/ui/harness.mjs [--only <case-name-substring>] [--port 3123] [--out ../work/ui]
// Cases live in tests/ui/cases/*.mjs (one file per page session; each exports `cases`, an array, see cases/shell.mjs).
// Playwright is the machine's global 1.56.1 (CI installs it the same way), launched on the preinstalled Chromium.
// Fonts: the app self-hosts the design's face Inter (styles/fonts.css), so text widths do not depend on the machine;
// every case checks that the self-hosted Inter loaded. `--fallback-fonts` blocks the font files and hides any
// installed Inter from the browser (it falls back to the next installed face, e.g. DejaVu Sans) to check the pages
// also hold when the font cannot load; there, width findings are advisory (WIDE) and other findings still fail.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { apiFixture } from "./fixtures.mjs";

const web = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const repo = join(web, "..");
const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const port = Number(arg("--port", "3123"));
const out = resolve(arg("--out", join(repo, "work", "ui")));
const only = arg("--only", "");
const fallbackFonts = process.argv.includes("--fallback-fonts");
const origin = `http://127.0.0.1:${port}`;

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  try {
    return require("playwright");
  } catch {
    const globalRoot = execSync("npm root -g").toString().trim();
    return require(join(globalRoot, "playwright"));
  }
}

/** The face fontconfig gives for Inter ("" when fc-match is missing); reported in the fallback run. */
function interFace(env = process.env) {
  try {
    return execSync("fc-match -f '%{family}' Inter", { env }).toString();
  } catch {
    return "";
  }
}

/** The browser's environment: as is, or (--fallback-fonts) with a fontconfig file that rejects every Inter face. */
function browserEnv() {
  if (!fallbackFonts) return process.env;
  const dir = join(out, "_fontconfig");
  mkdirSync(dir, { recursive: true });
  const file = join(dir, "fonts.conf");
  writeFileSync(
    file,
    `<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n` +
      `  <selectfont><rejectfont><pattern><patelt name="family"><string>Inter</string></patelt></pattern>` +
      `<pattern><patelt name="family"><string>Inter Display</string></patelt></pattern></rejectfont></selectfont>\n</fontconfig>\n`,
  );
  return { ...process.env, FONTCONFIG_FILE: file };
}

async function launch(chromium, env) {
  const candidates = ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium"];
  for (const executablePath of candidates) if (existsSync(executablePath)) return chromium.launch({ executablePath, env });
  return chromium.launch({ env });
}

async function loadCases() {
  const dir = join(web, "tests", "ui", "cases");
  const all = [];
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".mjs")).sort()) {
    const mod = await import(pathToFileURL(join(dir, file)).href);
    for (const c of mod.cases ?? []) all.push({ file, ...c });
  }
  return all.filter((c) => !only || c.name.includes(only));
}

async function startServer() {
  const busy = await fetch(origin + "/").then(() => true, () => false);
  if (busy) throw new Error(`port ${port} is already serving; stop that server or pass --port`);
  const server = spawn(process.execPath, [join(web, "node_modules", "next", "dist", "bin", "next"), "start", "-p", String(port), "-H", "127.0.0.1"], {
    cwd: web,
    env: { ...process.env, MB_GATEWAY: "", NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let log = "";
  server.stdout.on("data", (d) => (log += d));
  server.stderr.on("data", (d) => (log += d));
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(origin + "/_ui_harness_ping");
      if (res.status) return server;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  server.kill();
  throw new Error("next start did not come up:\n" + log);
}

/* Next.js prefetches the stylesheet of a page a visible link points to; when that page is not opened within a few
   seconds Chromium logs this warning. It is about a prefetch of our own origin, not an error of the page under test. */
const BENIGN_CONSOLE = [/^The resource http:\/\/127\.0\.0\.1:\d+\/_next\/static\/css\/[0-9a-f]+\.css was preloaded using link preload but not used/];

/* In the fallback run the font requests are aborted on purpose. */
const FONT_BLOCKED = /^Failed to load resource: net::ERR_FAILED/;

const MOCKUP_SHOT = (mockup, width, market) => join(repo, "design", "mockups", mockup, `shot-${market === "us" ? "us-" : ""}${width}-full.png`);

async function compareImage(browser, mockupPng, appPng, target, title) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const b64 = (p) => "data:image/png;base64," + readFileSync(p).toString("base64");
  await page.setContent(
    `<!doctype html><html><body style="margin:0;font:13px sans-serif;background:#ddd">
     <div style="display:flex;gap:12px;padding:12px;align-items:flex-start">
       <figure style="margin:0;flex:1"><figcaption>mockup · ${title}</figcaption><img style="width:100%" src="${b64(mockupPng)}"></figure>
       <figure style="margin:0;flex:1"><figcaption>app · ${title}</figcaption><img style="width:100%" src="${b64(appPng)}"></figure>
     </div></body></html>`,
  );
  await page.screenshot({ path: target, fullPage: true });
  await page.close();
}

async function runCase(browser, c) {
  const errors = [];
  const shots = [];
  const widths = c.widths ?? [1280, 390];
  const market = c.market ?? "india";
  for (const width of widths) {
    const mobile = width < 600;
    const ctx = await browser.newContext({ viewport: { width, height: mobile ? 844 : 900 }, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile });
    const page = await ctx.newPage();
    const tag = `${c.name} @${width}`;
    page.on("console", (m) => {
      if ((m.type() === "error" || m.type() === "warning") && ![...BENIGN_CONSOLE, ...(fallbackFonts ? [FONT_BLOCKED] : []), ...(c.allowConsole ?? [])].some((re) => re.test(m.text()))) errors.push(`${tag} console.${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => errors.push(`${tag} pageerror: ${e.message}`));
    page.on("request", (r) => {
      const url = r.url();
      if (!url.startsWith(origin) && !url.startsWith("data:") && !url.startsWith("blob:")) errors.push(`${tag} external request ${url}`);
    });
    await page.route(`${origin}/api/v1/**`, async (route) => {
      try {
        await route.fulfill(await apiFixture(route.request().url(), c));
      } catch (error) {
        errors.push(`${tag} fixture failed for ${route.request().url()}: ${error.message}`);
        await route.fulfill({ status: 500, body: "fixture error" });
      }
    });
    // Same-origin routes outside /api/v1 a case answers itself: routes = {"/api/assistant": async (request) => ({status, body})}.
    if (fallbackFonts) await page.route((url) => url.origin === origin && url.pathname.startsWith("/fonts/"), (route) => route.abort());
    for (const [path, handler] of Object.entries(c.routes ?? {})) {
      await page.route((url) => url.origin === origin && url.pathname === path, async (route) => {
        try {
          const answer = await handler(route.request());
          await route.fulfill({ status: answer.status ?? 200, contentType: answer.contentType ?? "application/json", body: typeof answer.body === "string" ? answer.body : JSON.stringify(answer.body) });
        } catch (error) {
          errors.push(`${tag} route ${path} failed: ${error.message}`);
          await route.fulfill({ status: 500, body: "route error" });
        }
      });
    }
    const response = await page.goto(origin + c.path, { waitUntil: c.apiStatus === "slow" ? "load" : "networkidle" });
    if (!response || response.status() !== (c.status ?? 200)) errors.push(`${tag} HTTP ${response?.status()} (expected ${c.status ?? 200})`);
    await page.waitForTimeout(300);
    if (c.waitFor) await page.waitForSelector(c.waitFor, { timeout: 5000 }).catch(() => errors.push(`${tag} never showed ${c.waitFor}`));
    await page.evaluate(() => document.fonts.ready);
    if (!fallbackFonts && (c.status ?? 200) === 200) {
      const inter = await page.evaluate(() => [...document.fonts].some((f) => f.family.replace(/"/g, "") === "Inter" && f.status === "loaded"));
      if (!inter) errors.push(`${tag} the self-hosted Inter font did not load`);
    }
    const sw = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth));
    if (sw > width) errors.push(`${tag} horizontal overflow: ${sw} > ${width}`);
    const wide = await page.evaluate(
      (vw) =>
        Array.from(document.querySelectorAll("body *"))
          .filter((el) => {
            const r = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return r.right > vw + 1 && r.width > 0 && style.position !== "fixed" && style.visibility !== "hidden" && !el.closest(".md-table-wrap, .md-pre, pre, .mb-sidebar, .mb-chat-slot") && el.id !== "tip";
          })
          .slice(0, 6)
          .map((el) => `${el.tagName}.${el.className?.baseVal ?? el.className} ${Math.round(el.getBoundingClientRect().right)}`),
      width,
    );
    if (wide.length) errors.push(`${tag} elements past the edge: ${wide.join(" | ")}`);
    const text = await page.evaluate(() => document.body.innerText);
    for (const want of c.expectText ?? []) if (!text.includes(want)) errors.push(`${tag} missing text: ${want}`);
    for (const sel of c.expectSelector ?? []) if (!(await page.$(sel))) errors.push(`${tag} missing element: ${sel}`);
    const dir = join(out, c.name.replace(/[^a-z0-9-]+/gi, "_"));
    mkdirSync(dir, { recursive: true });
    const appPng = join(dir, `app-${width}-full.png`);
    await page.screenshot({ path: appPng, fullPage: true });
    shots.push(appPng);
    if (c.keyboard !== false) {
      await page.keyboard.press("Tab");
      const first = await page.evaluate(() => document.activeElement?.className ?? "");
      if (!String(first).includes("mb-skip")) errors.push(`${tag} first Tab stop is "${first}", not the skip link`);
    }
    if (c.check) {
      for (const problem of (await c.check(page, { width, market })) ?? []) errors.push(`${tag} ${problem}`);
    }
    if (c.mockup) {
      const mockupPng = MOCKUP_SHOT(c.mockup, width, market);
      if (existsSync(mockupPng)) {
        const comparePng = join(dir, `compare-${width}.png`);
        await compareImage(browser, mockupPng, appPng, comparePng, `${c.mockup} ${market} ${width}px`);
        shots.push(comparePng);
      }
    }
    await ctx.close();
  }
  return { name: c.name, file: c.file, errors, shots };
}

const cases = await loadCases();
if (!cases.length) {
  console.error("no UI case matches");
  process.exit(1);
}
if (!existsSync(join(web, ".next", "BUILD_ID"))) {
  console.error("run `npm run build` first");
  process.exit(1);
}
const env = browserEnv();
if (fallbackFonts) console.log(`fallback fonts: the self-hosted Inter is blocked and any installed Inter hidden; the browser uses "${interFace(env)}" (advisory)`);
const { chromium } = loadPlaywright();
const server = await startServer();
process.on("exit", () => server.kill());
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => process.exit(130));
const browser = await launch(chromium, env);
const results = [];
try {
  for (const c of cases) {
    try {
      results.push(await runCase(browser, c));
    } catch (error) {
      results.push({ name: c.name, file: c.file, errors: [`${c.name} crashed: ${error.message.split("\n")[0]}`], shots: [] });
    }
  }
} finally {
  await browser.close();
  server.kill();
}
mkdirSync(out, { recursive: true });
writeFileSync(join(out, "report.json"), JSON.stringify(results, null, 2));
/* In the fallback run only width findings (overflow, elements past the edge, tables wider than their wrapper) are
   advisory: they are what a different face changes. Every other finding still fails the run. */
const WIDTH_FINDING = /horizontal overflow|elements past the edge|wider than its wrapper/;
const blocking = (e) => !(fallbackFonts && WIDTH_FINDING.test(e));
let failed = 0;
let advisory = 0;
for (const r of results) {
  const hard = r.errors.filter(blocking);
  if (hard.length) failed++;
  else if (r.errors.length) advisory++;
  console.log(`${hard.length ? "FAIL" : r.errors.length ? "WIDE" : "ok  "} ${r.name} (${r.file})`);
  for (const e of r.errors) console.log(`     ${blocking(e) ? "" : "(advisory) "}${e}`);
}
console.log(`${results.length} cases, ${failed} failed${fallbackFonts ? `, ${advisory} with advisory width findings only` : ""}; screenshots and comparisons in ${out}`);
process.exit(failed ? 1 : 0);
