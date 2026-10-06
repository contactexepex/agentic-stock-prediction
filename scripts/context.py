#!/usr/bin/env python3
"""Print a compact Markdown context pack for one market's agents: regime, upcoming events,
overnight cues and global factors, PASDS indicators, prices and returns, news activity,
filings, macro and flows (yields, credit spreads, put/call, short selling; India FPI and
indices), open predictions and the track record, and the previous run's judge FAILs that its
report could not list (for today's data_quality). Agents read this instead of raw files."""
from __future__ import annotations

from datetime import timedelta

import events as ev
import fundamentals as fu
import graph
import macro_context
import nse_context
import relations
import smart_money as sm
from score_predictions import is_late
from common import connect, market_arg, md_table, require_market, utc_today
from features import local_today

PCT = "round({} * 100, 2)"


def sections(cfg: dict) -> list[tuple[str, str, list]]:
    roles = {k: v.get("role") for k, v in cfg["symbols"].items()}
    names = {**{k: v.get("name", k) for k, v in cfg["symbols"].items()},
             **{f"{k}:ADR": f"{v['name']} ADR ({v.get('adr')})" for k, v in cfg["tickers"].items()}}
    case_name = "CASE symbol " + " ".join(f"WHEN '{k}' THEN '{v.replace(chr(39), '')}'" for k, v in names.items()) + " ELSE symbol END"
    case_role = "CASE symbol " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in roles.items()) + " ELSE 'ticker' END"
    sector = "CASE ticker " + " ".join(f"WHEN '{k}' THEN '{v.get('sector') or ''}'" for k, v in cfg["tickers"].items()) + " END"
    etf_of = "CASE ticker " + " ".join(f"WHEN '{k}' THEN '{v.get('sector_etf') or ''}'" for k, v in cfg["tickers"].items()) + " END"
    covers = {k: ", ".join(v.get("sectors") or []).replace("'", "") for k, v in cfg["symbols"].items()}
    case_covers = "CASE ticker " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in covers.items()) + " ELSE '' END"
    tickers = list(cfg["tickers"])
    return [
        ("Market regime (latest)", """
            SELECT as_of_date, session_date, regime, vol_level, round(vol_change_1d * 100, 1) AS vol_chg_pct,
                   round(bench_ret_5d * 100, 2) AS bench_5d_pct, round(bench_vol_10d * 100, 1) AS bench_vol_10d_pct,
                   major_event, major_event_names, stress, notes
            FROM regime_latest ORDER BY as_of_date DESC LIMIT 1""", []),
        ("Overnight cues and global factors (latest snapshot today, UTC)", f"""
            SELECT symbol, {case_name} AS name, {case_role} AS role, price, prev_close,
                   round(change_pct * 100, 2) AS change_pct, ts
            FROM quotes_latest WHERE day = current_date ORDER BY role, symbol""", []),
        ("Sector ETFs and indices (latest bar; returns in %)", f"""
            SELECT ticker, {case_name.replace('symbol', 'ticker')} AS name, {case_covers} AS watchlist_sectors,
                   date, round(close, 2) AS close,
                   round(ret_1d * 100, 2) AS d1, round(ret_5d * 100, 2) AS d5, round(ret_20d * 100, 2) AS d20
            FROM returns WHERE list_contains(?, ticker)
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
            ORDER BY ticker""", [[k for k, v in cfg["symbols"].items() if v.get("role") == "sector_etf"] or [""]]),
        ("Indicators (latest snapshot; returns and vol in %)", f"""
            SELECT ticker, {sector} AS sector, {etf_of} AS sector_etf, quality, round(close, 2) AS close,
                   round(ret_1d * 100, 2) AS d1, round(ret_5d * 100, 2) AS d5, round(ret_20d * 100, 2) AS d20,
                   round(rsi_14, 0) AS rsi, round(ema_ratio, 3) AS ema_r, round(price_vs_20d_high, 3) AS vs_20d_hi,
                   round(atr_pct * 100, 2) AS atr_pct, round(ewma_vol * 100, 1) AS ewma_vol,
                   round(volume_ratio_20d, 2) AS vol_ratio, round(obv_trend, 2) AS obv,
                   round(beta_1y, 2) AS beta, round(rel_sector_5d * 100, 2) AS vs_peer_5d,
                   round(cue_change_pct * 100, 2) AS cue_pct, days_to_earnings, ex_dividend_date
            FROM features_latest
            WHERE as_of_date = (SELECT max(as_of_date) FROM features_latest) AND list_contains(?, ticker)
            ORDER BY sector, ticker""", [tickers]),
        # role/tag_confidence (scripts/news_tags.py): primary_7d = items about the ticker (named in
        # the headline as the subject); low_conf_7d = tags to read with care (several companies in
        # the headline, a comparison or list, or named only in the summary)
        ("News activity and sentiment by window (primary = about the ticker; low_conf = mentioned or ambiguous tag)", """
            SELECT ticker,
                   count(*) FILTER (WHERE day >= current_date - 1)  AS n_1d,
                   count(*) FILTER (WHERE day >= current_date - 7)  AS n_7d,
                   count(*) FILTER (WHERE day >= current_date - 7 AND role = 'primary') AS primary_7d,
                   count(*) FILTER (WHERE day >= current_date - 7 AND tag_confidence = 'low') AS low_conf_7d,
                   count(*) FILTER (WHERE day >= current_date - 30) AS n_30d,
                   round(avg(sentiment) FILTER (WHERE day >= current_date - 7), 2)  AS sent_7d,
                   round(avg(sentiment) FILTER (WHERE day >= current_date - 30), 2) AS sent_30d,
                   count(*) FILTER (WHERE materiality = 'high' AND day >= current_date - 7) AS high_7d
            FROM news_ticker_day GROUP BY ticker ORDER BY ticker""", []),
        ("SEC filings, last 14 days", """
            SELECT ticker, form, filing_date, description, url
            FROM filings WHERE filing_date >= current_date - 14 ORDER BY filing_date DESC, ticker""", []),
        ("Open predictions", """
            SELECT id, ticker, as_of_date, horizon_days, direction, confidence FROM open_predictions
            ORDER BY as_of_date, ticker""", []),
        ("Price ranges published for the latest session (80% and 50%)", """
            SELECT ticker, horizon_days AS h, target_date, round(base_close, 2) AS base,
                   round(lo80, 2) AS lo80, round(lo50, 2) AS lo50, round(hi50, 2) AS hi50, round(hi80, 2) AS hi80,
                   direction, confidence, notes,
                   CASE WHEN id IN (SELECT id FROM late_ranges) THEN 'late: not a forecast, never scored'
                        ELSE '' END AS late
            FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)
            ORDER BY ticker, h""", []),
        ("Ranges scored on the latest target date (yesterday's calls)", """
            SELECT ticker, horizon_days AS h, target_date, round(lo80, 2) AS lo80, round(hi80, 2) AS hi80,
                   round(actual_close, 2) AS actual, hit50, hit80, naive_hit80
            FROM range_record WHERE target_date = (SELECT max(target_date) FROM range_record)
            ORDER BY ticker, h""", []),
        ("Range scorecard (targets: 50% and 80% coverage; score lower is better)", """
            SELECT horizon_days AS h, CASE WHEN target_date >= current_date - 30 THEN 'last 30d' ELSE 'older' END AS window,
                   count(*) AS n, round(avg(hit50::INT), 3) AS cover50, round(avg(hit80::INT), 3) AS cover80,
                   round(avg(naive_hit80::INT), 3) AS naive_cover80,
                   round(avg(width80_pct), 2) AS width80_pct, round(avg(naive_width80_pct), 2) AS naive_width80_pct,
                   round(avg(is80_pct), 3) AS score80, round(avg(naive_is80_pct), 3) AS naive_score80
            FROM range_record GROUP BY ALL
            UNION ALL
            SELECT horizon_days, 'all', count(*), round(avg(hit50::INT), 3), round(avg(hit80::INT), 3),
                   round(avg(naive_hit80::INT), 3), round(avg(width80_pct), 2), round(avg(naive_width80_pct), 2),
                   round(avg(is80_pct), 3), round(avg(naive_is80_pct), 3)
            FROM range_record GROUP BY horizon_days ORDER BY 1, 2""", []),
        ("Track record by horizon (all time; vs always-up baseline)", """
            SELECT horizon_days, count(*) AS n, round(avg(hit::INT), 3) AS hit_rate,
                   round(avg((actual_return > 0)::INT), 3) AS always_up_rate,
                   round(avg(confidence), 3) AS avg_confidence
            FROM track_record GROUP BY horizon_days ORDER BY horizon_days""", []),
        ("Track record by confidence band, last 90 days", """
            SELECT CASE WHEN confidence < 0.6 THEN '0.50-0.59'
                        WHEN confidence < 0.7 THEN '0.60-0.69' ELSE '0.70+' END AS band,
                   count(*) AS n, round(avg(hit::INT), 3) AS hit_rate
            FROM track_record WHERE target_date >= current_date - 90 GROUP BY band ORDER BY band""", []),
    ]


