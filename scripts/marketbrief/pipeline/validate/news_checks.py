"""News stage: source allow-list, article pages and the news analyst's enrichment file."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from marketbrief.constants.validation import ENRICH_ENUMS
from marketbrief.pipeline.validate.gate_result import Result, work_dir
from marketbrief.pipeline.validate.row_checks import check_rows, read_rows, todays_files
from marketbrief.constants.validation import (
    MSG_IDS_ALREADY_IN_NEWS_ENRICHED_E,
    MSG_IDS_ARE_NOT_NEWS_ANNOUNCEMENTS_FIRST,
    MSG_ENRICHED_FILE_PROBLEM,
    MSG_ENRICHMENT_RULE_PROBLEM,
    MSG_NEWS_ARTICLES_ROWS_BREAK_THE_ARTICLE,
    MSG_TODAYS_IDS_WITHOUT_ENRICHMENT,
    MSG_REPEATED_IDS,
)


def registrable(host: str) -> str:
    """The registrable domain (last two labels) of a host name."""
    parts = host.lower().split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "gov", "ac", "edu"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def allowed_news_sources(cfg: dict) -> tuple[set[str], dict[str, set[str]]]:
    """(domains of the Google News base, outlet name -> allowed link domains)."""
    news = cfg.get("news") or {}
    google_news = news.get("google_news") or {}
    gdom = {registrable(urlparse(google_news["base"]).hostname)} if google_news.get("base") else set()
    outlets = {}
    for outlet in news.get("outlets") or []:
        doms = {registrable(urlparse(outlet["url"]).hostname)} | {
            registrable(domain) for domain in outlet.get("link_domains") or []
        }
        outlets[outlet["name"]] = doms
    return gdom, outlets


def check_news_sources(res: Result, cfg: dict, con, today: date):
    """Today's news rows come from allow-listed sources."""
    gdom, outlets = allowed_news_sources(cfg)
    rows = con.execute(
        "SELECT id, url, feed, tickers FROM news WHERE CAST(first_seen_at AS DATE) = ?", [today]
    ).fetchall()
    bad = []
    for nid, url, feed, tickers in rows:
        parsed_url = urlparse(url or "")
        dom = registrable(parsed_url.hostname or "")
        if parsed_url.scheme != "https":
            bad.append((nid, f"scheme {parsed_url.scheme or 'none'}", tickers))
        elif str(feed).startswith("gnews:"):
            if dom not in gdom:
                bad.append((nid, f"Google News feed but link domain {dom}", tickers))
        elif feed in outlets:
            if dom not in outlets[feed]:
                bad.append((nid, f"outlet {feed} but link domain {dom} (allowed {sorted(outlets[feed])})", tickers))
        else:
            bad.append((nid, f"feed {feed!r} is not a configured outlet", tickers))
    if bad:
        res.block(
            "NEWS_SOURCE",
            f"{len(bad)} news rows from unconfigured sources or not https, e.g. "
            + "; ".join(f"{index}: {source}" for index, source, _ in bad[:5]),
            [tag for *_, ts_ in bad for tag in (ts_ or []) if tag in cfg["tickers"]],
        )


def check_articles(res: Result, cfg: dict, today: date):
    """news_articles written today (collect_articles.py): a known access value, no stored article
    text (extract: at most 3 sentences of at most 40 words), and a page read only from an
    allowlisted https:// URL (config/news_sources.yaml)."""
    from marketbrief.analytics.article_pages import url_check
    from marketbrief.analytics.news_sources import load_sources
    from marketbrief.constants.articles import ACCESS

    src, bad = load_sources(), []
    for path in todays_files(cfg["market"], "news_articles", today):
        for row in read_rows(path)[0]:
            ext = row.get("extract") or []
            if row.get("access") not in ACCESS:
                bad.append(f"{row.get('id')}: access {row.get('access')!r}")
            elif len(ext) > 3 or any(len(str(extractor).split()) > 40 for extractor in ext):
                bad.append(f"{row.get('id')}: extract longer than 3 sentences of 40 words")
            elif (
                row["access"] in ("full", "partial", "paywalled")
                and row.get("http_status") is not None
                and not url_check(row.get("final_url"), src)[0]
            ):
                bad.append(
                    f"{row.get('id')}: read from a URL that is not an allowlisted https page "
                    f"({str(row.get('final_url'))[:60]})"
                )
            elif row["access"] in ("skipped_unlisted", "undecoded") and row.get("http_status") is not None:
                bad.append(f"{row.get('id')}: access {row['access']} but an HTTP status is stored")
    if bad:
        res.warn("ARTICLE_ROWS", MSG_NEWS_ARTICLES_ROWS_BREAK_THE_ARTICLE.format(count=len(bad), value=bad[:3]))


