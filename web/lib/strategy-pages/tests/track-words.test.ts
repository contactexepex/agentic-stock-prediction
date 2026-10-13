import assert from "node:assert/strict";
import { test } from "node:test";
import { aucWords, brierWords } from "../track-record.ts";

test("Brier and AUC in words", () => {
  assert.equal(brierWords(0.2), "more honest than a coin flip");
  assert.equal(brierWords(0.25), "about as good as a coin flip");
  assert.equal(brierWords(0.3), "worse than a coin flip");
  assert.equal(brierWords(null), "not measured yet");
  assert.equal(aucWords(0.55, 0.51), "yes");
  assert.equal(aucWords(0.52, 0.49), "slightly");
  assert.equal(aucWords(0.49, 0.47), "no");
});
