"""The deterministic numbers of a results release, from stored data only and point in time.

India: the quarter's NSE Integrated Filing values filed with the release (both bases, within a grace period; a
revision filed later is not used), with the same-basis quarter a year and a quarter earlier as filed by then.
US: fundamentals_metrics_asof at the first 10-Q/10-K that reported the quarter (numbers_as_of), so a later
restatement is never used; before that report is filed the numbers are `pending_report`. Growth uses |previous|
as the base (a shrinking loss reads as positive), margins are in % of revenue; both rounded to 2 decimals."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from marketbrief.results.constants import NUMBERS_OK, NUMBERS_PENDING, NUMBERS_UNAVAILABLE
from marketbrief.results.detection import Release

INDIA_ROWS_SQL = """
SELECT DISTINCT ON (basis, period_end) id, basis, period_start, period_end, revenue, revenue_item, total_income,
       profit_before_tax, net_profit, profit_to_owners, eps_basic, eps_diluted, filed_at
FROM financials
WHERE ticker = ? AND period_type = 'quarterly' AND filed_at <= ?::TIMESTAMPTZ AND first_seen_at <= ?::TIMESTAMPTZ
ORDER BY basis, period_end, filed_at DESC, first_seen_at DESC"""
INDIA_CUT_SQL = """
SELECT max(filed_at) FROM financials
WHERE ticker = ? AND period_type = 'quarterly' AND period_end = ?::DATE AND filed_at <= ?::TIMESTAMPTZ
  AND first_seen_at <= ?::TIMESTAMPTZ"""
US_PERIOD_SQL = """
SELECT max(period_end) FROM fundamentals
WHERE ticker = ? AND period <> 'instant' AND period_end > ?::DATE AND period_end < ?::DATE
  AND coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) <= ?::TIMESTAMPTZ
  AND first_seen_at <= ?::TIMESTAMPTZ"""
US_FIRST_REPORT_SQL = """
SELECT min(coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ))) FROM fundamentals
WHERE ticker = ? AND period <> 'instant' AND period_end = ?::DATE"""
US_METRICS_SQL = """
SELECT * FROM fundamentals_metrics_asof(?::TIMESTAMPTZ) WHERE ticker = ? AND period_end BETWEEN ?::DATE AND ?::DATE
ORDER BY period_end DESC"""
US_REPORT_SQL = """
SELECT DISTINCT accession FROM fundamentals_latest_asof(?::TIMESTAMPTZ) WHERE ticker = ? AND period_end = ?::DATE
ORDER BY accession"""


def clean(value):
    """A number as a plain float, or None for missing/NaN."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA:
        return None
    return float(value)


def growth_pct(current, previous) -> float | None:
    """(current - previous) / |previous| in %, 2 decimals; None when either is missing or previous is 0."""
    current, previous = clean(current), clean(previous)
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def margin_pct(part, revenue) -> float | None:
    """part / revenue in %, 2 decimals; None when either is missing or revenue is 0."""
    part, revenue = clean(part), clean(revenue)
    if part is None or not revenue:
        return None
    return round(part / revenue * 100, 2)


def india_fiscal_label(period_end: date) -> str:
    """Indian fiscal quarter of a quarter end (April-March year): 2026-06-30 -> FY2027 Q1."""
    year = period_end.year + 1 if period_end.month >= 4 else period_end.year
    return f"FY{year} Q{(period_end.month - 4) % 12 // 3 + 1}"


def near(rows: pd.DataFrame, period_end: date, days: tuple[int, int]) -> dict | None:
    """The row whose period end lies `days` (low, high) before period_end (the newest such), or None."""
    low, high = days
    ends = pd.to_datetime(rows["period_end"]).dt.date
    gap = ends.map(lambda end: (period_end - end).days)
    match = rows[(gap >= low) & (gap <= high)]
    return None if match.empty else match.sort_values("period_end").iloc[-1].to_dict()


