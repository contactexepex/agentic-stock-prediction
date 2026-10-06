"""backfill: a scratch source root with longer histories, filled by the collectors."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from marketbrief.core import paths
from marketbrief.core.clock import utc_today
from marketbrief.utils.timefmt import as_utc_timestamp
from marketbrief.constants.ai_replay import BACKFILL_KINDS, BACKFILL_STEPS, PUBLIC_AT, SOURCE_MARKER
from marketbrief.replay.ai_replay.copy_asof import public_at
from marketbrief.replay.ai_replay.roots import json_or_text, run_script


def check_source(source: Path) -> Path:
    """The scratch source must not be the repo, the real data/ or anything inside or above it."""
    s = source.resolve()
    for real_root in {paths.CODE.resolve(), Path(paths.ROOT).resolve()}:
        real = real_root / "data"
        if s == real_root or s == real or real in s.parents or s in real_root.parents:
            raise SystemExit(f"--source {s} is the repo, its real data/ or contains them; use a scratch directory")
    for a in [s, *s.parents]:   # any other market-brief checkout's data/ (e.g. the main clone of a worktree)
        if a.name == "data" and (a.parent / "config" / "markets").is_dir() and (a.parent / "scripts").is_dir():
            raise SystemExit(f"--source {s} is inside the real data/ of the checkout {a.parent}; use a scratch directory")
    if s.exists() and any(s.iterdir()) and not (s / SOURCE_MARKER).exists():
        raise SystemExit(f"--source {s} exists, is not empty and is not an ai_replay source; choose another path")
    return s


def backfill_config(cfg_dir: Path, market: str, since: date, today: date) -> dict:
    """Longer lookbacks in the scratch source's config copy only (never the repo's config)."""
    import yaml
    path = cfg_dir / "markets" / f"{market}.yaml"
    doc = yaml.safe_load(path.read_text())
    days = (today - since).days + 1
    changed = {}
    if doc.get("filings") == "sec":
        doc["filing_lookback_days"] = changed["filing_lookback_days"] = days
        for k in ("insiders", "stakes"):
            if k in (doc.get("relationships") or {}):
                doc["relationships"][k]["lookback_days"] = changed[f"relationships.{k}.lookback_days"] = days
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return changed


def stored_by_month(market: str, root: Path, kinds) -> dict:
    """Rows per kind by month of their publication/acceptance time (events: event date)."""
    out = {}
    for kind in kinds:
        cols = PUBLIC_AT.get(kind, [])
        months: dict[str, int] = {}
        for f in sorted((root / "data" / market / kind).glob("**/*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                t = as_utc_timestamp(r.get("date")) if kind in ("events", "deals") else public_at(kind,
                r) if cols else None
                key = "unknown" if t is None else f"{t:%Y-%m}"
                months[key] = months.get(key, 0) + 1
        out[kind] = dict(sorted(months.items()))
    return out


def backfill(cfg: dict, source: Path, since: date, timeout: int = 3600) -> dict:
    market = cfg["market"]
    if market not in BACKFILL_STEPS:
        raise SystemExit(f"no backfill steps for market {market}")
    s = check_source(source)
    today = utc_today()
    if since >= today:
        raise SystemExit("--since must be before today")
    s.mkdir(parents=True, exist_ok=True)
    (s / SOURCE_MARKER).write_text("ai_replay backfill source (scratch; never the repo's data)\n")
    src_data = Path(paths.ROOT) / "data" / market
    if not (s / "data" / market).exists():
        shutil.copytree(src_data, s / "data" / market)
    if not (s / "config").exists():
        shutil.copytree(paths.CONFIG, s / "config")
    changed = backfill_config(s / "config", market, since, today)
    before = stored_by_month(market, s, BACKFILL_KINDS[market])
    steps = []
    for step in BACKFILL_STEPS[market]:
        script, args = step[0], [a.format(since=since) for a in step[1:]]
        t0 = datetime.now(timezone.utc)
        try:
            p = run_script(script, s, market, *args, timeout=timeout)
            code, out, err = p.returncode, json_or_text(p.stdout), p.stderr[-1500:]
        except subprocess.TimeoutExpired:
            code, out, err = None, None, f"timed out after {timeout} s"
        if isinstance(out, dict):   # keep the summary readable
            out = {k: v for k, v in out.items() if k not in ("notes",)} | (
                {"notes": out["notes"][:12]} if isinstance(out.get("notes"), list) else {})
        steps.append({"script": script, "args": args, "exit": code, "seconds": round(
            (datetime.now(timezone.utc) - t0).total_seconds()), "summary": out, "stderr_tail": err if code else ""})
    res = {"step": "ai_replay.backfill", "market": market, "source": str(s), "copied_from": str(src_data),
           "since": str(since), "today": str(today), "config_overrides": changed, "steps": steps,
           "rows_by_public_month_before": before, "rows_by_public_month_after": stored_by_month(
               market, s, BACKFILL_KINDS[market]),
           "note": "each backfilled row keeps its real publication/acceptance time; first_seen_at is the "
                   "backfill time, and prepare filters on the publication/acceptance time"}
    (s / f"backfill-{market}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res
