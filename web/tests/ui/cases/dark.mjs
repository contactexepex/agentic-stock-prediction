// Dark-mode cases (UX4): every page of the cockpit, with the device set to dark (prefers-color-scheme), at 1280 and
// 390, with the text contrast check (tests/ui/contrast.mjs). Each reuses a light case of its page session (same
// fixtures, texts and checks) and drops the mockup comparison, since the mockups' shots are light. `theme-toggle`
// checks the top bar's button: the cycle, the saved choice, and that a saved choice applies before the first paint.
import { cases as assistant } from "./assistant.mjs";
import { cases as companies } from "./companies.mjs";
import { cases as company } from "./company.mjs";
import { cases as help } from "./help.mjs";
import { cases as home } from "./home.mjs";
import { cases as news } from "./news.mjs";
import { cases as portfolios } from "./paper-portfolios.mjs";
import { cases as ruleVsAi } from "./rule-vs-ai.mjs";
import { cases as shell } from "./shell.mjs";
import { cases as lab } from "./strategy-lab.mjs";
import { cases as track } from "./track-record.mjs";
import { cases as watchlist } from "./watchlist.mjs";

const ALL = [...assistant, ...companies, ...company, ...help, ...home, ...news, ...portfolios, ...ruleVsAi, ...shell, ...lab, ...track, ...watchlist];

const LIGHT_CASES = [
  "home-india", "home-us", "watchlist-india", "news-india", "companies-india", "company-reliance", "company-aapl",
  "lifecycle-reliance", "strategies-reliance", "strategy-lab-india", "rule-vs-ai-india", "paper-portfolio-v3-india",
  "paper-portfolio-v3-finished", "paper-portfolio-v3-story", "track-record-india", "help-india", "assistant-india",
  "gallery",
];

function darkOf(name) {
  const light = ALL.find((c) => c.name === name);
  if (!light) throw new Error(`dark.mjs: no light case named ${name}`);
  const { mockup, ...rest } = light;
  return { ...rest, name: `dark-${name}`, theme: "dark", contrast: true, widths: [1280, 390] };
}

const THEME_BTN = ".mb-theme-btn";

/** Light device: System shows light; Light, then Dark; the saved Dark applies on reload before the first paint. */
async function toggleChecks(page) {
  const problems = [];
  const state = () => page.evaluate(() => ({ attr: document.documentElement.getAttribute("data-theme"), saved: (() => { try { return localStorage.getItem("mb-theme"); } catch { return "blocked"; } })(), bg: getComputedStyle(document.body).backgroundColor }));
  const lightBg = (await state()).bg;
  const choice = () => page.getAttribute(THEME_BTN, "data-theme-choice");
  if ((await choice()) !== "system") problems.push(`first choice is ${await choice()}, not system`);
  await page.click(THEME_BTN);
  let s = await state();
  if ((await choice()) !== "light" || s.attr !== "light" || s.saved !== "light") problems.push(`after one press: ${JSON.stringify(s)}`);
  await page.click(THEME_BTN);
  s = await state();
  if ((await choice()) !== "dark" || s.attr !== "dark" || s.saved !== "dark") problems.push(`after two presses: ${JSON.stringify(s)}`);
  if (s.bg === lightBg) problems.push("Dark did not change the page background");
  // Reload: the boot script in <head> sets data-theme before the body is parsed, so the first paint is dark.
  const seen = [];
  await page.exposeFunction("__mbSeenTheme", (v) => seen.push(v));
  await page.addInitScript(() => {
    new MutationObserver((_, o) => {
      if (document.body) {
        window.__mbSeenTheme("body:" + document.documentElement.getAttribute("data-theme"));
        o.disconnect();
      }
    }).observe(document, { childList: true, subtree: true });
  });
  await page.reload({ waitUntil: "networkidle" });
  if (seen[0] !== "body:dark") problems.push(`on reload the body started with data-theme ${seen[0]}`);
  if ((await choice()) !== "dark") problems.push(`after reload the button shows ${await choice()}`);
  await page.click(THEME_BTN);
  s = await state();
  if ((await choice()) !== "system" || s.attr !== null || s.saved !== null) problems.push(`back to system: ${JSON.stringify(s)}`);
  if (s.bg !== lightBg) problems.push("System on a light device did not show light");
  return problems;
}

/** A dark device with Light chosen shows light; storage that throws leaves System and the page working. */
async function overrideChecks(page) {
  const problems = [];
  const darkBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.click(THEME_BTN);
  const lightBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (lightBg === darkBg) problems.push("Light on a dark device did not change the background");
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
  });
  await page.reload({ waitUntil: "networkidle" });
  const after = await page.evaluate(() => ({ attr: document.documentElement.getAttribute("data-theme"), bg: getComputedStyle(document.body).backgroundColor }));
  if (after.attr !== null || after.bg !== darkBg) problems.push(`blocked storage: ${JSON.stringify(after)}`);
  await page.click(THEME_BTN);
  if ((await page.getAttribute(THEME_BTN, "data-theme-choice")) !== "light") problems.push("with blocked storage the button did not move to Light");
  return problems;
}

export const cases = [
  ...LIGHT_CASES.map(darkOf),
  { name: "theme-toggle", path: "/india", themeFixed: true, widths: [1280, 390], waitFor: ".phead", check: toggleChecks },
  { ...darkOf("paper-portfolio-v3-india"), name: "theme-override-on-dark-device", themeFixed: true, widths: [1280], contrast: false, expectText: [], check: overrideChecks },
];
