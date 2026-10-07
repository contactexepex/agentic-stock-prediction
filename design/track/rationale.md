# Track record screen: rationale

Files: `template.html` + `build.py` (`--out DIR`, both markets in one page with an in-page India/US switch),
`track.html` (self-contained, no network), `data-track.json`, screenshots `shot-*.png`, `notes.md`. Same shell
and design system as the other screens (`design/system/`).

## What it is for
The owner's rule is that every signal stays Paper until proven. This screen is the proof gate: it says TRUSTED or
NOT YET and shows exactly why, separating what is live from what is a rehearsal on past prices (back-test).

## Plain language (second pass)
The first version was written for a statistician and the owner could not read it. It was rewritten so that every
block is a question with a one-sentence answer, and every number is "x out of 100" or money on 10,000: a reading
guide at the top; the verdict "in plain words"; three tests in plain words (enough real calls; when it says 70%
sure is it right 70% of the time; does it beat a coin); "promise vs reality" bars for the ranges; a "coin" chart for
direction (dashed line = the coin); a money table for the paper strategy. Brier, AUC, Wilson intervals, reliability
and the baseline tables moved to a folded "for the record" section at the bottom.

## Layout
1. **Verdict header** (red NOT YET today; dark green TRUSTED when all three gates pass) with the reason in
   one sentence, then the three gates as tiles with a progress bar each: enough live calls scored (0 of the
   50 per band that config/review.yaml requires), confidence bands keep their promise (no band has enough
   calls), model skill in the weekly review (n ok, Brier skill must be above 0, AUC's 95% low end must be above
   0.5: both fail on 6 Oct in both markets).
2. **Live record**: calls scored, calls made and open, ranges scored, ranges waiting (60 India / 40 US with
   their target dates), the calls-by-confidence-band table (empty state explains when it fills), lessons count.
3. **Weekly review**: week, model-skill verdict, scored counts, coverage and hit rates since start (none yet),
   sample size, proposals (India: "drop regime widening" from the history walk-forward), report path.
4. **Ranges in the back-test** (rule replay, tagged): 1-day / 5-day toggle; 80% and 50% held with the 95%
   interval, interval score ours vs naive; by regime (bars, amber when off target); by month (bar chart with the
   80% line); the replay's own summary sentences.
5. **Signal model in the back-test** (walk-forward, tagged): the four labels with Brier vs base, skill and AUC
   [95% CI] in green/red; the reliability chart for 5-day open-to-close (bins sized by rows, Wilson whiskers,
   the perfect-calibration diagonal); the latest fit's facts.
6. **Paper strategy after costs**: dot-and-whisker chart of mean return per trade with 95% intervals for the
   three thresholds and the four baselines; table with "vs always up" and whether the interval clears zero.
7. **Direction baselines** (always up, momentum, RSI; 1-day and 5-day hit rates with intervals) and the
   call-threshold table (long/short at 55/60/65%, Wilson intervals, hit after cost).
8. **By company**: replay coverage and scores per ticker (links to the decision pages), a live-calls column
   that fills as calls settle.
9. Collapsed: the back-tests' own limitations and the data sources.

## Real, back-test, derived
- Live: predictions, outcomes, ranges, range_record, open_ranges, open_predictions, lessons, reviews.
- Back-test: replay JSON (coverage, scores, baselines) and the model back-test JSON (Brier, AUC, reliability,
  thresholds, paper strategy), every block tagged.
- Derived: the PROVEN / NOT PROVEN verdict combines the three gates with the thresholds in config/review.yaml;
  it is this page's reading of the rules, not a stored verdict. Empty live tables say so.

## Checked
Playwright, pre-installed Chromium, 1280 and 390 px: no console errors, no horizontal scroll, no external requests.
