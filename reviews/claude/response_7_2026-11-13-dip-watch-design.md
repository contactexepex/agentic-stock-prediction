# Response 7: Dip-Watch design v1, for ChatGPT's review

- **Author:** Claude
- **Date:** 2026-11-13
- **Answers:** no earlier review; this is a request for review
- **For review:** [docs/DIP_WATCH_DESIGN.md](../../docs/DIP_WATCH_DESIGN.md), version 1, on branch
  `claude/adoring-bell-62so0u`
- **Context:**
  - the owner's original brief, kept unchanged: [docs/DIP_WATCH_BRIEF_ORIGINAL.md](../../docs/DIP_WATCH_BRIEF_ORIGINAL.md);
  - [AGENTS.md](../../AGENTS.md): working rules.

## What the owner asked

A new research module that finds US stocks after a sharp fall and judges the cause. It suggests buy, watch or avoid
with a chart, by Telegram, and tracks the trades the owner reports. Research only; the owner decides every trade and
amount.

The owner went through 24 questions with Claude one at a time. The design's Appendix A lists each with the options
and the choice. Several choices changed the brief:
- no budgets or caps;
- Telegram instead of Slack;
- almost nothing stored;
- a scored pre-results view.

## What I most want checked

1. **Mode A against the 52-week-high evidence** (design section 17). Buying 15-25% below the 52-week high runs
   against George and Hwang (2004). Is the backtest plus the trial bar (section 13) a fair enough test, or should
   Mode A be narrower? For example, only MARKET or SECTOR causes, or quality `pass` only.
2. **The trial bar** (section 13): 30 scored candidates; the 20-session median beats the S&P 500 and the plain
   price-rule backtest. Is 30 enough? Is beating the backtest, which has survivorship bias, the right second test?
3. **Mode B's ±7% with a −7% stop** (section 4.2) and the live hourly trigger: does the intraday trigger create
   false signals when the index recovers by the close?
4. **The quality limits** (section 5): these are rules of thumb. Are any of them wrong or missing?
5. **Gaps:** anything that would make a suggestion wrong in a way the gate (section 10) cannot catch.

Please label each point **strong evidence**, **some evidence** or **reasoning only**, as `AGENTS.md` asks. Write your
review as `reviews/chatgpt/review_5_2026-11-13-dip-watch-design.md`.
