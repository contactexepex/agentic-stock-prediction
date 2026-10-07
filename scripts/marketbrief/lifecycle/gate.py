"""The collect gate of one onboarding candidate (F8.3): the daily collect gate's checks that concern a company, run
on the candidate-mode config (validate.py's checks of market symbols, quotes, news runs and collector summaries are
the routine's, not the candidate's): no duplicate ids in the kinds the backfill wrote, a bar for the last completed
session, positive recent closes, big moves noted, and at least `min_bars` bars. A STALE_BARS failure becomes a
warning when the candidate's newest bar is not older than the market benchmark's newest stored bar: the candidate is
then as current as the rest of the market (e.g. Yahoo has not finalised the last session's bar yet), and the
routine's own collect gate judges the whole market's freshness."""
from __future__ import annotations

import yaml

from marketbrief.constants.files import DIR_CONFIG_MARKETS, YAML_SUFFIX
from marketbrief.constants.kinds import KIND_ANNOUNCEMENTS, KIND_FILINGS, KIND_NEWS, KIND_PRICES
from marketbrief.core import clock, database, paths
from marketbrief.core.market_config import benchmark_key
from marketbrief.pipeline.validate.collect_checks import check_bars, check_duplicates
from marketbrief.pipeline.validate.gate_result import Result, load_config, run_status

BACKFILL_KINDS = [KIND_PRICES, KIND_NEWS, KIND_FILINGS, KIND_ANNOUNCEMENTS]


def candidate_gate(cfg: dict, min_bars: int) -> dict:
    """{ok, failures, warnings, bars} of the candidate config's single company."""
    res, validate_config = Result(), load_config()
    con = database.connect(cfg["market"])
    check_duplicates(res, cfg, con, validate_config, only_kinds=BACKFILL_KINDS)
    check_bars(res, cfg, con, run_status(cfg), validate_config)
    ticker = next(iter(cfg["tickers"]))
    relax_stale(res, con, cfg["market"], ticker)
    bars = con.execute("SELECT count(*) FROM bars WHERE ticker = ?", [ticker]).fetchone()[0]
    if bars < min_bars:
        res.block("TOO_FEW_BARS", f"{bars} stored bars, at least {min_bars} needed", [ticker])
    return {"ok": not res.failures, "failures": res.failures, "warnings": res.warnings, "bars": int(bars),
            "checked_at": clock.utc_now()}


def relax_stale(res, con, market: str, ticker: str) -> None:
    """Move STALE_BARS to the warnings when the candidate is as current as the market's benchmark."""
    raw = yaml.safe_load((paths.CONFIG / DIR_CONFIG_MARKETS / f"{market}{YAML_SUFFIX}").read_text())
    benchmark = benchmark_key({"symbols": raw.get("symbols") or {}})
    newest = dict(con.execute("SELECT ticker, max(date) FROM bars WHERE ticker IN (?, ?) GROUP BY 1",
                              [ticker, benchmark]).fetchall())
    if benchmark not in newest or ticker not in newest or newest[ticker] < newest[benchmark]:
        return
    for failure in [entry for entry in res.failures if entry["code"] == "STALE_BARS"]:
        res.failures.remove(failure)
        res.warn("STALE_BARS_MARKET_WIDE", f"{failure['detail']}; the benchmark {benchmark}'s newest stored bar is "
                 f"{newest[benchmark]} too", failure["tickers"])
