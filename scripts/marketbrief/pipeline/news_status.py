"""Verification status of news events (news verification phase B, docs/DESIGN.md section 3b). Run after
claims.py add; reads only what was available at the run's time (MB_NOW in a replay):
- clusters: news_clusters_asof(now) with an item reported in the last `lookback_hours`;
- claims: news_claims with extracted_at <= now and source_available_at <= now (an article fetched,
  a filing accepted and its text stored, an NSE announcement disseminated by then).
Status rules are in marketbrief/analytics/verification_status.py. Appends to data/<market>/news_verified/
one row per cluster (level cluster) and per fact (level claim) when new or changed since its last
stored row; as_of = now and every input is <= inputs_until <= as_of. Read the state at a time with
news_verified_asof(ts) and each news id's status with news_status_ids_asof(ts) (sql/views.sql).
Prints a JSON summary with the number of events and facts per status."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

import pandas as pd

from marketbrief.analytics.news_sources import load_sources
from marketbrief.analytics.verification_status import cluster_status
from marketbrief.constants.verification import (
    KIND_NEWS_VERIFIED,
    LEVEL_CLAIM,
    LEVEL_CLUSTER,
    METHOD_VERSION_STATUS,
    STATUS_PRECEDENCE,
)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.pipeline.claim_sources import clean_row, current_clusters, iso

CLAIMS_SQL = """
SELECT DISTINCT ON (id) * FROM news_claims
WHERE list_contains(?, cluster_id) AND extracted_at <= ?::TIMESTAMPTZ AND source_available_at <= ?::TIMESTAMPTZ
ORDER BY id, extracted_at"""
STORED_SQL = """
SELECT DISTINCT ON (cluster_id, coalesce(claim_id, '')) cluster_id, coalesce(claim_id, '') AS claim, state_hash
FROM news_verified WHERE as_of <= ?::TIMESTAMPTZ ORDER BY cluster_id, coalesce(claim_id, ''), as_of DESC, id"""
HASHED = (
    "cluster_row_id",
    "status",
    "primary_ids",
    "outlet_ids",
    "mismatch_ids",
    "status_ids",
    "id_statuses",
    "independent_origins",
    "unread_vetted_origins",
    "origins",
    "conflicts",
    "flags",
    "confirmed_at",
)


def statements_by_cluster(con, cluster_ids: list[str], now: pd.Timestamp) -> dict[str, list[dict]]:
    """Claims available by now, per cluster, with timestamps as ISO text."""
    out: dict[str, list[dict]] = {}
    rows = con.execute(CLAIMS_SQL, [cluster_ids, now.isoformat(), now.isoformat()]).df().to_dict("records")
    for row in rows:
        row = clean_row(row)
        for key in ("source_available_at", "source_published_at", "extracted_at"):
            row[key] = iso(row.get(key))
        out.setdefault(row["cluster_id"], []).append(row)
    return out


def state_hash(row: dict) -> str:
    """A hash of the fields that define a status row's state."""
    return hashlib.sha1(json.dumps({k: row[k] for k in HASHED}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def status_rows(cluster: dict, statements: list[dict], as_of: pd.Timestamp) -> list[dict]:
    """The cluster's status row and one row per fact."""
    result, facts = cluster_status(cluster, statements)
    stamp = f"{as_of:%Y%m%dT%H%M%SZ}"
    inputs = [iso(cluster["inputs_until"]) or iso(cluster["as_of"])]
    inputs += [time for s in statements for time in (s["extracted_at"], s["source_available_at"]) if time]
    common = {
        "as_of": as_of.isoformat(),
        "cluster_id": cluster["cluster_id"],
        "cluster_row_id": cluster["id"],
        "ticker": cluster["ticker"],
        "independent_origins": cluster["independent_origins"],
        "unread_vetted_origins": cluster["unread_vetted_origins"],
        "first_reported_at": iso(cluster["first_reported_at"]),
        "inputs_until": max(inputs),
        "method_version": METHOD_VERSION_STATUS,
    }
    ids = sorted(result["ids"])
    rows = [
        {
            "id": f"{cluster['cluster_id']}|*@{stamp}",
            **common,
            "claim_id": None,
            "level": LEVEL_CLUSTER,
            "status": result["status"],
            "primary_ids": result["primary_ids"],
            "outlet_ids": result["outlet_ids"],
            "mismatch_ids": result["mismatch_ids"],
            "status_ids": ids,
            "id_statuses": [result["ids"][i] for i in ids],
            "origins": list(cluster.get("origins") or []),
            "conflicts": result["conflicts"],
            "flags": result["flags"],
            "confirmed_at": result["confirmed_at"],
        }
    ]
    for key, fact in facts.items():
        rows.append(
            {
                "id": f"{cluster['cluster_id']}|{key}@{stamp}",
                **common,
                "claim_id": key,
                "level": LEVEL_CLAIM,
                "status": fact["status"],
                "primary_ids": fact["primary_ids"],
                "outlet_ids": fact["outlet_ids"],
                "mismatch_ids": fact["mismatch_ids"],
                "status_ids": [],
                "id_statuses": [],
                "origins": fact["origins"],
                "conflicts": fact["conflicts"],
                "flags": fact["flags"],
                "confirmed_at": fact["confirmed_at"],
            }
        )
    for row in rows:
        row["state_hash"] = state_hash(row)
    return rows


def run(cfg: dict) -> dict:
    """Compute and append the run's status rows; returns the JSON summary."""
    market = cfg["market"]
    as_of = pd.Timestamp(clock()).floor("s")
    lookback = float(load_sources().clusters.get("lookback_hours", 144))
    con = connect(market)
    clusters = [c for c in current_clusters(con, as_of, lookback) if c["ticker"] in cfg["tickers"]]
    claims = statements_by_cluster(con, [c["cluster_id"] for c in clusters], as_of)
    stored = {(c, k): h for c, k, h in con.execute(STORED_SQL, [as_of.isoformat()]).fetchall()}
    rows, current = [], []
    for cluster in clusters:
        for row in status_rows(cluster, claims.get(cluster["cluster_id"], []), as_of):
            current.append(row)
            if stored.get((row["cluster_id"], row["claim_id"] or "")) != row["state_hash"]:
                rows.append(row)
    written = append_jsonl(day_file(market, KIND_NEWS_VERIFIED, utc_today()), rows) if rows else 0
    order = {s: i for i, s in enumerate(STATUS_PRECEDENCE)}

    def counts(level: str) -> dict:
        """The number of rows of each status at one level, in status precedence order."""
        found = Counter(r["status"] for r in current if r["level"] == level)
        return dict(sorted(found.items(), key=lambda kv: order[kv[0]]))

    return {
        "step": "news_status",
        "market": market,
        "as_of": as_of.isoformat(),
        "clusters": len(clusters),
        "claims": sum(len(v) for v in claims.values()),
        "events_by_status": counts(LEVEL_CLUSTER),
        "facts_by_status": counts(LEVEL_CLAIM),
        "written": written,
        "unchanged": len(current) - len(rows),
        "flags": dict(
            Counter(flag for r in current if r["level"] == LEVEL_CLUSTER for flag in r["flags"]).most_common()
        ),
    }


def main() -> int:
    """Print the JSON summary of one run."""
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps(run(cfg), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
