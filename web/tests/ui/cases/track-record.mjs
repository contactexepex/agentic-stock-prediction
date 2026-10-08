// UI cases of page 08, Track record (B16), at the mockup's widths (design/mockups/08-track-record/shot-*-full.png):
// the mockup's data, the stored data of today (empty call blocks), a second scoring basis, and the error state.
import { storedApi } from "../b16/stored.mjs";
import { mockupPayload, envelope } from "../fixtures.mjs";

const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of 503/;
const PAPER = "Paper only — no proven edge yet";

/** The mockup payload with a second basis and a weekly series, to see the basis switch and the weekly card. */
function twoBases(rest, market) {
  if (rest !== "track-record") return undefined;
  const p = structuredClone(mockupPayload("08-track-record", market));
  const second = { ...structuredClone(p.track.calls[0]), basis: "open_to_close", key: "open_to_close", label: "open→close" };
  second.all = { ...second.all, n: 12, hits: 8, share: 0.6667 };
  p.track.calls.push(second);
  p.weekly = [
    { basis: "close_to_close", key: "close_to_close", label: "close→close", weeks: [{ week: "2026-W40", n: 4, hits: 2, share: 0.5, wilson_lo: 0.15, wilson_hi: 0.85, brier: 0.2517, log_loss: 0.6964 }] },
    { basis: "open_to_close", key: "open_to_close", label: "open→close", weeks: [{ week: "2026-W41", n: 12, hits: 8, share: 0.6667, wilson_lo: 0.39, wilson_hi: 0.86, brier: 0.231, log_loss: 0.651 }] },
  ];
  return { status: 200, body: envelope(market, "_", p) };
}

export const cases = [
  {
    name: "track-record-india",
    path: "/india/track-record",
    mockup: "08-track-record",
    widths: [1280, 390],
    waitFor: ".cal svg",
    expectText: [PAPER, "Calls by scoring basis", "not enough history yet", "Calibration", "Signal model back-test", "Momentum (5 days)", "fewer than 20 dates", "No rule-only replay stored by the cut-off.", "No week of close→close calls scored yet."],
    expectSelector: [".p-track .ci svg", ".p-track .cal circle.pt.empty", ".p-track tr.grp"],
  },
  { name: "track-record-us", path: "/us/track-record", market: "us", mockup: "08-track-record", widths: [1280], waitFor: ".phead", expectText: [PAPER, "Calls by scoring basis"] },
  {
    name: "track-record-stored-india",
    path: "/india/track-record",
    api: storedApi,
    widths: [1280, 390],
    waitFor: ".phead",
    expectText: [PAPER, "No direction call has been scored yet.", "No call scored yet, so no calibration.", "No range is scored yet", "No call scored yet, so no weekly series.", "Verdict."],
  },
  {
    name: "track-record-basis-switch",
    path: "/india/track-record",
    api: twoBases,
    widths: [1280],
    waitFor: ".cal svg",
    check: async (page) => {
      const problems = [];
      const weekly = () => page.textContent('[aria-label="Accuracy over time"]');
      if (!(await weekly()).includes("2026-W40")) problems.push("weekly close→close week missing");
      await page.click('[aria-label="Scoring basis"] button:has-text("open→close")');
      const text = await weekly();
      if (!text.includes("2026-W41")) problems.push("the switch did not show the open→close week");
      if (text.includes("2026-W40")) problems.push("the close→close week still shows: bases pooled");
      return problems;
    },
  },
  { name: "track-record-error", path: "/india/track-record", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again"] },
];
