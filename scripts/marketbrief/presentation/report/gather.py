"""The stored data the report skeleton is built from."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from marketbrief.constants.horizon_names import BASIS_KEY_SQL, LABEL_ORDER_SQL
from marketbrief.constants.messages import MSG_NO_PUBLISHED_RANGES
from marketbrief.core import paths
from marketbrief.core.clock import utc_today
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.presentation.news_events import call_status_lines
from marketbrief.presentation.reader.links import brief_path
from view_data import CONF_BANDS_SQL, RANGE_RECORD_EXACT

# Scored records twice: since start, and the rolling last 30 days (by target date).
WINDOWS = """SELECT *, 'since start' AS win FROM {src}
             UNION ALL SELECT *, 'last 30 days' AS win FROM {src} WHERE target_date >= current_date - 30"""

# per horizon and horizon label (core/horizons.py): ranges of an old window (legacy_cc) never pooled with N+k
SCORECARD_SQL = f"""
    SELECT horizon_days AS h, horizon_label AS label, win, count(*) AS n, avg(hit50::INT) AS c50,
           avg(hit80::INT) AS c80, avg(naive_hit80::INT) AS nc80, avg(width80_pct) AS w, avg(naive_width80_pct) AS nw,
           avg(is80_pct) AS s, avg(naive_is80_pct) AS ns,
           avg(center_err_pct) AS ce, avg(naive_center_err_pct) AS nce
    FROM ({WINDOWS.format(src=RANGE_RECORD_EXACT)}) GROUP BY h, label, win
    ORDER BY h, {LABEL_ORDER_SQL}, win DESC"""


def weekly_review(con, session) -> dict | None:
    """Stored review (review.py) of the ISO week before the session's week, if any."""
    year, week, _ = (session - timedelta(days=7)).isocalendar()
    review_frame = con.execute(
        "SELECT week, report, n_proposals, low_sample, CAST(computed_at AS DATE) AS day "
        "FROM review_latest WHERE id = ?",
        [f"{year}-W{week:02d}"],
    ).df()
    if review_frame.empty:
        return None
    out = review_frame.iloc[0].to_dict()
    out["fresh"] = pd.Timestamp(out["day"]).date() == utc_today()  # written in this run -> one Slack line
    return out


def gather(cfg: dict, con) -> dict:
    """Read the day's ranges, regime, features, scores and events from the data."""
    query = lambda sql, params=None: con.execute(sql, params or []).df()  # noqa: E731
    ranges = query("SELECT * FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)")
    if ranges.empty:
        raise SystemExit(MSG_NO_PUBLISHED_RANGES)
    as_of = pd.Timestamp(ranges["as_of_date"].iloc[0]).date()
    last_target = con.execute("SELECT max(target_date) FROM range_record").fetchone()[0]
    return {
        "as_of": as_of,
        "session": pd.Timestamp(ranges["session_date"].iloc[0]).date(),
        "ranges": ranges,
        "regime": query("SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1"),
        "features": query("SELECT * FROM features_latest WHERE as_of_date = ? ORDER BY ticker", [as_of]),
        "quotes": query("SELECT * FROM quotes_latest WHERE day = (SELECT max(day) FROM quotes_latest) ORDER BY symbol"),
        "scored": query(
            "SELECT * FROM range_record WHERE target_date = ? ORDER BY ticker, horizon_days, id", [last_target]
        ),
        "last_target": last_target,
        "calls_scored": query(
            "SELECT * FROM track_record WHERE target_date = (SELECT max(target_date) FROM track_record) "
            "ORDER BY ticker, horizon_days, id"
        ),
        # scoring per horizon over the last 30 days and since start (docs/DESIGN.md section 6)
        "scorecard": query(SCORECARD_SQL),
        "by_regime": query(f"""SELECT horizon_days AS h, horizon_label AS label, coalesce(regime, '?') AS regime,
                                  count(*) AS n, avg(hit50::INT) AS c50, avg(hit80::INT) AS c80,
                                  avg(naive_hit80::INT) AS nc80
                           FROM range_record GROUP BY h, label, regime
                           ORDER BY h, {LABEL_ORDER_SQL}, regime"""),
        # per scoring basis key (scoring.basis_key): old D+4 open-to-close calls never pooled with N+k
        "direction": query(f"""SELECT horizon_days AS h, {BASIS_KEY_SQL} AS label_basis, win, count(*) AS n,
                                  avg(hit::INT) AS hit, avg((actual_return > 0)::INT) AS up
                           FROM ({WINDOWS.format(src="track_record")}) GROUP BY ALL
                           ORDER BY h, label_basis, win DESC"""),
        "conf_bands": query(CONF_BANDS_SQL),
        "market": query(
            """SELECT ticker, close, ret_1d FROM returns WHERE date = ? AND list_contains(?, ticker)""",
            [as_of, [key for key in (benchmark_key(cfg), vol_index_key(cfg)) if key]],
        ),
        "calibration": query("SELECT * FROM calibration_latest ORDER BY horizon_days"),
        "company_events": query(
            "SELECT date, name FROM company_events WHERE date BETWEEN ? AND ? ORDER BY date",
            [as_of, as_of + timedelta(days=21)],
        ),
        "review": weekly_review(con, pd.Timestamp(ranges["session_date"].iloc[0]).date()),
        "evidence_status": call_status_lines(con, as_of),  # news verification status of each call's evidence
        "charts": {
            params.name
            for params in (
                paths.ROOT
                / "reports"
                / cfg["market"]
                / "charts"
                / str(pd.Timestamp(ranges["session_date"].iloc[0]).date())
            ).glob("*.png")
        },
    }


def report_url(settings: dict, market: str, session, app: str | None = None) -> str:
    """The Slack draft's link: the market's page in the app (`app` = config/settings.yaml slack_link_url) when set;
    otherwise the HTML report in the repo (GitHub shows HTML as source, which is why the Slack thread also
    attaches the file)."""
    if app:
        return f"{app.rstrip('/')}/{market}"
    return f"{settings['repo_url']}/blob/{settings['branch']}/reports/{market}/{session}.html"


def brief_url(settings: dict, market: str, session) -> str | None:
    """The day's public brief page (C2): `brief_link_url` + brief_path(market, session); None without the setting or
    without BRIEF_LINK_SECRET (the caller keeps report_url's link)."""
    base, path = settings.get("brief_link_url"), brief_path(market, str(session))
    return f"{base.rstrip('/')}{path}" if base and path else None
