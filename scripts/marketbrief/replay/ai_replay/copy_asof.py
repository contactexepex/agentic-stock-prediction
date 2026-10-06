"""Copy of the stored data as of a cutoff: publication-time rules per kind, rows kept or dropped."""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
import pandas as pd
from marketbrief.core.schemas import ACCEPTED_KEYS, SCHEMAS
from marketbrief.utils.timefmt import as_utc_timestamp
from marketbrief.constants.ai_replay import DATE_PUBLIC_AFTER_CLOSE, DROPPED, PUBLIC_AT, TARGET_DATE_KINDS


def public_at(kind: str, row: dict) -> pd.Timestamp | None:
    for col in PUBLIC_AT.get(kind, []):
        if col.endswith("+1d"):
            t = as_utc_timestamp(row.get(col[:-3]))
            if t is not None:
                return t.normalize() + pd.Timedelta(days=1)
        else:
            t = as_utc_timestamp(row.get(col))
            if t is not None:
                return t
    return None


def load_sec_times(base: Path) -> dict[str, str]:
    """Accession -> SGML-header acceptance time (newest check wins) from data/<market>/sec_times/,
    the correction connect applies to accepted_at (see marketbrief/sources/sec_filings.py)."""
    best: dict[str, tuple[str, str]] = {}
    for f in sorted((base / "sec_times").glob("**/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            acc, at, checked = r.get("accession"), r.get("accepted_at"), str(r.get("checked_at") or "")
            if acc and at and (acc not in best or checked >= best[acc][1]):
                best[acc] = (at, checked)
    return {a: at for a, (at, _) in best.items()}


def keep_row(kind: str, row: dict, d: date, cutoff: pd.Timestamp, times: dict[str, str] | None = None) -> bool:
    """True when the row was public by the cutoff (pre-open of the session after d). `times`
    (load_sec_times) replaces a SEC row's stored accepted_at with its header time, as the
    corrected views do: a value stored from a shifted submissions file is 4-5h late."""
    if times and kind in ACCEPTED_KEYS and row.get(ACCEPTED_KEYS[kind]) in times:
        row = {**row, "accepted_at": times[row[ACCEPTED_KEYS[kind]]]}
    if kind in ("prices", "price_sources"):   # a bar and its provenance row share the bar date
        t = as_utc_timestamp(row.get("date"))
        return t is not None and t.date() <= d
    if kind == "adjustments":   # a split/bonus applies to the root's bars only from its ex-date
        t = as_utc_timestamp(row.get("ex_date"))
        return t is not None and t.date() <= d
    if kind in DATE_PUBLIC_AFTER_CLOSE:
        t = as_utc_timestamp(row.get("date"))
        return t is not None and t.date() <= d
    if kind == "events":
        seen = as_utc_timestamp(row.get("first_seen_at"))
        if seen is not None and seen <= cutoff:
            return True
        day = as_utc_timestamp(row.get("date"))
        return str(row.get("source") or "").endswith("_history") and day is not None and day.date() <= d
    t = public_at(kind, row)
    if t is None or t > cutoff:
        return False
    if kind in TARGET_DATE_KINDS:
        td = as_utc_timestamp(row.get("target_date"))
        return td is not None and td.date() <= d
    return True


def rule_text(kind: str) -> str:
    if kind in ("prices", "price_sources"):
        return "bar date <= D"
    if kind == "adjustments":
        return "ex_date <= D (detected_at ignored: see the docstring)"
    if kind in DATE_PUBLIC_AFTER_CLOSE:
        return "trade date <= D (assumed: NSE publishes the day's deals after the close)"
    if kind == "events":
        return "first_seen_at <= cutoff, or a backfilled past event (*_history) dated <= D"
    cols = " else ".join(c.replace("+1d", " (end of day UTC)") for c in PUBLIC_AT[kind])
    extra = " and target_date <= D" if kind in TARGET_DATE_KINDS else ""
    if kind in ACCEPTED_KEYS:
        cols = cols.replace("accepted_at", "accepted_at (SGML header time from sec_times when checked)", 1)
    return f"{cols} <= cutoff{extra}"


def filter_jsonl_rows(text: str, kind: str, d: date, cutoff: pd.Timestamp,
                  times: dict[str, str] | None = None) -> tuple[list[str], int]:
    kept, n = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        n += 1
        if keep_row(kind, json.loads(line), d, cutoff, times):
            kept.append(line)
    return kept, n


def filter_csv_rows(text: str, kind: str, d: date, cutoff: pd.Timestamp,
                times: dict[str, str] | None = None) -> tuple[list[str], int]:
    lines = text.splitlines()
    if not lines:
        return [], 0
    header = next(csv.reader([lines[0]]))
    kept, n = [], 0
    for line in lines[1:]:
        if not line.strip():
            continue
        n += 1
        if keep_row(kind, dict(zip(header, next(csv.reader([line])))), d, cutoff, times):
            kept.append(line)
    return ([lines[0]] + kept if kept else []), n


def earliest_news(src_market: Path) -> str | None:
    files = sorted((src_market / "news").glob("**/*.jsonl"))
    return files[0].stem if files else None


def copy_asof(market: str, src: Path, dst: Path, d: date, cutoff: datetime) -> dict:
    """Copy src/data/<market>/ into dst/data/<market>/, keeping only rows public by the cutoff."""
    cut = pd.Timestamp(cutoff)
    base, out_base = src / "data" / market, dst / "data" / market
    kinds, excluded = {}, {}
    first_news = earliest_news(base) or "none stored"
    times = load_sec_times(base)       # SEC accepted_at corrected to the header time (sec_times)
    for kdir in sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []:
        kind = kdir.name
        if kind in DROPPED:
            excluded[kind] = DROPPED[kind].format(first=first_news)
            continue
        if kind not in ("prices", "price_sources", "adjustments", "events", *DATE_PUBLIC_AFTER_CLOSE) \
                and kind not in PUBLIC_AT:
            excluded[kind] = "no known publication-time rule for this kind"
            continue
        ext = SCHEMAS[kind][0] if kind in SCHEMAS else "jsonl"
        stat = {"rule": rule_text(kind), "files_in": 0, "files_out": 0, "rows_in": 0, "rows_kept": 0}
        for f in sorted(kdir.glob(f"**/*.{ext}")):
            text = f.read_text(encoding="utf-8")
            kept, n = (filter_csv_rows if ext == "csv" else filter_jsonl_rows)(text, kind, d, cut, times)
            stat["files_in"] += 1
            stat["rows_in"] += n
            rows = len(kept) - (1 if ext == "csv" and kept else 0)
            stat["rows_kept"] += rows
            if rows:
                out = out_base / f.relative_to(base)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(kept) + "\n", encoding="utf-8")
                stat["files_out"] += 1
        stat["rows_dropped"] = stat["rows_in"] - stat["rows_kept"]
        kinds[kind] = stat
    for kind in DROPPED:
        excluded.setdefault(kind, DROPPED[kind].format(first=first_news))
    return {"kinds": kinds, "excluded": excluded, "first_news_file": first_news}
