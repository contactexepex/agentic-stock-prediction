"""Shared paths, schemas and DuckDB setup for the market-brief pipeline.

Each market (config/markets/<market>.yaml) has its own data tree: append-only,
date-partitioned files under data/<market>/<kind>/YYYY/MM/. DuckDB reads those files
directly, so any time window is just a SQL query. Scripts take --market (or MB_MARKET).
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import yaml

CODE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("MB_ROOT", CODE))
CONFIG = Path(os.environ.get("MB_CONFIG", CODE / "config"))

# Indicator columns written by features.py (formulas in indicators.py).
FEATURE_COLS: dict[str, str] = {
    "close": "DOUBLE", "bars": "INTEGER",
    "ret_1d": "DOUBLE", "ret_3d": "DOUBLE", "ret_5d": "DOUBLE", "ret_20d": "DOUBLE",
    "ema_ratio": "DOUBLE", "rsi_14": "DOUBLE", "roc_10": "DOUBLE", "price_vs_20d_high": "DOUBLE",
    "atr_14": "DOUBLE", "atr_pct": "DOUBLE", "realized_vol_10d": "DOUBLE", "ewma_vol": "DOUBLE",
    "bb_width": "DOUBLE", "obv_trend": "DOUBLE", "volume_ratio_20d": "DOUBLE",
    "beta_1y": "DOUBLE", "rel_sector_5d": "DOUBLE", "cue_change_pct": "DOUBLE",
    "days_to_earnings": "INTEGER", "ex_dividend_date": "DATE",
    "quality": "VARCHAR", "warnings": "VARCHAR[]",
}

# kind -> (file extension, column types). This is the single source of truth for schemas.
SCHEMAS: dict[str, tuple[str, dict[str, str]]] = {
    "news": ("jsonl", {
        "id": "VARCHAR", "title": "VARCHAR", "url": "VARCHAR", "source": "VARCHAR",
        "published_at": "TIMESTAMPTZ", "first_seen_at": "TIMESTAMPTZ",
        "feed": "VARCHAR", "category": "VARCHAR", "tickers": "VARCHAR[]",
    }),
    "news_enriched": ("jsonl", {
        "id": "VARCHAR", "analyzed_at": "TIMESTAMPTZ", "relevance": "DOUBLE",
        "sentiment": "DOUBLE", "novelty": "DOUBLE", "materiality": "VARCHAR",
        "event_type": "VARCHAR", "urgency": "VARCHAR", "geopolitical": "BOOLEAN",
        "priced_in": "BOOLEAN", "summary": "VARCHAR", "prompt_version": "VARCHAR",
    }),
    "filings": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "cik": "VARCHAR", "form": "VARCHAR",
        "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ", "description": "VARCHAR",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "predictions": ("jsonl", {
        "id": "VARCHAR", "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "ticker": "VARCHAR",
        "horizon_days": "INTEGER", "direction": "VARCHAR", "confidence": "DOUBLE",
        "rationale": "VARCHAR", "evidence_ids": "VARCHAR[]", "prompt_version": "VARCHAR",
        "range_widen": "DOUBLE",
    }),
    "outcomes": ("jsonl", {
        "prediction_id": "VARCHAR", "scored_at": "TIMESTAMPTZ", "base_date": "DATE",
        "base_close": "DOUBLE", "target_date": "DATE", "target_close": "DOUBLE",
        "actual_return": "DOUBLE", "hit": "BOOLEAN",
    }),
    "prices": ("csv", {
        "date": "DATE", "ticker": "VARCHAR", "open": "DOUBLE", "high": "DOUBLE",
        "low": "DOUBLE", "close": "DOUBLE", "adj_close": "DOUBLE", "volume": "BIGINT",
        "collected_at": "TIMESTAMPTZ",
    }),
    "quotes": ("jsonl", {
        "symbol": "VARCHAR", "yahoo": "VARCHAR", "ts": "TIMESTAMPTZ", "price": "DOUBLE",
        "prev_close": "DOUBLE", "change_pct": "DOUBLE", "collected_at": "TIMESTAMPTZ",
    }),
    "events": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "type": "VARCHAR", "ticker": "VARCHAR",
        "name": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "features": ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "ticker": "VARCHAR", "computed_at": "TIMESTAMPTZ",
        **FEATURE_COLS,
    }),
    "ranges": ("jsonl", {
        "id": "VARCHAR", "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "session_date": "DATE",
        "target_date": "DATE", "ticker": "VARCHAR", "horizon_days": "INTEGER",
        "base_close": "DOUBLE", "center": "DOUBLE", "sigma_h": "DOUBLE",
        "lo50": "DOUBLE", "hi50": "DOUBLE", "lo80": "DOUBLE", "hi80": "DOUBLE",
        "naive_lo50": "DOUBLE", "naive_hi50": "DOUBLE", "naive_lo80": "DOUBLE", "naive_hi80": "DOUBLE",
        "direction": "VARCHAR", "confidence": "DOUBLE", "regime": "VARCHAR",
        "calibration_id": "VARCHAR", "notes": "VARCHAR[]",
    }),
    "range_outcomes": ("jsonl", {
        "range_id": "VARCHAR", "scored_at": "TIMESTAMPTZ", "target_date": "DATE",
        "actual_close": "DOUBLE", "z": "DOUBLE", "hit50": "BOOLEAN", "hit80": "BOOLEAN",
        "naive_hit50": "BOOLEAN", "naive_hit80": "BOOLEAN", "is80_pct": "DOUBLE",
        "naive_is80_pct": "DOUBLE", "width80_pct": "DOUBLE", "naive_width80_pct": "DOUBLE",
        "center_err_pct": "DOUBLE", "naive_center_err_pct": "DOUBLE",
    }),
    "calibration": ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "computed_at": "TIMESTAMPTZ", "horizon_days": "INTEGER",
        "q10": "DOUBLE", "q25": "DOUBLE", "q75": "DOUBLE", "q90": "DOUBLE",
        "n_history": "INTEGER", "n_live": "INTEGER", "source": "VARCHAR",
    }),
    "regime": ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "session_date": "DATE", "computed_at": "TIMESTAMPTZ",
        "regime": "VARCHAR",
        "vol_level": "DOUBLE", "vol_change_1d": "DOUBLE", "bench_ret_5d": "DOUBLE",
        "bench_vol_10d": "DOUBLE", "major_event": "BOOLEAN", "major_event_names": "VARCHAR[]",
        "stress": "BOOLEAN", "notes": "VARCHAR[]",
    }),
}

# Relationships (docs/DESIGN.md phase 5), US from SEC EDGAR: one row per Form 4 transaction
# line (insiders), per Schedule 13D/13G filing (stakes), per 13F filing x watchlist ticker (holdings).
SCHEMAS.update({
    "insiders": ("jsonl", {
        "id": "VARCHAR", "accession": "VARCHAR", "line": "INTEGER", "ticker": "VARCHAR",
        "issuer_cik": "VARCHAR", "form": "VARCHAR", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ",
        "insider_name": "VARCHAR", "insider_cik": "VARCHAR", "role": "VARCHAR",
        "is_director": "BOOLEAN", "is_officer": "BOOLEAN", "is_ten_pct_owner": "BOOLEAN",
        "derivative": "BOOLEAN", "security": "VARCHAR", "transaction_date": "DATE", "code": "VARCHAR",
        "acquired_disposed": "VARCHAR", "shares": "DOUBLE", "price": "DOUBLE", "value": "DOUBLE",
        "shares_after": "DOUBLE", "ownership": "VARCHAR", "plan_10b5_1": "BOOLEAN",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "stakes": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "issuer_cik": "VARCHAR", "form": "VARCHAR",
        "kind": "VARCHAR", "amendment": "BOOLEAN", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ",
        "event_date": "DATE", "filer_name": "VARCHAR", "filer_cik": "VARCHAR",
        "reporting_persons": "VARCHAR[]", "percent": "DOUBLE", "shares": "DOUBLE",
        "purpose": "VARCHAR", "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "holdings": ("jsonl", {
        "id": "VARCHAR", "accession": "VARCHAR", "filer_cik": "VARCHAR", "filer_name": "VARCHAR",
        "period": "DATE", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ", "ticker": "VARCHAR",
        "cusip": "VARCHAR", "issuer_name": "VARCHAR", "shares": "DOUBLE", "value_usd": "DOUBLE",
        "put_call": "VARCHAR", "n_lines": "INTEGER", "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "report_type": "VARCHAR", "complete": "BOOLEAN", "note": "VARCHAR",
    }),
})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


# ---------- markets ----------

def load_ranges_config() -> dict:
    return yaml.safe_load((CONFIG / "ranges.yaml").read_text())


def market_names() -> list[str]:
    return sorted(p.stem for p in (CONFIG / "markets").glob("*.yaml"))


def load_market(name: str) -> dict:
    path = CONFIG / "markets" / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"unknown market {name!r}; available: {market_names()}")
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault("market", name)
    cfg.setdefault("symbols", {})
    for key, meta in cfg["tickers"].items():
        meta.setdefault("yahoo", key)
    for key, meta in cfg["symbols"].items():
        meta.setdefault("yahoo", key)
    sector_of = {t: s for s, ts in cfg.get("sectors", {}).items() for t in ts}
    for key, meta in cfg["tickers"].items():
        meta.setdefault("sector", sector_of.get(key))
    return cfg


def market_arg(description: str | None = None) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--market", default=os.environ.get("MB_MARKET"),
                    help="market config name, e.g. india or us (default: $MB_MARKET)")
    return ap


def require_market(args) -> dict:
    if not args.market:
        raise SystemExit(f"--market is required; available: {market_names()}")
    return load_market(args.market)


def symbols_by_role(cfg: dict, role: str) -> dict[str, dict]:
    return {k: v for k, v in cfg["symbols"].items() if v.get("role") == role}


def benchmark_key(cfg: dict) -> str | None:
    return next(iter(symbols_by_role(cfg, "benchmark")), None)


def vol_index_key(cfg: dict) -> str | None:
    return next(iter(symbols_by_role(cfg, "vol_index")), None)


# ---------- files ----------

def data_dir(market: str) -> Path:
    return ROOT / "data" / market


def day_file(market: str, kind: str, day: date, ext: str | None = None) -> Path:
    ext = ext or SCHEMAS[kind][0]
    path = data_dir(market) / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, rows) -> int:
    """Append rows; never rewrites existing lines."""
    rows = list(rows)
    if rows:
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def recent_ids(market: str, kind: str, days: int, key: str = "id") -> set[str]:
    """Ids seen in the last `days` daily files of a kind (for de-duplication)."""
    ids: set[str] = set()
    files = sorted((data_dir(market) / kind).glob("**/*.jsonl"))[-days:]
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)[key])
    return ids


def connect(market: str) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with one view per data kind plus the derived views in sql/views.sql."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    base = data_dir(market)
    for name, (ext, cols) in SCHEMAS.items():
        has_files = any((base / name).glob(f"**/*.{ext}"))
        col_spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"
        if has_files:
            pattern = (base / name).as_posix() + f"/**/*.{ext}"
            if ext == "jsonl":
                src = f"read_json('{pattern}', format='newline_delimited', columns={col_spec})"
            else:
                src = f"read_csv('{pattern}', header=true, columns={col_spec})"
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM {src}")
        else:
            con.execute(f"CREATE TABLE {name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
    con.execute((CODE / "sql" / "views.sql").read_text())
    return con


def md_table(cursor) -> str:
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out) + "\n"