def gap_days(period_end: date, row: dict | None) -> int | None:
    """Days between a quarter end and an earlier row's period end (QoQ compares quarters of unequal length when
    this is far from 91, e.g. a 16-week fourth quarter)."""
    return None if row is None else (period_end - pd.Timestamp(row["period_end"]).date()).days


def growth_block(current: dict, year: dict | None, quarter: dict | None, keys: dict[str, str]) -> dict:
    """<name>_yoy_pct and <name>_qoq_pct for each name -> column."""
    out = {}
    for name, column in keys.items():
        out[f"{name}_yoy_pct"] = growth_pct(current.get(column), year.get(column)) if year else None
        out[f"{name}_qoq_pct"] = growth_pct(current.get(column), quarter.get(column)) if quarter else None
    return out


def india_numbers(con, release: Release, now: pd.Timestamp, conf: dict) -> tuple[str, pd.Timestamp | None, dict]:
    """(numbers status, numbers as of, numbers) of an India results release, as filed by its release time: the
    quarter's filings (both bases) filed within `india_release_grace_hours` of the first one; anything filed later
    (a revision) is not used."""
    grace = release.release_at + pd.Timedelta(hours=float(conf.get("india_release_grace_hours", 24)))
    found = con.execute(
        INDIA_CUT_SQL, [release.ticker, str(release.period_end), grace.isoformat(), now.isoformat()]
    ).fetchone()[0]
    cut = release.release_at if found is None else max(release.release_at, pd.Timestamp(found).tz_convert("UTC"))
    rows = con.execute(INDIA_ROWS_SQL, [release.ticker, cut.isoformat(), now.isoformat()]).df()
    order = list(conf.get("india_basis_order") or ["consolidated", "standalone"])
    for basis in order:
        same = rows[rows["basis"] == basis] if not rows.empty else rows
        current = same[pd.to_datetime(same["period_end"]).dt.date == release.period_end] if not same.empty else same
        if current.empty:
            continue
        row = current.iloc[0].to_dict()
        year = near(same, release.period_end, (350, 380))
        quarter = near(same, release.period_end, tuple(conf.get("qoq_gap_days", [80, 125])))
        eps = clean(row["eps_diluted"]) if clean(row["eps_diluted"]) is not None else clean(row["eps_basic"])
        numbers = {
            "period_start": str(pd.Timestamp(row["period_start"]).date()),
            "period_end": str(release.period_end),
            "fiscal_label": india_fiscal_label(release.period_end),
            "basis": basis,
            "currency": "INR",
            "revenue": clean(row["revenue"]),
            "revenue_item": row.get("revenue_item"),
            "total_income": clean(row["total_income"]),
            "operating_profit": None,
            "profit_before_tax": clean(row["profit_before_tax"]),
            "net_profit": clean(row["net_profit"]),
            "profit_to_owners": clean(row["profit_to_owners"]),
            "eps_diluted": eps,
            "net_margin_pct": margin_pct(row["net_profit"], row["revenue"]),
            "pbt_margin_pct": margin_pct(row["profit_before_tax"], row["revenue"]),
            "operating_margin_pct": None,
            "gross_margin_pct": None,
            "prev_year_period_end": str(pd.Timestamp(year["period_end"]).date()) if year else None,
            "prev_quarter_period_end": str(pd.Timestamp(quarter["period_end"]).date()) if quarter else None,
            "prev_quarter_gap_days": gap_days(release.period_end, quarter),
            "derived": False,
            "filing_ids": [row["id"]],
        }
        if year:
            year = {**year, "eps": year["eps_diluted"] if clean(year["eps_diluted"]) is not None else year["eps_basic"]}
        if quarter:
            quarter = {
                **quarter,
                "eps": quarter["eps_diluted"] if clean(quarter["eps_diluted"]) is not None else quarter["eps_basic"],
            }
        keys = {"revenue": "revenue", "net_profit": "net_profit", "pbt": "profit_before_tax", "eps": "eps"}
        numbers.update(growth_block({**row, "eps": eps}, year, quarter, keys))
        return NUMBERS_OK, cut, numbers
    return NUMBERS_UNAVAILABLE, None, {}