def sector_gaps(cfg: dict) -> str:
    """Watchlist sectors that no sector ETF or index stands for (empty when all are mapped)."""
    gaps = [s for s in cfg.get("sectors") or {} if s not in cfg.get("sector_etfs", {})]
    return f"Watchlist sectors without a sector ETF or index: {', '.join(gaps)}\n" if gaps else ""


def upcoming_events(cfg: dict, con) -> str:
    start = local_today(cfg)
    session = ev.next_session(cfg, start)
    rows = [(e["date"], e["name"], "major" if e["major"] else "") for e in
            ev.market_events(cfg, start, session + timedelta(days=14))]
    rows += con.execute("SELECT date, name, type FROM company_events WHERE date BETWEEN ? AND ?",
                        [start, session + timedelta(days=14)]).fetchall()
    if not rows:
        return "_none_\n"
    rows.sort(key=lambda r: (r[0], r[1]))
    return "| date | event | note |\n|---|---|---|\n" + "".join(f"| {d} | {n} | {k} |\n" for d, n, k in rows)


JUDGE_LOOKBACK_DAYS = 7

# The previous run (latest run_date before today, at most JUDGE_LOOKBACK_DAYS back): each agent's
# final verdict that is a FAIL recorded after that run's last report/slack verdict, i.e. one its
# report could not list (the step 14 graph-builder), or every final FAIL if it never got that far.
JUDGE_FAILS_SQL = """
WITH prev AS (SELECT max(run_date) AS d FROM judgments WHERE run_date < ?::DATE AND run_date >= ?::DATE - ?),
reported AS (SELECT max(recorded_at) AS t FROM judgments, prev
             WHERE run_date = prev.d AND agent IN ('report', 'slack')),
final AS (SELECT j.* FROM judgments j, prev WHERE j.run_date = prev.d
          QUALIFY row_number() OVER (PARTITION BY j.agent ORDER BY j.recorded_at DESC, j.round DESC) = 1)
SELECT f.run_date, f.agent, f.round, f.summary, f.dropped, f.recorded_at
FROM final f, reported
WHERE upper(f.verdict) = 'FAIL' AND (reported.t IS NULL OR f.recorded_at > reported.t)
ORDER BY f.recorded_at"""


