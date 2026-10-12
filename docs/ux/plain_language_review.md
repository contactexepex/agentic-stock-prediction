# Plain-language review of the cockpit (UX1)

Status: **proposal, awaiting the owner's approval**. Nothing in the app has changed. Written 2026-10-12, on the first
day of live paper trading, from main at `194133c`.

Research only: the system never trades and nothing here is advice. Every change proposed below keeps the app
"research only, paper, never advice". Nothing proposed tells a reader to buy or sell.

## Why this review exists

On Day 1 the owner, who built the system, could not read the dashboard well enough to decide whether to rely on it:

> "When I am unable to read the dashboard to make a decision whether I can rely on the data, then how can another
> user, who is just a normal retail user like me, understand and make a decision whether to invest or not and why?
> Not even the home page is telling me that or giving me that information."

The pages are correct and careful. They are also written for the people who built them. The same four problems show
up on every page:

1. **The first screen never answers "can I rely on this yet?"** The answer exists (the signals band, the go-live
   bar, the weekly review's `model_skill`), but it is one grey sentence of jargon. The reader has to look for it.
2. **Internal references are shown to the reader.** Tooltips cite `decision 51`, `SPEC section 6`, `F1.10`, `WS4`,
   `Wave 5`, `DESIGN 3b`, `ranges.py` and `config/costs.yaml`. A grep of the page code for `decision NN`,
   `SPEC section`, `WS4`, `Wave 5` and `(F…` finds 85 matching lines that are not comment lines. The command is in
   Appendix B.
3. **Expected values look like results.** The reader sees "−₹1,160 · −1.16% · below market costs" and reads it as a
   loss that already happened.
4. **Empty states say "not yet" but never "when".** Almost every "No … yet" is silent about when it fills. The data
   to say when is usually already in the payload (an open trade's `exit_date`, the post-close run's `next_at`, the
   Saturday review date).

### How to read the references

Lines are on main at `194133c`. Each quoted text is an exact substring of that line (or line range); `…` marks a part left out, for example a
long template expression.

| Alias | File |
|---|---|
| `home` | `web/app/(cockpit)/[market]/_home/home-page.tsx` |
| `head` | `web/components/blocks/page-head.tsx` |
| `costs` | `web/components/blocks/costs.tsx` |
| `consts` | `web/lib/ui/constants.ts` |
| `watch` | `web/app/(cockpit)/[market]/watchlist/_parts/watchlist-page.tsx` |
| `news` | `web/app/(cockpit)/[market]/news/_parts/news-page.tsx` |
| `cos` | `web/app/(cockpit)/[market]/companies/_parts/companies-page.tsx` |
| `decision` | `web/app/(cockpit)/[market]/stocks/[ticker]/_parts/decision.tsx` |
| `trades` | `web/app/(cockpit)/[market]/stocks/[ticker]/_parts/trades.tsx` |
| `fh` | `web/app/(cockpit)/[market]/stocks/[ticker]/_parts/forecast-history.tsx` |
| `cards` | `web/app/(cockpit)/[market]/stocks/[ticker]/_parts/cards.tsx` |
| `strat` | `web/app/(cockpit)/[market]/stocks/[ticker]/strategies/_parts/strategies-page.tsx` |
| `life` | `web/app/(cockpit)/[market]/stocks/[ticker]/lifecycle/[date]/_parts/lifecycle-page.tsx` |
| `pp` | `web/app/(cockpit)/[market]/paper-portfolios/_parts/paper-portfolios-page.tsx` |
| `rva` | `web/app/(cockpit)/[market]/rule-vs-ai/_parts/rule-vs-ai-page.tsx` |
| `lab` | `web/app/(cockpit)/[market]/strategy-lab/_parts/strategy-lab-page.tsx` |
| `tr` | `web/app/(cockpit)/[market]/track-record/_parts/track-record-page.tsx` |
| `trlib` | `web/lib/strategy-pages/track-record.ts` |
| `help` | `web/app/(cockpit)/[market]/help/_parts/help-page.tsx` |
| `asst` | `web/app/(cockpit)/[market]/assistant/_parts/assistant-page.tsx` |

---

## 1. The questions a retail reader brings, in order

| # | The reader's question | Where it should be answered | Where it is answered today |
|---|---|---|---|
| 1 | **Can I trust this yet, and why or why not?** | The **top of Home**, as a verdict block with a yes/no in big words, the reasons as a checklist, and what is missing (section 3). The same short verdict sits on every page as the band under the title. | Only in the signals band (`head:95-96`): "No proven strong signals today" plus a long sentence. The checklist lives in Strategy lab's detail card ("Against the go-live bar (your cost)", `lab:378`) and on Help. Track record's skill band (`tr:80-91`) is a third answer. |
| 2 | **What happened today?** | Home, second block: "Today in 3 lines" (market mood, what the paper trades did, the one story that mattered). | Spread over seven Home cards: agreement, head-to-head, Rule vs AI, alerts, news, runs, open trades. There is no summary line. The end-of-day analyst's `eod.summary` is the closest, and it is buried in the Rule vs AI card (`home:312`). |
| 3 | **What did the paper trades do, wins and losses?** | Home's third block: "Paper trades so far", meaning settled, won, lost, and net after costs. It links to **one** trades page, Paper portfolios (being reworked by B4/B13/B16, "all paper trades in one place"). | The cumulative chart (`home:276`), "Last close" (`home:292`), "Head-to-head to date" (`home:318`), the Rule vs AI scorecard and Strategy lab all show parts. None says "N settled: W won, L lost". |
| 4 | **What should I look at for one company?** | The company page's first card, rewritten as "What the strategies think, and how sure they are" (section 2.5), followed by the price chart. | "{name} at a glance" (`decision.tsx`) opens with horizon tabs, N+k, head-to-head and cost labels before the chart. |
| 5 | **What would have to happen before a signal is "proven"?** | The verdict block's checklist (section 3) with dates ("earliest possible: mid-December 2026"), plus a Help section "Why the app does not tell you when to buy or sell". | Help lists the five checks (`help:69-73`) and says "no page ever tells you to buy or sell" (`help:87`). It never says **why**, or when the bar could be met at the earliest. |

**Why the app never says "buy" or "sell" (proposed wording for the verdict block and Help).** The owner asked which
page tells them when to buy or sell. The honest answer, in plain words:

> **This app does not tell you when to buy or sell, and right now it cannot.** Every strategy here is being tested on
> paper. Nothing has yet shown that it beats simply holding the market after costs, over enough trades and long
> enough to rule out luck. Until a strategy passes that test (the "go-live bar" below), any "buy" here would be a
> guess dressed up as a signal. Even after a strategy passes, the app will show what the tested strategy would do
> and how well it has done, not instructions for your money. This is a personal research project, not investment
> advice.

---

## 2. Page by page

Each table row gives a label that confuses a newcomer, where it is, and a rewrite in plain words. "Tooltip" means the
text appears on hover or tap, "inline" means it is printed on the page.

### 2.0 Shared parts (every page)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `head:95`, `consts:29` | `No proven strong signals today` | **"Not proven yet: these are tests, not tips."** |
| `head:89` | `None of the ${strategies ?? "registered"} strategies has met the go-live bar (${goLive.trades_needed} more settled trades needed, ${goLive.months_forward} of ${GO_LIVE_MONTHS} months forward so far, and beating the best baseline after costs).` | "No strategy has passed the test yet. The main rule strategy has finished {300 − needed} of about 300 test trades and {months} of 2 months, and has not yet beaten simply buying and holding after costs." **This also fixes a wrong impression.** The numbers come from `go_live`, which is the *reference strategy's* (`rule.model_news.v1`) position only (`scripts/marketbrief/warehouse/rm_common.py:215-232`). The sentence reads as if they were true of all strategies. Either name the strategy, or add a data field for the strategy nearest the bar (section 6, D2). |
| `consts:31` | `Paper only — no proven edge yet` | Keep it, and make it tappable: "Paper = a record of what would have happened. No real money moves." |
| `head:34` with `consts:84` | `Regime` chip; tooltip `Market mood stored by the daily run: CALM / TRENDING / EVENT_HEAVY / UNSTABLE.` | Chip: **"Market mood: calm"**, in words, not codes ("calm", "trending", "busy with events", "jumpy"). Tooltip: "How the whole market has behaved lately. Some strategies sit out the busy and jumpy days." |
| `head:46-47` | the freshness chip, its state word (e.g. "fresh") then `` · built ${fmtLocal(fr.built_at, m, lt)}`` | "Updated 08:41 (data up to yesterday's close)". The word "fresh" is the system's word, not the reader's. |
| `head:109` | footer `as_of … · cutoff … · built_at …` and the API path | Hide behind a "Technical details" toggle. The API path means nothing to a reader. |
| every page | Tooltips citing `decision 30`, `decision 51`, `SPEC section 6`, `F1.10`, `F10`, `WS4`, `Wave 5`, `DESIGN 3b`, `ranges.py`, `config/costs.yaml` | **Remove all of them from visible text.** If traceability matters, keep the reference in a code comment or a `data-ref` attribute, never in the reader's sentence. This is the biggest single wording win (section 6, W1). |
| `costs:20`, `rva:124` | `${signed(pick.expected_gain_pct)} · ${clears ? "clears market costs" : "below market costs"}` (the owner's "−₹1,160 · −1.16% · below market costs") | **"Expected: −₹1,160 (−1.16%) · costs are bigger than the likely gain."** Prefix every expected value with "Expected" (or "if the odds hold"), and never style it like a realised loss. Tooltip: "Not a loss. Nothing has happened yet. This is the average result we would expect from this trade, given its chance of going up, how far it might move, and the costs of buying and selling." |
| `costs:28` | `viable at your cost` / `not viable at your cost` | **"Worth it after your broker's fees"** / **"Not worth it after your broker's fees"**. Tooltip: "Your broker charges more than the basic market fees (for example, currency markup and reporting charges). After those, the expected gain is {x}." |

### 2.1 Home (`home`; owner B14, read model B11)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `home:475` | subtitle `the session being predicted` | "Monday 12 Oct: what the strategies expect for today's trading". |
| `home:75` | KPI `Most agreed at N+${horizon}` | **"Most strategies like: {ticker}"**, with the sub-line "{n} of {m} would buy for a 1-day hold". |
| `home:78` | tooltip `The company most strategies would buy at the selected horizon (decision 30).` | "The company the largest number of test strategies would buy for this holding period. Agreement is not proof: they can all be wrong together." |
| `home:79` | KPI `Head-to-head today` | **"Today's test trades: rule vs AI"**. |
| `home:87` | tooltip `Up to four paper trades per company: strongest rule strategy and strongest AI trader × two pick rules. …(decision 51).` | "For each company, the best rule-based strategy and the best AI each make up to two paper trades, so we can compare them fairly on the same days." |
| `home:88-90` | KPI `Open paper trades` / `unrealised … before costs` | "Paper trades running now", with sub "{±amount} so far, before fees". (The Day-1 "0 open" count is being fixed by B4/B13/B16.) |
| `home:105` | card title `Who agrees at N+${horizon}` | **"Which companies most strategies would buy"**, with the horizon tabs as "Hold 1 day · 2 · 3 · 4 · 5 days". |
| `home:106` | help `Decision 30: companies ranked by how many strategies would buy them…` | Drop "Decision 30:". The rest of the sentence is good. |
| `home:109` | `N+${horizon} = …the close of the ${ORDINAL[horizon]…} session after the open` | "Buy at today's open, sell at the close {k} trading days later." Say this once, inline, above the tabs. |
| `home:140` | `buyers N+1 … N+5` | "Buyers for 1 to 5-day holds". |
| `home:144` | `avg. chance of a rise` | Keep. Add "(50% = coin flip)" inline, not only in the tooltip at `home:143`. |
| `home:162-165` | card `Today’s head-to-head paper trades`; help with `p × move − (1 − p) × loss − costs` and `decisions 41-42` | Title: **"Today's test trades: rule vs AI"**. Help: "Each side picks the holding period it thinks is best, in two ways: the best expected gain and the highest chance of rising. Each pick is a paper trade of {amount}. The formula is on the Help page." |
| `home:175` | `(expected gain after costs above zero; your cost = decision 51)` | "(worth it = the expected gain is bigger than all fees)". |
| `home:234` | `to target ${…} · downside ${…} · costs ${…}%` | "If right: +{x}% · if wrong: −{y}% · fees {z}%". |
| `home:276` | `No settled paper trade yet` | See section 4: "First results after Tuesday's close ({date}, {time})". |
| `home:296` | `No end-of-day analysis stored yet.` | "The end-of-day write-up appears after the first trades close ({next_at})". |
| `home:318-319` | `Head-to-head to date`; tooltip `Fewer than 20 trades: too few to rank (SPEC section 6).` | **"Rule vs AI so far"**. Tooltip: "Under 20 finished trades the numbers are mostly luck, so no winner is named yet." |
| `home:323` | `Gain pick` / `Probability pick` | "Picked for biggest expected gain" / "Picked for highest chance". |
| `home:328` | `no settled trade yet` | "{n} running, first finish {date}". |
| `home:334` | badge `too few to rank` | **"too early to tell ({n} of 20)"**. |
| `home:356` | `No intraday check stored yet today. Checks run … per session; the first one fills this card.` | Good. Add the time: "First check around {time}". |
| `home:388` | help `…the engine’s market-moving flag first (high materiality and market-wide or a results item)…` | "The stories most likely to move prices: big company news, results, and market-wide news (rates, inflation, oil)". |
| `home:400` | `not verified per company` | "market-wide news" (verification is a per-company idea; for market news, say nothing). |
| `home:403` | `${…} materiality` | "importance: high / medium / low". |
| `home:435` | the runs help (31 runs a week, the full schedule) | "Did today's automatic steps run? A tick = finished and checked." Move the schedule to Help. |
| `home:458-463` | Legend (sample values) | Keep. Add a line: "Expected = what the odds suggest, not what happened". |

**Layout.** The order is: agreement → head-to-head → Rule vs AI → alerts → news → runs → open trades. That answers the
builders' questions (who agrees, which picks compete) before the reader's (can I trust it, what happened). Section 3
proposes the new top. The rest can stay below it.

### 2.2 Watchlist (`watch`; owner B14, read model B11)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `watch:68` | `…never predicted (decision 13); they live on the Companies page.` | Drop "(decision 13)". |
| `watch:69` | `Most agreed at N+${horizon}` | As on Home: "Most strategies like". |
| `watch:107` | `…Range = the published range for the horizon (ranges.py; …), shown whether or not a strategy is live.` | "Range = where the price is likely to end: the inner band about half the time, the outer band about 8 times in 10." Drop "ranges.py" and "live". |
| `watch:118` | column `Agreement at N+${horizon}` | "Would buy ({k}-day hold)". |
| `watch:120` | column `Buyers N+1…5` | "Buyers, 1 to 5-day holds". |
| `watch:121` | column `Range at N+${horizon}` | "Likely price range ({k} days)". |
| `watch:122`, `watch:146` | column `Open` and link `Open` | The same word means "open paper trades" in the header and "open the page" in the row. Rename the column **"Trades running"**. |
| `watch:203` | `N+k: buy at the open … (decision 39).` | Keep the sentence and drop "(decision 39)". |

### 2.3 News (`news`; owner B14, read model B11)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `news:65` | `Market-wide stories carry no verification status: verification is per company (DESIGN 3b).` | Drop "(DESIGN 3b)". |
| `news:67` | `The engine’s market-moving flag: high materiality and market-wide or a results item.` | "Likely to move prices: an important market-wide story or a results announcement." |
| `news:140` | chip `Can carry a call` | **"Checked news only"**. Tooltip: "Confirmed by an official filing or reported independently by two or more outlets. Only these can be the main reason for a prediction." |
| `news:152` | `…(the analyst’s summaries were templated)…` | "Some stories have no summary yet; the headline links to the article." |
| `news:202` | help `…raises the regime to EVENT_HEAVY…` | "A big scheduled event (like a central-bank decision) makes the ranges wider, because prices can jump." |
| `news:216` | `Major: widens every range of this market whose window contains it (F2, major_event_factor).` | "Big event: the expected price ranges are widened around it." |
| `news:221` | the raw event type with `_` replaced by spaces | Map each type to words ("results", "ex-dividend", "options expiry"). |

### 2.4 Companies (`cos`; owner B14, read model B11)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `cos:266` | subtitle `the watchlist as data: …` | "The companies this app follows, and their history". |
| `cos:268` | `Active companies are collected, predicted and traded on paper (F8.2).` | Drop "(F8.2)". |
| `cos:271` | `Requests from any channel are appended to the inbox and imported by the next run (F10)…` | "Your change is saved and takes effect at the next morning run." |
| `cos:175` | `Appended to the inbox with your sign-in and an idempotency key; the next run imports it (F10).` | "Saved. It takes effect at the next morning run ({time}). Sending it twice is safe." |
| `cos:218` | `The watchlist is data (F8): every add, … is an append-only event` | "Every change to the list is kept, with who asked and when." |
| `cos:190` | the raw refusal code with `_` replaced by spaces | Map codes to sentences ("This company is already on the list"). |

### 2.5 Company page (`decision`, `trades`, `fh`, `cards`; owner B15, read model B12)

**Layout.** The page opens with horizon tabs, "N+k", "head-to-head" and cost labels before the reader sees the price
chart. Proposed order:

1. One plain sentence: "{n} of {m} strategies would buy {name} for a {k}-day hold. Their average chance of a rise is
   {p}%. Not proven: see how often they've been right." The link goes to this company's settled trades.
2. The price chart with the likely range.
3. "What our paper trades on {name} did": settled, won, lost.
4. Everything else.

| Where | Today it says | Plain rewrite |
|---|---|---|
| `decision:96` | help `…It helps you judge the company; it never tells you to buy or sell.…` | Good. Keep it, and show it inline once rather than only on hover. |
| `decision:99` | `N+k: … Opens on N+1 (decision 39).` | Drop "(decision 39)". |
| `decision:140` | `The published range for this horizon, computed by ranges.py: …` | "Where the price is likely to close after {k} days: the target is the middle guess; the inner band catches the close about half the time, the outer band about 8 times in 10." |
| `decision:164` | `…“clears costs” when it is above zero (decisions 41-42, 51).` | Drop the decision numbers. |
| `fh:26` | `Regime {r.regime ?? "not stored"} · calibration {r.calibration_id` | Show the calibration id only under "Technical details". |
| `fh:37` | `P(up) … pts ${g}` | "Chance of a rise {p}%. What pushed it up or down: {group in words} +{x} points…" |
| `trades:100` | `…(${…} × beta ${…})…` | "The market moved {x}%, and this stock usually moves {beta}× the market, so the market explains {y}%." |
| `trades:108` | `…Net = profit after the market-cost charges of config/costs.yaml. … (F1.10, decision 43)…` | "Net = profit after brokerage, taxes and fees. 'Why' splits the move into: the whole market, the sector, verified news, and the company itself." |
| `cards:24` | `…(F6.1)…` | Drop it. |
| `cards:124` | the results help, which cites `WS6` | Drop "WS6". |
| `trades:132` | `No settled paper trade yet.` | "No finished paper trade yet. The first ones finish on {earliest exit_date}." |

**Stock strategies (`strat`).**

| Where | Today it says | Plain rewrite |
|---|---|---|
| `strat:53` | `…Under ${MIN_TRADES_TO_RANK} trades it is mostly noise (SPEC section 6).` | Drop "(SPEC section 6)". |
| `strat:56` | `…as the luck guard of SPEC section 6.` | "Shown so a lucky streak on one company is not mistaken for skill." |
| `strat:300` | `A down call: scored as a prediction, never traded (decision 3).` | "Predicted down: we score it, but paper trades only buy, never short." |
| `strat:266` | `differs from the reference in ${…}` | "Same as the main rule strategy except: {setting in words}". |

**Lifecycle (`life`).** This page is the clearest "what became of each call" story in the app. It mostly needs
decision numbers removed (`life:95`) and "not settled yet" (`life:44`) to name the exit date from the row's own
`exit_date`.

### 2.6 Paper portfolios (`pp`; owner B16, read model B13)

The page itself is being reworked into "all paper trades in one place" by B4/B13/B16. That rework also covers the
Day-1 "0 open" count. Wording only:

| Where | Today it says | Plain rewrite |
|---|---|---|
| `pp:56` | `…the go-live bar uses it (decision 50). Open trades are before costs.` | "Market fees: brokerage and taxes. Your fees: also your own broker's extra charges. The test that decides whether a strategy is proven uses your fees." |
| `pp:85` | `Your manual paper trades (WS4), …` | Drop "(WS4)". |
| `pp:88` | `…appended to the inbox with your sign-in and an idempotency key; the next run imports it (F10)…` | "Saved. It shows here after the next run ({time})." |
| `pp:110` | `…a handful of trades is mostly luck (SPEC section 6).` | Drop "(SPEC section 6)". |
| `pp:179` | badge `H2H` | "Rule vs AI". |
| `pp:336` | `…the import checks it (WS4)…` | Drop "(WS4)". |

### 2.7 Rule vs AI (`rva`; owner B16, read model B13)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `rva:45` | subtitle `head-to-head paper trades on identical company-days` | "Rule-based strategies vs AI traders, on the same companies and the same days". |
| `rva:48` | `…the go-live bar uses it (decision 50)…` | As at `pp:56`. |
| `rva:98` | help `The head-to-head view (F1, decisions 41-42): …` | "Every day, the best rule strategy and the best AI each pick trades on the same companies, so the comparison is fair. The luck test says whether a lead could just be chance." |
| `rva:109` | `No verdict yet` | **"Too early to call: {n} trades finished, 20 needed per side"**. Before any trade has settled: "First trades finish at Tuesday's close ({date})". |
| `rva:113` | `A lead on a handful of trades is mostly luck (SPEC section 6): the luck bar must clear zero after correction…` | "A lead on a few trades is mostly luck. We only call a winner when the luck test clears zero." |
| `rva:81`, `rva:204`, `rva:306` | `Nothing settled yet in the head-to-head view.` / `No settled head-to-head trade yet.` | See section 4. |
| `rva:124` | `below market costs` | See the shared row in 2.0: "Expected … costs are bigger than the likely gain". **This is the owner's Day-1 confusion.** |
| `rva:258` | `…by the market regime at prediction time (F2.6).` | "…and by the market's mood on the day of the prediction". |
| `rva:321` | `…the EOD analyst (Sonnet, F6.1)…` | "After each close an AI writes a short, checked explanation of what happened. It explains, it never predicts." |
| `rva:369` | `…the research director (Opus, F6.2)…proposals as config diffs…` | "Every Saturday an AI reviews the week and suggests changes. Nothing changes until the owner approves." |
| `rva:378` | the weekly-review empty state with the due date | Good: it already says when. Keep it. |
| `rva:443` | Legend `edge` / `luck?` / `loss` | Good words. Add "(after correcting for comparing many strategies)" only in the tooltip. |

### 2.8 Strategy lab (`lab`; owner B16, read model B13)

| Where | Today it says | Plain rewrite |
|---|---|---|
| `lab:96` | help `Accuracy: … Head-to-head: … (F1, decisions 41-42).` | "All trades: every prediction a strategy made becomes a paper trade. Rule vs AI: only the daily picks of the two best." |
| `lab:99` | `Forward` / `Back-test` | **"Since 12 Oct (real time)"** / **"Replayed on past years"**. Help: "Replayed results say what *would* have happened; real-time results say what *did*. They are never mixed." |
| `lab:102` | `…Market cost: brokerage, taxes and fees of config/costs.yaml…(decision 50)…` | Drop "config/costs.yaml" and "(decision 50)". |
| `lab:118` | `…With few trades the lead is mostly luck (SPEC section 6).` | Drop "(SPEC section 6)". |
| `lab:120-121` | KPI `Best yardstick (baseline)`; tooltip `The best of the three baselines (always buy, follow yesterday, model without news). …(F7.2).` | **"Simple benchmark to beat"**. Tooltip: "A deliberately simple strategy, for example 'always buy'. If a clever strategy can't beat it after fees, it isn't adding anything." |
| `lab:126-127` | `Nearest to go-live (baselines aside)`; tooltip `The go-live bar (F7.2, your cost): about ${GO_LIVE_TRADES_ABOUT} settled trades, …` | **"Closest to being proven"**. |
| `lab:171` | `No back-test rows stored yet. …(F2.3).` | "No replay on past years yet. The weekly review on Saturday writes one." |
| `lab:328` | `live` tag, and tooltip `Not live yet: paper trading of this strategy is switched on in Wave 5; …` | **"Paper testing since {live_from}"** / **"Not tested yet"**. The word "live" reads as "real money", which is exactly the wrong impression. "Wave 5" is a build-plan word. Every strategy in `config/strategies.yaml` has `live_from: 2026-10-12`. |
| `lab:334` | `bar ${pct(s.threshold)}` | "buys when the chance of a rise is at least {x}%". |
| `lab:378-390` | `Against the go-live bar (your cost)` checklist | **The best explanation of "proven" in the app.** Promote it to Home (section 3) and keep it here. |
| `lab:413`, `lab:545` | `No settled trade in this view yet.` / `No settled trade in this view and basis yet.` | See section 4. |

### 2.9 Track record (`tr`, `trlib`; owner B16, read model B13)

The owner's Day-1 question was what "paper long", the baselines and the sessions are, and whether the strategies were
invented. Two things a newcomer cannot know:

- **This page scores a different thing from the Strategy lab.** It scores the *forecaster's daily calls* and the
  *signal model's back-test*, not the strategies' paper trades. The subtitle says so (`tr:51`, "the forecaster’s
  calls scored per basis") but uses words the reader doesn't have. Add one inline sentence at the top: "This page
  checks two things: (1) how often the daily AI forecast was right, and (2) whether the statistical model had any real
  skill when replayed on past years. The paper trades' results are on Strategy lab and Rule vs AI."
- **The baselines are standard, not invented.** "Always up", "Momentum (5 days)", "RSI mean reversion" and
  "Benchmark long, per date" (`trlib:6-11`) are textbook yardsticks used in research to check whether a model adds
  anything. Say so.

| Where | Today it says | Plain rewrite |
|---|---|---|
| `tr:99` | KPI `Signal model` / `No proven skill` | Keep. Add a sub-line: "replayed on past years, it did not beat simple benchmarks". This is the review's verdict, and `track.skill.why` already carries a sentence. |
| `tr:104` | `Against always-up` | **"vs. 'it always goes up'"**. Inline: "Stocks rise more often than they fall, so a forecast must beat simply always saying 'up'." |
| `tr:108-111` | KPI `Brier score`, `skill … vs the base rate · log loss …` | Title **"Honesty of the stated chances"**, with a meter from "coin flip (0.25)" to "perfect (0)". Show Brier as the number in small print only. Move log loss to "Technical details". |
| `tr:123-124` | `Calls by scoring basis` and the help on close→close / open→close and `legacy` | **"How often the daily forecast was right"**. Inline: "Older calls were scored from close to close, newer ones from the open to the close, so they are kept apart." |
| `tr:66` | Legend `Wilson 95% interval` | "the range the true hit rate is very likely in; it is wide when there are few calls". Never use the name "Wilson" in visible text. |
| `tr:177` | Calibration help | Good plain words. Rename the card **"When it said 70%, was it right 70% of the time?"** |
| `tr:242` | `Ranges held` | **"Did the price land in the predicted range?"** |
| `tr:304-305` | `Signal model back-test`; help `walk-forward test…` | **"Replay on past years (not real trades)"**. Help: "Each month the model was trained only on earlier data and then tested on the next month, as if in real time." |
| `tr:329` | column `AUC`; tooltip `Area under the curve: 0.5 is no ranking ability…` | **"Picks risers better than chance?"** Show it as a meter centred on 0.5 (coin flip), with the word "no" / "slightly" / "yes". Keep "AUC" in small print. |
| `tr:349` | `Paper long against the baselines` | **"If you had bought whenever the model said 'likely up', vs simple benchmarks"**. |
| `tr:354` | columns `Bar`, `Positions`, `Days` | "Buy when chance ≥", "Times it would have bought", "Days tested". |
| `tr:355` | `The model’s paper long minus the baseline: the return over the whole window (1 or 5 sessions)…` | "Extra return per trade compared with the benchmark, for 1-day and 5-day holds. Positive = the model did better." |
| `tr:361` | `the model’s paper long (buy when the chance clears the bar) against each baseline` | Same as `tr:349`. Define "paper long" once in the glossary: "a pretend purchase, held for the stated days". |
| `tr:392` | `No rule-only replay stored by the cut-off.` | "No replay yet: it runs on request." |

### 2.10 Assistant (`asst`; owner B8)

This page is already the plainest in the app. Its subtitle (`asst:100`) says "never advice" and its rules list says
"A question about real money is declined". Two changes:

- Add a starter question that matches the owner's real question: **"Can I rely on these signals yet?"** The
  assistant's answer should come from the same go-live and skill fields as the Home verdict.
- Where a decline replaces an advice-like answer, link to the Help section "Why the app does not tell you when to
  buy or sell".

### 2.11 Help (`help`; owner B7)

Help is the right place for the formulas, and its plain-word sections are good. Gaps:

| Where | Today it says | Change |
|---|---|---|
| `help:87` | `no page ever tells you to buy or sell` | Add the **why** (the paragraph at the end of section 1) as its own section near the top, "Why the app does not tell you when to buy or sell". |
| `help:90` | `(measured on your own costs, decision 50)` | Drop "decision 50". |
| `help:311` | `accuracy over time, calibration, scoring bases apart` | Brier, AUC, the Wilson interval, "paper long", "back-test" and "walk-forward" are **not explained anywhere in Help** (a baseline is, in its glossary). Add them to the glossary (section 5). |
| — | — | Add "When will this page fill?" (section 4 as a table), so a reader on Day 1 knows what to expect over the first weeks. |

---

## 3. A new top for Home: "Can I rely on this yet?"

Built **only from data the Home payload already carries**, unless a line is marked *new field*.

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  Can I rely on this yet?   NOT YET                                         [Why? ▸]  │
│  Everything here is a test on paper. No real money moves, and nothing here           │
│  tells you to buy or sell.                                                           │
│                                                                                      │
│  What has to happen before any strategy counts as "proven":                          │
│   ✗  Enough finished trades       0 of about 300   (main rule strategy)              │
│   ✗  Long enough                  0 of 2 months    (earliest: mid-December 2026)     │
│   ?  Beats "always buy" after     not measurable yet                                 │
│      your fees, beyond luck                                                          │
│   ?  Losses stay within the limit not measured yet                    (new field D1) │
│   ?  Works in calm and jumpy      not enough data yet                 (new field D1) │
│      markets                                                                         │
│   ✗  The model shows real skill   No: replayed on past years, it did not beat        │
│      (weekly review)              simple benchmarks.  → Track record                 │
│                                                                                      │
│  Paper trades so far:  0 finished · 223 running · first results Tue 13 Oct, after    │
│                        the close (about 16:30 IST)                                   │
└──────────────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  Today in 3 lines                                                                    │
│  1. Market mood: calm. Most stocks you follow are up/down (n up, m down).            │
│  2. 223 paper trades opened at 09:15; the 1-day ones finish at Tuesday's close.      │
│  3. The story that mattered: "<top mover headline>" (confirmed)                      │
│                                                           [See all paper trades ▸]   │
└──────────────────────────────────────────────────────────────────────────────────────┘
   … then today's cards as now (who would buy, rule vs AI picks, alerts, news, runs)
```

The numbers in the wireframe are placeholders shaped like Day 1, not computed values.

**Where each line comes from**

| Line | Source in the Home payload | Today? |
|---|---|---|
| Verdict "NOT YET" / "A strategy is proven" | `go_live.proven` (`web/lib/ui/types.ts:98-103`). It is false until the reference strategy meets the bar. | exists |
| Enough finished trades | `go_live.trades_needed` (300 − settled, `scripts/marketbrief/lab/constants.py:31`) | exists, but only for the reference strategy `rule.model_news.v1` (`scripts/marketbrief/constants/warehouse.py:39`). Name it, or add D2. |
| Long enough | `go_live.months_forward` of `GO_LIVE_MONTHS` = 2 (`consts:9`). Earliest date = `live_from` (2026-10-12 in `config/strategies.yaml`) + 2 months. | exists; the date is computable |
| Beats always-buy beyond luck | `go_live.beats_best_baseline` (null = not measurable yet) | exists |
| Drawdown and regimes | `drawdown_within_limit` and `holds_in_calm_and_volatile` exist on Strategy lab's scoreboard rows (`scripts/marketbrief/warehouse/rm_strategies.py:69-79`), not in Home's 4-field `go_live` | **new field D1**: add both to Home's `go_live` |
| Model skill | `status.paper_label` (from the weekly review's `model_skill`, `rm_common.py:156`) on every page; the reason sentence is in Track record's `track.skill.why` | Home needs `skill.state` and `skill.why`: **new field D3** (or reuse `paper_label` only) |
| Paper trades so far: finished / won / lost | `settled_trades` (each with `net_pnl`): count, `net_pnl > 0` = won, `< 0` = lost | exists |
| Running | `open_trades.length` (being fixed by B4/B13/B16) | exists |
| First results | min `open_trades[].exit_date`, and `status.runs.post_close.next_at` | exists |
| Today line 1 (mood, ups and downs) | `status.regime`; `companies[].change_pct` (count > 0, < 0) | exists. A benchmark move would need **new field D4**. |
| Today line 2 | `open_trades` by `entry_date` = today; `status.runs.pre_open.at` | exists |
| Today line 3 | `news` via the existing `movers()` (first item) and its `status` | exists |
| Link to the trades | `pagePath(market, "portfolios")` (already used at `home:491`) | exists |

When `go_live.proven` becomes true, the block turns to "One strategy has passed the test: {name}". It also says
"Even now, this shows what a tested strategy would do on paper. It is not advice." It still never says "buy".

---

## 4. Empty states: say when they will fill

A rule for every page: **every "No … yet" names the event that fills it, and the date or time when the payload knows
it.** The facts are already stored: open trades carry `exit_date` (`web/lib/ui/types.ts:178`), runs carry
`post_close.next_at`, the weekly review is due on Saturday (`rva:378` already says so), and the go-live clock starts
at `live_from`.

| Where | Today | Proposed |
|---|---|---|
| `home:276`, `rva:204`, `rva:306`, `lab:413` | `No settled paper trade yet` / `No settled head-to-head trade yet.` / `No settled trade in this view yet.` | "No paper trade has finished yet. The first ones (1-day holds) finish at the close on **{min exit_date}**; results appear after the evening run (**{post_close.next_at}**)." |
| `home:328`, `rva:81` | `no settled trade yet` / `Nothing settled yet in the head-to-head view.` | "{n} running · first finishes {date}". |
| `home:334`, `pp:110`, `rva:83` | `too few to rank` | "too early to tell: {n} of 20 finished trades". |
| `home:296`, `rva:322` | `No end-of-day analysis stored yet.` / `No end-of-day analysis stored by the cut-off.` | "The evening write-up appears after the first trades finish ({date})." |
| `home:356` | `No intraday check stored yet today…` | Add "First check around {time}". This needs the next intraday time: **new field D5** (`status.runs.intraday[].next_at`). |
| `lab:171` | `No back-test rows stored yet. …` | "No replay on past years yet. It is written by the weekly review (next: Saturday {date})." |
| `lab:545` | `No settled trade in this view and basis yet.` | As at `home:276`. |
| `lab:390` | `No forward accuracy row yet, so no position against the bar.` | "This strategy has no finished paper trade yet: its 2-month test started on {live_from}." |
| `tr:128` | `No direction call has been scored yet.` | "No daily forecast has been checked yet. A 1-day forecast is checked after the next trading day's close." |
| `tr:243` | `No range is scored yet: the first published range settles at its exit session.…` | Add the date: "…on {first exit date}". |
| `trades:132` | `No settled paper trade yet.` | "None finished yet; the first on {name} finishes on {min exit_date}." |
| `life:44` | `not settled yet` | "finishes {exit_date}". The row already has it (`life:56`). |
| `cards:50` | `No analyst note on this company yet: notes are written for settled head-to-head trades…` | Add the date of this company's first head-to-head exit. |
| `fh:86` | `…it arrives with the next page build.` | Name the time of the next morning run. |
| `cos:182` | `No company command recorded for this market yet.` | Fine as it is: this one is caused by the user. |

---

## 5. A short glossary, and tooltip vs inline

**Rule of thumb.** Put a meaning **inline** when the reader needs it to read the number at all (what N+k is, that
"expected" is not "happened", that 50% is a coin flip). Use a **tooltip** for how a number is computed (the formula,
the correction for many comparisons). Use **Help** for the full method. On phones, tooltips are tap-only and easily
missed, so nothing a reader needs for a decision may live only in a tooltip.

| Term in the app | Plain meaning | Inline or tooltip |
|---|---|---|
| Paper / paper trade | A pretend trade, recorded to measure a strategy. No money moves. | Inline once per page (the tag), tooltip on the tag |
| N+k (horizon) | Buy at today's open, sell at the close k trading days later. Show "N+3" as "3-day hold". | **Inline** |
| D / session being predicted | The trading day the forecast is for (today, before the open). | Inline ("today's trading") |
| Go-live bar / proven | The test a strategy must pass before it counts as proven: about 300 finished trades, 2 months, beating simple benchmarks after your fees beyond luck, losses within a limit, working in calm and jumpy markets. | **Inline on Home** (section 3) |
| Baseline / yardstick | A deliberately simple strategy (always buy, follow yesterday, model without news) that a clever one must beat. | Inline label "benchmark", tooltip for which one |
| Rule strategy / AI trader | A strategy that follows fixed rules / an AI that reads the data and decides. | Tooltip |
| Head-to-head (H2H) | The daily comparison: the best rule strategy vs the best AI on the same companies. Label it "Rule vs AI". | Inline label |
| Pick rule | How each side picks its holding period: biggest expected gain, or highest chance. | Tooltip |
| Expected gain | Average result if the stated chances are right: chance × gain − (1 − chance) × loss − fees. **Not a result.** | **Inline word "Expected"**, formula in tooltip |
| Market cost / your cost | Brokerage, taxes, exchange fees / plus your own broker's extra charges (FX markup, reporting, DP, portfolio fee). | Inline "after fees" / "after your fees", tooltip for the list |
| Cost-viable / clears costs | The expected gain is bigger than the fees. | Inline "worth it after fees" |
| Range (50% / 80%), band | Where the closing price is likely to land: about half the time inside the inner band, about 8 in 10 inside the outer. | Inline on first use, tooltip after |
| Target | The middle guess for the closing price. | Inline |
| Band position, target_z | How far the price sits from the target, in "usual moves". Not shown on the pages today; keep it that way. | — |
| Flagged / alert | A running paper trade is outside its range, far from target, or moving against the prediction. Monitoring only. | Inline |
| Regime | The market's mood: calm, trending, busy with events, jumpy. | Inline in words |
| Materiality | How important a news story is: high, medium or low. | Inline "importance" |
| Confirmed / corroborated / single source / rumour | Checked against an official filing / reported by 2+ independent outlets / only one outlet / unnamed sources. | Inline badge, tooltip for the rule |
| Win rate | Share of finished trades that made money after fees. | Inline |
| Luck test (edge / luck? / loss) | Could this result be chance? "edge" = probably not luck, "luck?" = could be, "loss" = loses after fees, and that's not luck. | Inline word, tooltip for the interval |
| Too few to rank | Under 20 finished trades: too early to tell. | **Inline** "too early to tell (n of 20)" |
| Drawdown | The biggest fall from a high point. | Tooltip |
| Brier score | How honest the stated chances were: 0 = perfect, 0.25 = coin flip. | Inline meter, number in small print |
| AUC | Whether the model ranks risers above fallers better than chance (0.5 = no better). | Inline meter, number in small print |
| Wilson 95% interval | The range the true hit rate is very likely in; wide when there are few calls. | Tooltip only, never the name "Wilson" inline |
| Calibration | When it says 70%, is it right about 70% of the time? | Inline as the card title |
| Back-test / walk-forward | A replay on past years, trained only on earlier data each time. Says what would have happened, not what did. | Inline label "replay on past years" |
| Forward | Real-time paper trading since 12 Oct 2026. | Inline "since 12 Oct" |
| Paper long | A pretend purchase held for the stated days. | Tooltip; rename the section instead |
| Model score / P(up) | The statistical model's chance that the price rises. | Inline "chance of a rise" |
| Settled | Finished: the paper trade has been sold. | Inline "finished" |
| Cut-off / as of | Nothing stored after this time is used on the page. | Technical details only |

---

## 6. Prioritised changes

Owners come from each file's git history (`git log -- <path>`), and agree with the `owner` field in
`web/lib/ui/routes.ts:23-34`. Sizes: **S** = under an hour, **M** = half a day, **L** = a day or more.

### Quick wording fixes (no layout, no data)

| # | Change | Files | Owner | Size |
|---|---|---|---|---|
| W1 | Remove every internal reference from visible text (`decision NN`, `SPEC section N`, `F…`, `WS4`, `WS6`, `Wave 5`, `DESIGN 3b`, `ranges.py`, `config/costs.yaml`, `Sonnet`/`Opus` in helps) | all pages; `costs.tsx`; `help` | B14 (home, watch, news, cos), B15 (stocks), B16 (pp, rva, lab, tr), B7 (costs, help) | M in total, S per page |
| W2 | "Expected" in front of every expected gain; "costs are bigger than the likely gain" instead of "below market costs"; "worth it after your fees" instead of "viable at your cost" | `costs:18-28`, `rva:122-129`, `home:230-234`, `strat:177` | B7 (shared label), B16 (rva copy), B14, B15 | S |
| W3 | "Live" → "Paper testing since {date}"; drop "Wave 5" | `lab:328` | B16 | S |
| W4 | Horizon words: "N+3" → "3-day hold" in labels and tabs (keep N+k in tooltips) | `consts`, `HorizonTabs`, `home`, `watch`, `decision`, `strat`, `rva` | B7 (shared), then the page owners | M |
| W5 | Track record wording: "paper long", the baselines are standard yardsticks, Brier/AUC in words, "this page scores the forecaster, not the paper trades" | `tr`, `trlib` | B16 | M |
| W6 | Regime and materiality in words on chips and news | `head:34`, `consts:84`, `news`, `home:403` | B7, B14 | S |
| W7 | The signals band names whose numbers it shows (the reference strategy) | `head:89` | B7 | S |

### Layout changes

| # | Change | Owner | Size |
|---|---|---|---|
| L1 | **Home: the "Can I rely on this yet?" verdict block, plus "Today in 3 lines" and "Paper trades so far"** (section 3) at the top | B14 (page), B7 if it becomes a shared block for the other pages | L |
| L2 | Empty states name when they fill (section 4), as one shared helper ("first finishes {date}") used by every page | B7 (helper), B14/B15/B16 (call sites) | M |
| L3 | Company page: open with one plain sentence and the chart, then the company's own paper results; move the horizon tabs and head-to-head detail lower | B15 | M |
| L4 | Help: add "Why the app does not tell you when to buy or sell", "When will each page fill?", and the missing glossary terms | B7 | M |
| L5 | A "Technical details" toggle for the footer, ids, calibration ids, raw codes and log loss | B7 (shared), page owners | M |
| L6 | Assistant: the starter "Can I rely on these signals yet?", and a decline that links to the Help section | B8 | S |

### New data fields

| # | Field | Read model | Owner | Size |
|---|---|---|---|---|
| D1 | Home `go_live`: add `drawdown_within_limit` and `holds_in_calm_and_volatile` (already computed on the scoreboard rows) | `rm_common.go_live` (B4, used by B11's `rm_home`) | B4 / B11 | S |
| D2 | `go_live_nearest`: the strategy closest to the bar, with its name, replacing or beside the reference strategy (Strategy lab already computes "Nearest to go-live" in the browser, `lab:126`) | `rm_common` / `rm_strategies` | B4 / B13 | M |
| D3 | Home `skill`: `state` and `why` of the weekly review's `model_skill` (Track record already has `track.skill`) | `rm_home` | B11 | S |
| D4 | Home: the benchmark's last move for "Today in 3 lines" | `rm_home` | B11 | S |
| D5 | `status.runs.intraday[].next_at` (the next check time), like `post_close.next_at` | `rm_common.status_block` | B4 | S |

### Suggested order

W1, W2 and W3 first: they are small, and they remove the three things that confused the owner most. Then L1 with D1
and D3. Then L2. The rest can follow.

---

## Appendix A: what this review did not change

No app code, data, config or read model was changed. Paper Portfolios' "0 open" and the "all paper trades in one
place" flow are B4/B13/B16's and are not redesigned here.

## Appendix B: how the internal-reference count was made

From `web/`:

```
grep -rnE 'decision [0-9]+|SPEC section|WS4|Wave 5|\(F[0-9]' "app/(cockpit)" components --include=*.tsx \
  | grep -v '^\S*:\s*//' | grep -c .
```

It printed `85` at `194133c`. The second grep drops lines that begin with `//`, but it can still count a few code
comments that sit inside JSX, so treat 85 as approximate.
