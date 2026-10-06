"""Walk-forward backtest of the range formula (no AI) on stored bars for one market.

For each evaluation day d (the last --eval-sessions trading days) and horizon h, the range is built exactly as live
(EWMA volatility at d, empirical quantiles from a recency-weighted pool of outcomes already known at d) and scored on
the close h sessions later. The naive baseline is last close +/- 20-day realized volatility with normal quantiles.
Regime and AI adjustments are not replayed, so the headline numbers test the core formula.

Range inputs (config/ranges.yaml, docs/DESIGN.md section 11) are then switched off and on, each
scored where it applies (docs/DESIGN.md section 7: keep an input only if it improves accuracy):
- earnings_history: earnings widening sized from the stock's past earnings-day moves (only
  reactions completed before d) vs the fixed multiplier; earnings dates from event_history, with
  the SEC 2.02 filings that are not results releases dropped as known at d (only 10-Q/10-K
  reports accepted by d are used: event_history.earnings_versions).
- ex_dividend: centre shifted down by dividends going ex inside the horizon vs no shift.
- beta_split: beta x index cue + own cue net of it vs the direct own cue. Historical cues are
  proxies: a numeric index_cue beta (US futures) uses the benchmark's next open gap; "fit" uses
  the cue's previous session return (exactly what is known live); the own cue is the stock's
  next open gap if the market has pre-market quotes, else none (ADR history is not stored).
- implied_vol has no stored history: live only, not backtested.
Writes reports/<market>/backtest-<as_of>.md (or --out) and prints a JSON summary."""
from __future__ import annotations

import json
from pathlib import Path
from marketbrief.core import cli, market_config, paths
from marketbrief.replay.backtest.report import markdown, run


def main() -> int:
    ap = cli.market_arg(__doc__)
    ap.add_argument("--eval-sessions", type=int, default=250, help="trading days to evaluate (default 250)")
    ap.add_argument("--out", help="write the report here instead of reports/<market>/")
    args = ap.parse_args()
    cfg = cli.require_market(args)
    rc = market_config.load_ranges_config(cfg["market"])
    s = run(cfg, rc, args.eval_sessions)
    path = Path(args.out) if args.out else paths.ROOT / "reports" / cfg["market"] / f"backtest-{s['as_of_date']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(cfg, s))
    print(json.dumps({"step": "backtest", "report": str(path), "horizons": s["horizons"],
                      "inputs": s["inputs"], "event_history": s["event_history"]}, indent=2, default=str))
    return 0