def us_period(con, release: Release, now: pd.Timestamp, conf: dict) -> date | None:
    """The quarter end a US release reports: the newest period end in the report window known by now."""
    low = release.release_date - pd.Timedelta(days=int(conf.get("report_window_days", 75)))
    found = con.execute(
        US_PERIOD_SQL, [release.ticker, str(low), str(release.release_date), now.isoformat(), now.isoformat()]
    ).fetchone()[0]
    return None if found is None else pd.Timestamp(found).date()


def us_numbers(con, release: Release, now: pd.Timestamp, conf: dict) -> tuple[str, pd.Timestamp | None, dict]:
    """(numbers status, numbers as of, numbers) of a US release: fundamentals_metrics_asof at the first report of
    the quarter (pending_report until that 10-Q/10-K is filed)."""
    period_end = us_period(con, release, now, conf)
    if period_end is None:
        return NUMBERS_PENDING, None, {}
    cut = pd.Timestamp(con.execute(US_FIRST_REPORT_SQL, [release.ticker, str(period_end)]).fetchone()[0])
    cut = cut.tz_convert("UTC")
    low, high = (int(days) for days in conf.get("qoq_gap_days", [80, 125]))
    metrics = con.execute(
        US_METRICS_SQL, [cut.isoformat(), release.ticker, str(period_end - pd.Timedelta(days=high)), str(period_end)]
    ).df()
    current = metrics[pd.to_datetime(metrics["period_end"]).dt.date == period_end]
    if current.empty:
        return NUMBERS_PENDING, None, {}
    row = current.iloc[0].to_dict()
    quarter = near(metrics, period_end, (low, high))
    accessions = [
        found[0] for found in con.execute(US_REPORT_SQL, [cut.isoformat(), release.ticker, str(period_end)]).fetchall()
    ]
    numbers = {
        "period_start": None,
        "period_end": str(period_end),
        "fiscal_label": f"FY{int(row['fiscal_year'])} {row['fiscal_period']}",
        "basis": "sec_xbrl",
        "currency": "USD",
        "revenue": clean(row["revenue"]),
        "gross_profit": clean(row["gross_profit"]),
        "operating_profit": clean(row["operating_income"]),
        "profit_before_tax": None,
        "net_profit": clean(row["net_income"]),
        "eps_diluted": clean(row["eps_diluted"]),
        "net_margin_pct": margin_pct(row["net_income"], row["revenue"]),
        "operating_margin_pct": margin_pct(row["operating_income"], row["revenue"]),
        "gross_margin_pct": margin_pct(row["gross_profit"], row["revenue"]),
        "pbt_margin_pct": None,
        "revenue_yoy_pct": None if pd.isna(row["revenue_yoy"]) else round(float(row["revenue_yoy"]) * 100, 2),
        "net_profit_yoy_pct": None if pd.isna(row["net_income_yoy"]) else round(float(row["net_income_yoy"]) * 100, 2),
        "eps_yoy_pct": None if pd.isna(row["eps_yoy"]) else round(float(row["eps_yoy"]) * 100, 2),
        "operating_profit_yoy_pct": (
            None if pd.isna(row["operating_income_yoy"]) else round(float(row["operating_income_yoy"]) * 100, 2)
        ),
        "prev_year_period_end": None
        if pd.isna(row["yoy_period_end"])
        else str(pd.Timestamp(row["yoy_period_end"]).date()),
        "prev_quarter_period_end": str(pd.Timestamp(quarter["period_end"]).date()) if quarter else None,
        "prev_quarter_gap_days": gap_days(period_end, quarter),
        "derived": bool(row["derived"]),
        "filing_ids": accessions,
    }
    for name, column in (
        ("revenue", "revenue"),
        ("net_profit", "net_income"),
        ("eps", "eps_diluted"),
        ("operating_profit", "operating_income"),
    ):
        numbers[f"{name}_qoq_pct"] = growth_pct(row[column], quarter[column]) if quarter else None
    return NUMBERS_OK, cut, numbers
