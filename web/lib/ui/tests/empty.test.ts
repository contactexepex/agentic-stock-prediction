import assert from "node:assert/strict";
import { test } from "node:test";
import { finishesOn, firstExit, noneFinishedYet, runningLine, tooEarly } from "../empty.ts";

const trades = [{ exit_date: "2026-10-16" }, { exit_date: "2026-10-13" }, { exit_date: null }];
const IST = "2026-10-12T08:41:00+05:30";

test("the first exit is the earliest stored exit date", () => {
  assert.equal(firstExit(trades), "2026-10-13");
  assert.equal(firstExit([]), null);
});

test("an empty settled list says when the first trades finish and when results appear", () => {
  assert.equal(
    noneFinishedYet(trades, "2026-10-13T12:15:00Z", "india", IST),
    "No paper trade has finished yet. The first ones finish at the close on Tue 13 Oct; results appear at the after-close run (next: 13 Oct 17:45 IST).",
  );
  assert.equal(
    noneFinishedYet([], null, "india", IST, "head-to-head trade"),
    "No head-to-head trade has finished yet. The first ones finish at the close of their exit day; results appear at that day’s after-close run.",
  );
});

test("running, too early and finishes words", () => {
  assert.equal(runningLine(trades), "3 running · first finishes Tue 13 Oct");
  assert.equal(runningLine([]), "none running yet");
  assert.equal(tooEarly(3), "too early to tell: 3 of 20 finished trades");
  assert.equal(finishesOn("2026-10-13"), "finishes Tue 13 Oct");
  assert.equal(finishesOn(null), "not finished yet");
});
