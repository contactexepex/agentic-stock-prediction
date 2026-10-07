# Notes: queries and commands behind the decision pages

Rebuilt on 2026-10-07 (UTC) with the Material 3 design system (`design/system/`). The repo was read only;
everything written lives in this folder and under `work/design/` (gitignored scratch).

## Commands

- `python design/decision/build.py --market india --ticker HDFCBANK --out design/decision` (about 20 s once the
  back-test JSON exists): DuckDB reads (below), the rule-replay rows and walk-forward out-of-sample rows (library
  calls, in `history_rows`), cause derivation, costs, calendar, the drivers and checks -> `data-<TICKER>.json`,
  inlined with the design system (`design/system/system.py`) into `template.html` -> `decision-<TICKER>.html`.
  Also run for `--ticker ICICIBANK` and `--market us --ticker AAPL`.
- Inputs it caches under `work/design/` (not committed): `bt-<market>/model-backtest-<market>-<date>.json` from
  `python scripts/model_backtest.py --market <market> --out work/design/bt-<market>` (India 2026-10-07 13:08 UTC,
  US 13:15 UTC; run by build.py when missing, about 12 min) and the rule replay run into a scratch root
  `replayroot-<market>` (symlinks to the repo's data folders; `MB_ROOT=... scripts/replay.py --market m --start
  <window start> --end <as-of>`, 7 s).
- `node design/system/check_page.js design/decision/decision-HDFCBANK.html <out> hdfcbank '#chart svg'`:
  Playwright with the pre-installed Chromium at 1280 and 390 px; console errors/warnings, page errors, non-file
  requests, horizontal overflow. Result for all three pages and the style guide: "no console errors, no overflow,
  no external requests". Screenshots `shot-<ticker>-1280-full.png`, `shot-<ticker>-390-viewport.png`,
  `shot-hdfcbank-390-full.png`, `shot-hdfcbank-1280-hover.png` (chart tooltip).
- Before/after check of the data (HDFCBANK): the previous builder (commit 451963a) was rerun with the same cached
  inputs and reproduced the committed `decision-HDFCBANK.html` byte for byte; its `data.json` against the new
  `data-HDFCBANK.json` without the added `page` block differs only in label text: the cause labels say "Nifty 50"
  (the config name) instead of "Nifty", the 17 Oct results event is named "HDFC Bank results (Saturday; reaction on
  Mon 19 Oct)" instead of the hand-written "HDFC Bank Q2 FY27 results (...)", and `live.indices` is now ordered by
  index name (the old query had no ORDER BY). Every number is identical.

## Window and generic rules

- Back-test window = the 35 sessions up to the as-of date (the ticker's latest stored bar): India 17 Aug–6 Oct,
  US 18 Aug–6 Oct (the US calendar has one fewer session in September).
- "Today" = the next session after the as-of date; events window = 10 weeks, weekly expiries only in the first
  week; the page lists events up to 54 days out.
- 52-week position from `ohlc` highs/lows over 365 days: "52-week low area" within 5% of the low, "high area"
  within 5% of the high, else "x% below the 52-week high".
- Plan per horizon: the live range `<as_of>-<T>-<h>d` when stored (AAPL: both; HDFCBANK: 5d only), else the rule
  replay's row for the as-of date (labelled "rule replay, not published live").
- Checks: chance >= 60% from `model_scores_latest`; skill from the latest `reviews.model_skill`; run before the
  open = latest `computed_at` vs `calendar.session_open_utc` of today's session; evidence = best `news_verified`
  cluster status of the ticker's stored headlines; results = `features_latest.days_to_earnings` > 1.
- Drivers: Company = top 5 enriched headlines by |sentiment| x materiality (plus NSE delivery % for India, FINRA
  short interest for the US, and the model's technical points); Sector = the sector index/ETF of the market
  config (NSE `indices_latest` where its name matches, else stored bars), the peer's ADR/pre-market quote or
  close, index valuation (India), the peer's top headline; Market = today's major events (regime), the stock's own
  ADR/pre-market cue, FII/DII flows (India), the market's cue symbols, US 10y + DXY, oil + rupee (India) or oil +
  gold (US), the vol index + regime. Direction of market drivers is the conventional reading (yields up = down,
  oil up = down except Energy), stated in each tooltip.

## DuckDB queries (run from `scripts/`, `connect(market)`)

- Prices: `ohlc` for the ticker, benchmark, vol index and sector index (`config/markets/<m>.yaml` roles).
- Live rows: `model_scores`, `model_scores_latest`, `ranges`, `agent_reasoning`, `features_latest`, `regime`
  (latest by computed_at), `quotes_latest` (latest day), `flows_daily`, `fpi_latest`, `indices_latest`,
  `delivery_stats`, `earnings_estimates`, `short_interest_latest`, `shorts_latest`, `reviews`, `predictions`,
  `outcomes` (joined to predictions by ticker: 0 rows for every ticker on 2026-10-07).
- News: `news` where `list_contains(tickers, T)` joined to `enriched_latest` and `news_verified` level `cluster`
  (id `<T>-<newsid>|*@...`); items without a cluster row are "not assessed". The local day of a headline uses
  `timezone(<market tz>, published_at)`.
- Events: `events` type `earnings` for the ticker (reaction session: `calendar.next_session`, the day after for
  `after_close`); market events from `core.calendar.market_events`.
- Costs: `model.settings.load_costs(market)`, `round_trip_cost(market, costs, price=last close)`: India
  0.0022248 (Rs 22.25 per Rs 10,000), US 0.0000206 at $333.63 ($0.21 per $10,000; FINRA TAF paused at $0).
