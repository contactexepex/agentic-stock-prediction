"""Context-pack section "Results digests" (WS6, docs/ws/ws6.md): the results and earnings-call digests of the active
companies released in the last `detection.lookback_days` (config/results.yaml), as stored by now
(results_digests_asof(now()), so MB_NOW applies and a digest stored later is never shown). Numbers are the
deterministic ones of the release; bullets are the gated results-analyst's, each with its source id. Context only:
no range, model or prediction rule reads it. Omitted when no digest is in the window, so the pack is unchanged then."""

from __future__ import annotations

import json

from marketbrief.core import paths
from marketbrief.lifecycle.loader import active_tickers
from marketbrief.pipeline.forecast_gate import evidence_times
from marketbrief.results.constants import FILE_RESULTS_CONFIG
from marketbrief.results.digest import load_settings
from marketbrief.utils.markdown import cursor_markdown_table

TITLE = "Results digests (last {days} days; context only, not a range or forecast input)"
NOTE = (
    "Numbers as of each release, from stored filings (no later restatement). `surprise_pct` = EPS against the last "
    "consensus stored before the release (context only). `reaction_pct` = the close-to-close move over the earnings "
    "window when the digest was stored. Bullets quote the filed text verbatim. `cite:` names the filing or NSE "
    "announcement id the forecast gate accepts as evidence; a bullet without one is context only.\n\n"
)
ROWS_SQL = """
FROM results_digests_asof(now())
WHERE list_contains(?, ticker) AND release_at >= now() - to_days(CAST(? AS INTEGER)) AND release_at <= now()"""
TABLE_SQL = (
    """
SELECT ticker, CAST(release_date AS VARCHAR) AS released, release_kind AS kind, fiscal_label AS quarter,
       TRY_CAST(numbers->>'$.revenue_yoy_pct' AS DOUBLE) AS revenue_yoy_pct,
       TRY_CAST(numbers->>'$.net_profit_yoy_pct' AS DOUBLE) AS net_profit_yoy_pct,
       TRY_CAST(numbers->>'$.eps_diluted' AS DOUBLE) AS eps,
       TRY_CAST(consensus->>'$.surprise_pct' AS DOUBLE) AS surprise_pct,
       TRY_CAST(reaction->>'$.move_pct' AS DOUBLE) AS reaction_pct, status, numbers_status"""
    + ROWS_SQL
    + "\nORDER BY release_at DESC, id"
)
DEFAULT_DAYS = 10
BULLETS_SQL = "SELECT ticker, release_kind, CAST(bullets AS VARCHAR)" + ROWS_SQL + "\nORDER BY release_at DESC, id"


def window_days() -> int:
    """`detection.lookback_days` of config/results.yaml; DEFAULT_DAYS when the config folder has no results.yaml (a
    scratch root of a test or replay), so the context pack never fails over this section."""
    if not (paths.CONFIG / FILE_RESULTS_CONFIG).exists():
        return DEFAULT_DAYS
    return int((load_settings().get("detection") or {}).get("lookback_days", DEFAULT_DAYS))


def citation(bullet: dict, citable: dict) -> str:
    """`cite: <id>` for the bullet's filing or announcement (a stored text's id is `<that id>:<document>`) when the
    forecast gate knows that id (forecast_gate.evidence_times), else `context only` (e.g. an SEC filing found
    through the submissions fallback but not in `filings`)."""
    primary = str(bullet["source_id"]).split(":", 1)[0]
    return f"cite: {primary}" if primary in citable else "context only"


def context_section(cfg: dict, con) -> tuple[str, str] | None:
    """(title, body) of the section, or None when no digest of an active company falls in the window."""
    days = window_days()
    params = [sorted(active_tickers(cfg)), days]
    table = cursor_markdown_table(con.execute(TABLE_SQL, params))
    if table.startswith("_none_"):
        return None
    lines, citable = [], evidence_times(con)
    for ticker, kind, bullets in con.execute(BULLETS_SQL, params).fetchall():
        for bullet in json.loads(bullets or "[]"):
            lines.append(f"- {ticker} {kind} {bullet['topic']}: {bullet['text']} [{citation(bullet, citable)}]")
    return TITLE.format(days=days), NOTE + table + ("\n" + "\n".join(lines) + "\n" if lines else "")