def todays_new_ids(con, today) -> set[str]:
    """Ids of the news and announcements first seen today (the ones that need an enrichment)."""
    new_ids = {
        row[0] for row in con.execute("SELECT id FROM news WHERE CAST(first_seen_at AS DATE) = ?", [today]).fetchall()
    }
    new_ids |= {
        row[0]
        for row in con.execute("SELECT id FROM announcements WHERE CAST(first_seen_at AS DATE) = ?", [today]).fetchall()
    }
    return new_ids


def enrichment_rule_problems(row: dict) -> list[str]:
    """Rule problems of one news_enriched record: score ranges, enumerations, summary length, required fields."""
    why = []
    for key, lower, upper in (("relevance", 0, 1), ("sentiment", -1, 1), ("novelty", 0, 1)):
        value = row.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not lower <= value <= upper:
            why.append(f"{key} {value!r} not in {lower}..{upper}")
    why += [
        f"{key} {row.get(key)!r} not one of {sorted(allowed)}"
        for key, allowed in ENRICH_ENUMS.items()
        if row.get(key) not in allowed
    ]
    if not isinstance(row.get("summary"), str) or len(row["summary"].split()) > 25:
        why.append("summary missing or over 25 words")
    if not row.get("prompt_version"):
        why.append("prompt_version missing")
    if not row.get("analyzed_at"):
        why.append("analyzed_at missing")
    return why


def stage_news(  # noqa: PLR0913 (uniform stage signature)
    res, _cfg, con, _status, now, today, validate_config, path: Path | None = None
):
    """News stage: the news analyst's enrichment file against the rules."""
    path = path or work_dir() / "enriched.jsonl"
    if not path.exists():
        res.info["news"] = "no work/enriched.jsonl"
        return
    rows, problems = read_rows(path) if path.stat().st_size else ([], [])
    if problems:
        res.block("BAD_FILE", MSG_ENRICHED_FILE_PROBLEM.format(name=path.name, value="; ".join(problems[:3])))
    bad = check_rows("news_enriched", rows, False, now, timedelta(minutes=validate_config["future_tolerance_minutes"]))
    if bad:
        res.block("SCHEMA", MSG_ENRICHED_FILE_PROBLEM.format(name=path.name, value="; ".join(bad)))
    new_ids = todays_new_ids(con, today)
    done = {row[0] for row in con.execute("SELECT DISTINCT id FROM news_enriched").fetchall()}
    ids = [row.get("id") for row in rows]
    dup = sorted({index for index in ids if ids.count(index) > 1})
    if dup:
        res.block("DUPLICATE_ID", MSG_REPEATED_IDS.format(name=path.name, value=dup[:5]))
    extra = sorted({index for index in ids if index not in new_ids})
    if extra:
        res.block(
            "ENRICH_UNKNOWN_ID", MSG_IDS_ARE_NOT_NEWS_ANNOUNCEMENTS_FIRST.format(count=len(extra), value=extra[:5])
        )
    again = sorted({index for index in ids if index in done})
    if again:
        res.block("ENRICH_ALREADY_STORED", MSG_IDS_ALREADY_IN_NEWS_ENRICHED_E.format(count=len(again), value=again[:5]))
    missing = sorted(new_ids - done - set(ids))
    if missing:
        res.warn("ENRICH_MISSING", MSG_TODAYS_IDS_WITHOUT_ENRICHMENT.format(count=len(missing), value=missing[:5]))
    for row in rows:
        why = enrichment_rule_problems(row)
        if why:
            res.block("ENRICH_RULE", MSG_ENRICHMENT_RULE_PROBLEM.format(record_id=row.get("id"), value="; ".join(why)))
    res.info["news"] = {"records": len(rows), "new_ids_today": len(new_ids)}
