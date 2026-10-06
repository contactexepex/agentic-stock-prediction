"""Batch sizes, labels, indexes and the kinds not projected of the Neo4j sync."""

from __future__ import annotations


BATCH_SIZE = 500

OVERLAP_DAYS = 3  # incremental re-reads this much before the watermark (re-upserts are harmless)

DELETE_BATCH = 5000

SCHEMA_VERSION = "neo4j-v1"

LABELS = (
    "Market",
    "Sector",
    "Company",
    "Holder",
    "Source",
    "Event",
    "Prediction",
    "Range",
    "Outcome",
    "RegimeDay",
    "FeatureDay",
    "Judgment",
    "FinancialPeriod",
    "FlowDay",
    "SyncState",
)

REL_ID_TYPES = ("TRADED", "HOLDS", "CONNECTED_TO")

INDEXES = [
    ("Company", "ticker"),
    ("Company", "market"),
    ("Holder", "market"),
    ("Source", "market"),
    ("Event", "market"),
    ("Event", "date"),
    ("Prediction", "market"),
    ("Range", "market"),
    ("Outcome", "market"),
    ("SyncState", "market"),
]

PERSON_CATEGORIES = ("director", "key managerial", "kmp", "designated", "employee", "relative")

NOT_PROJECTED = {
    "prices": "daily bars stay in DuckDB (FeatureDay nodes carry each day's close and indicators)",
    "price_sources": "provenance of bars filled from another source (view bar_sources), DuckDB only",
    "adjustments": "split/bonus factors applied on read to the bars (views ohlc, bars), DuckDB only",
    "quotes": "intraday snapshots, operational",
    "options": "implied-vol snapshots, operational",
    "calibration": "range-engine internals",
    "delivery": "per-session time series (context only)",
    "reviews": "nested JSON tables; the review report is in reports/",
    "graph_runs": "refresh bookkeeping",
    "news_enriched": "merged into NewsItem / Announcement and MENTIONS (latest analysis wins)",
    "news_articles": "article metadata, extracts and copy signatures (verification inputs), DuckDB only",
    "news_clusters": "per-run cluster snapshots read as of a time (news_clusters_asof), DuckDB only",
    "news_claims": "claim statements quoted from articles and filings (verification inputs), DuckDB only",
    "news_verified": "per-run verification status snapshots read as of a time (news_verified_asof), DuckDB only",
    "primary_texts": "plain text of SEC filing documents quoted by claims, DuckDB only",
}

WATERMARK_STATEMENT = (
    "MERGE (s:SyncState {id: $id}) SET s.market = $market, s.kind = $kind, "
    "s.watermark = $watermark, s.rows = $n, s.synced_at = datetime($synced_at)"
)

# ---------- messages ----------
MSG_NEO4J_READ_FAILED = "read: {error}"
MSG_NEO4J_WATERMARK_FAILED = "watermark: {error}"
