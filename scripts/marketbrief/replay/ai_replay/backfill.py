"""backfill: a scratch source root with longer histories, filled by the collectors."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from marketbrief.constants.ai_replay import (
    BACKFILL_KINDS,
    BACKFILL_STEPS,
    MSG_NO_BACKFILL_STEPS_FOR_MARKET,
    MSG_SINCE_MUST_BE_BEFORE_TODAY,
    MSG_SOURCE_EXISTS_IS_NOT_EMPTY_AND,
    MSG_SOURCE_IS_INSIDE_THE_REAL_DATA,
    MSG_SOURCE_IS_THE_REPO_ITS_REAL,
    PUBLIC_AT,
    SOURCE_MARKER,
)
from marketbrief.core import paths
from marketbrief.core.clock import utc_today
from marketbrief.replay.ai_replay.copy_asof import public_at
from marketbrief.replay.ai_replay.roots import json_or_text, run_script
from marketbrief.utils.timefmt import as_utc_timestamp


def check_source(source: Path) -> Path:
    """The scratch source must not be the repo, the real data/ or anything inside or above it."""
    resolved = source.resolve()
    for real_root in {paths.CODE.resolve(), Path(paths.ROOT).resolve()}:
        real = real_root / "data"
        if resolved == real_root or resolved == real or real in resolved.parents or resolved in real_root.parents:
            raise SystemExit(MSG_SOURCE_IS_THE_REPO_ITS_REAL.format(resolved=resolved))
    for ancestor in [
        resolved,
        *resolved.parents,
    ]:  # any other market-brief checkout's data/ (e.g. the main clone of a worktree)
        if (
            ancestor.name == "data"
            and (ancestor.parent / "config" / "markets").is_dir()
            and (ancestor.parent / "scripts").is_dir()
        ):
            raise SystemExit(MSG_SOURCE_IS_INSIDE_THE_REAL_DATA.format(resolved=resolved, parent=ancestor.parent))
    if resolved.exists() and any(resolved.iterdir()) and not (resolved / SOURCE_MARKER).exists():
        raise SystemExit(MSG_SOURCE_EXISTS_IS_NOT_EMPTY_AND.format(resolved=resolved))
    return resolved


def backfill_config(cfg_dir: Path, market: str, since: date, today: date) -> dict:
    """Longer lookbacks in the scratch source's config copy only (never the repo's config)."""
    import yaml

    path = cfg_dir / "markets" / f"{market}.yaml"
    doc = yaml.safe_load(path.read_text())
    days = (today - since).days + 1
    changed = {}
    if doc.get("filings") == "sec":
        doc["filing_lookback_days"] = changed["filing_lookback_days"] = days
        for key in ("insiders", "stakes"):
            if key in (doc.get("relationships") or {}):
                doc["relationships"][key]["lookback_days"] = changed[f"relationships.{key}.lookback_days"] = days
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return changed


def stored_by_month(market: str, root: Path, kinds) -> dict:
    """Rows per kind by month of their publication/acceptance time (events: event date)."""
    out = {}
    for kind in kinds:
        cols = PUBLIC_AT.get(kind, [])
        months: dict[str, int] = {}
        for path in sorted((root / "data" / market / kind).glob("**/*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                timestamp = (
                    as_utc_timestamp(row.get("date"))
                    if kind in ("events", "deals")
                    else public_at(kind, row)
                    if cols
                    else None
                )
                key = "unknown" if timestamp is None else f"{timestamp:%Y-%m}"
                months[key] = months.get(key, 0) + 1
        out[kind] = dict(sorted(months.items()))
    return out


def backfill(cfg: dict, source: Path, since: date, timeout: int = 3600) -> dict:
    """Copy the market's data to a scratch source and run the collectors into it from `since`."""
    market = cfg["market"]
    if market not in BACKFILL_STEPS:
        raise SystemExit(MSG_NO_BACKFILL_STEPS_FOR_MARKET.format(market=market))
    source_root = check_source(source)
    today = utc_today()
    if since >= today:
        raise SystemExit(MSG_SINCE_MUST_BE_BEFORE_TODAY)
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / SOURCE_MARKER).write_text("ai_replay backfill source (scratch; never the repo's data)\n")
    src_data = Path(paths.ROOT) / "data" / market
    if not (source_root / "data" / market).exists():
        shutil.copytree(src_data, source_root / "data" / market)
    if not (source_root / "config").exists():
        shutil.copytree(paths.CONFIG, source_root / "config")
    changed = backfill_config(source_root / "config", market, since, today)
    before = stored_by_month(market, source_root, BACKFILL_KINDS[market])
    steps = []
    for step in BACKFILL_STEPS[market]:
        script, args = step[0], [argument.format(since=since) for argument in step[1:]]
        started_at = datetime.now(timezone.utc)
        try:
            process = run_script(script, source_root, market, *args, timeout=timeout)
            code, out, err = process.returncode, json_or_text(process.stdout), process.stderr[-1500:]
        except subprocess.TimeoutExpired:
            code, out, err = None, None, f"timed out after {timeout} s"
        if isinstance(out, dict):  # keep the summary readable
            out = {key: value for key, value in out.items() if key not in ("notes",)} | (
                {"notes": out["notes"][:12]} if isinstance(out.get("notes"), list) else {}
            )
        steps.append(
            {
                "script": script,
                "args": args,
                "exit": code,
                "seconds": round((datetime.now(timezone.utc) - started_at).total_seconds()),
                "summary": out,
                "stderr_tail": err if code else "",
            }
        )
    res = {
        "step": "ai_replay.backfill",
        "market": market,
        "source": str(source_root),
        "copied_from": str(src_data),
        "since": str(since),
        "today": str(today),
        "config_overrides": changed,
        "steps": steps,
        "rows_by_public_month_before": before,
        "rows_by_public_month_after": stored_by_month(market, source_root, BACKFILL_KINDS[market]),
        "note": "each backfilled row keeps its real publication/acceptance time; first_seen_at is the "
        "backfill time, and prepare filters on the publication/acceptance time",
    }
    (source_root / f"backfill-{market}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res
