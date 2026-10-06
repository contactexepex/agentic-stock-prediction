"""Second-order news: articles that name an entity linked to a watchlist company."""
from __future__ import annotations

import re
from datetime import date, timedelta
from marketbrief.core.clock import utc_today
from marketbrief.graph.connection_map import MIN_NAME, load_edges, status


def name_patterns(edges: list[dict]) -> list[tuple[dict, re.Pattern]]:
    """A compiled name pattern for each edge's target and aliases."""
    out = []
    for edge in edges:
        names = [name for name in {edge["target"], *(edge.get("aliases") or [])} if len(name) >= MIN_NAME]
        if names:
            out.append(
                (
                    edge,
                    re.compile(
                        r"(?<!\w)(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")(?!\w)", re.I
                    ),
                )
            )
    return out


def hits(_cfg: dict, con, days: int = 1, today: date | None = None) -> list[dict]:
    """Second-order news: an article that names a linked entity (or is tagged with a linked
    watchlist ticker) but is not itself tagged with the ticker. One row per (ticker, article)."""
    edges = load_edges(con)
    if not edges:
        return []
    since = (today or utc_today()) - timedelta(days=days)
    news = con.execute(
        """
        SELECT n.id, n.title, n.source, n.tickers, CAST(coalesce(n.published_at, n.first_seen_at) AS DATE) AS day,
               e.sentiment, e.materiality
        FROM (SELECT DISTINCT ON (id) * FROM news ORDER BY id, first_seen_at) n
        LEFT JOIN enriched_latest e USING (id)
        WHERE CAST(coalesce(n.published_at, n.first_seen_at) AS DATE) >= ?""",
        [since],
    ).fetchall()
    pats = name_patterns(edges)
    found: dict[tuple[str, str], dict] = {}
    for nid, title, source, tagged, day, sentiment, materiality in news:
        tagged = set(tagged or [])
        for edge, pat in pats:
            match = pat.search(title or "")
            via_ticker = edge.get("target_ticker") and edge["target_ticker"] in tagged
            if edge["ticker"] in tagged or not (match or via_ticker):
                continue
            key = (edge["ticker"], nid)
            link = f"{edge['relation']}: {edge['target']}"
            if key in found:
                if link not in found[key]["via"]:
                    found[key]["via"].append(link)
                continue
            found[key] = {
                "ticker": edge["ticker"],
                "via": [link],
                "news_id": nid,
                "day": str(day),
                "title": title,
                "source": source,
                "sentiment": sentiment,
                "materiality": materiality,
            }
    return sorted(found.values(), key=lambda hit: (hit["ticker"], hit["day"], hit["news_id"]))


def context_section(cfg: dict, con, days: int = 1, limit: int = 40) -> tuple[str, str]:
    """('Connections ...', markdown) for context.py."""
    map_status = status(cfg, con)
    title = f"Connections: second-order news, last {days} day(s) (news about a linked company or person)"
    if not map_status["edges"]:
        return title, "_no connection map yet (graph-builder runs monthly)_\n"
    rows = hits(cfg, con, days)
    head = (
        f"Map: {map_status['edges']} edges, last changed {str(map_status['last_added_at'])[:10]}"
        f"{', refresh due' if map_status['refresh_due'] else ''}.\n\n"
    )
    if not rows:
        return title, head + "_none_\n"
    clean = lambda status_text: str(status_text).replace("|", "/")  # noqa: E731
    body = "| ticker | via | news_id | day | title | sentiment |\n|---|---|---|---|---|---|\n"
    body += "".join(
        f"| {hit['ticker']} | {clean('; '.join(hit['via']))} | {hit['news_id']} | {hit['day']} | "
        f"{clean(hit['title'])} | {'' if hit['sentiment'] is None else round(hit['sentiment'], 2)} |\n"
        for hit in rows[:limit]
    )
    if len(rows) > limit:
        body += f"\n_{len(rows) - limit} more: `python scripts/graph.py hits`_\n"
    return title, head + body