def judge_fails(con, today) -> str:
    """Judge FAILs of the previous run that its own report could not list (CLAUDE.md "Judging
    every change"; routine/PROMPT.md step 14): the report copies each into `data_quality`."""
    return md_table(con.execute(JUDGE_FAILS_SQL, [today, today, JUDGE_LOOKBACK_DAYS]))


def main() -> None:
    cfg = require_market(market_arg(__doc__).parse_args())
    con = connect(cfg["market"])
    print(f"# Context pack: {cfg['name']}, {utc_today()} (UTC)\n")
    # ranges made at/after the open of the first session after as_of: shown, never scored
    latest = con.execute("SELECT id, as_of_date, made_at FROM ranges_latest "
                         "WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)").fetchall()
    late = [rid for rid, as_of, made in latest if is_late(cfg, as_of, made)]
    con.execute("CREATE OR REPLACE TEMP TABLE late_ranges AS SELECT unnest(?::VARCHAR[]) AS id", [late])
    blocks = sections(cfg)
    for title, sql, params in blocks[:2]:
        print(f"## {title}\n\n{md_table(con.execute(sql, params))}")
    print(f"## Upcoming events (next 14 days)\n\n{upcoming_events(cfg, con)}")
    for title, sql, params in blocks[2:]:
        if title.startswith("SEC") and cfg.get("filings") != "sec":
            continue
        print(f"## {title}\n\n{md_table(con.execute(sql, params))}")
        if title.startswith("Sector ETFs") and sector_gaps(cfg):
            print(sector_gaps(cfg))
    # Relationships (phase 5): India insider trades, deals, pledges and flags; connections (both markets).
    # India primary sources from NSE (flows, announcements, results, delivery); empty elsewhere.
    # Macro & flows (US Treasury/FRED/Cboe and FINRA shorts; India NSDL FPI and NSE indices).
    for title, body in [*relations.context_sections(cfg, con), graph.context_section(cfg, con),
                        *nse_context.context_sections(cfg, con), *macro_context.context_sections(cfg, con)]:
        print(f"## {title}\n\n{body}")
    print(sm.markdown(cfg, con))
    print(fu.markdown(cfg, con))  # US: last reported quarter from SEC XBRL (no consensus, no "surprise")
    print("## Judge FAILs from the previous run not yet in a report (copy each into data_quality)\n\n"
          f"{judge_fails(con, utc_today())}")


if __name__ == "__main__":
    main()
