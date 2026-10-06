"""News stage: source allow-list, article pages and the news analyst's enrichment file."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from marketbrief.constants.validation import ENRICH_ENUMS
from marketbrief.pipeline.validate.gate_result import Result, work_dir
from marketbrief.pipeline.validate.row_checks import check_rows, read_rows, todays_files


def registrable(host: str) -> str:
    parts = host.lower().split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "gov", "ac", "edu"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def allowed_news_sources(cfg: dict) -> tuple[set[str], dict[str, set[str]]]:
    """(domains of the Google News base, outlet name -> allowed link domains)."""
    news = cfg.get("news") or {}
    gn = news.get("google_news") or {}
    gdom = {registrable(urlparse(gn["base"]).hostname)} if gn.get("base") else set()
    outlets = {}
    for o in news.get("outlets") or []:
        doms = {registrable(urlparse(o["url"]).hostname)} | {registrable(d) for d in o.get("link_domains") or []}
        outlets[o["name"]] = doms
    return gdom, outlets


def check_news_sources(res: Result, cfg: dict, con, today: date):
    gdom, outlets = allowed_news_sources(cfg)
    rows = con.execute("SELECT id, url, feed, tickers FROM news WHERE CAST(first_seen_at AS DATE) = ?", [today]).fetchall()
    bad = []
    for nid, url, feed, tickers in rows:
        u = urlparse(url or "")
        dom = registrable(u.hostname or "")
        if u.scheme != "https":
            bad.append((nid, f"scheme {u.scheme or 'none'}", tickers))
        elif str(feed).startswith("gnews:"):
            if dom not in gdom:
                bad.append((nid, f"Google News feed but link domain {dom}", tickers))
        elif feed in outlets:
            if dom not in outlets[feed]:
                bad.append((nid, f"outlet {feed} but link domain {dom} (allowed {sorted(outlets[feed])})", tickers))
        else:
            bad.append((nid, f"feed {feed!r} is not a configured outlet", tickers))
    if bad:
        res.block("NEWS_SOURCE", f"{len(bad)} news rows from unconfigured sources or not https, e.g. "
                  + "; ".join(f"{i}: {w}" for i, w, _ in bad[:5]),
                  [t for *_, ts_ in bad for t in (ts_ or []) if t in cfg["tickers"]])


def check_articles(res: Result, cfg: dict, today: date):
    """news_articles written today (collect_articles.py): a known access value, no stored article
    text (extract: at most 3 sentences of at most 40 words), and a page read only from an
    allowlisted https:// URL (config/news_sources.yaml)."""
    from marketbrief.analytics.article_pages import url_check
    from marketbrief.analytics.news_sources import load_sources
    from marketbrief.constants.articles import ACCESS
    src, bad = load_sources(), []
    for p in todays_files(cfg["market"], "news_articles", today):
        for r in read_rows(p)[0]:
            ext = r.get("extract") or []
            if r.get("access") not in ACCESS:
                bad.append(f"{r.get('id')}: access {r.get('access')!r}")
            elif len(ext) > 3 or any(len(str(s).split()) > 40 for s in ext):
                bad.append(f"{r.get('id')}: extract longer than 3 sentences of 40 words")
            elif r["access"] in ("full", "partial", "paywalled") and r.get("http_status") is not None \
                    and not url_check(r.get("final_url"), src)[0]:
                bad.append(f"{r.get('id')}: read from a URL that is not an allowlisted https page "
                           f"({str(r.get('final_url'))[:60]})")
            elif r["access"] in ("skipped_unlisted", "undecoded") and r.get("http_status") is not None:
                bad.append(f"{r.get('id')}: access {r['access']} but an HTTP status is stored")
    if bad:
        res.warn("ARTICLE_ROWS", f"{len(bad)} news_articles rows break the article rules, e.g. {bad[:3]}")


def stage_news(res, cfg, con, st, now, today, vc, path: Path | None = None):
    path = path or work_dir() / "enriched.jsonl"
    if not path.exists():
        res.info["news"] = "no work/enriched.jsonl"
        return
    rows, problems = read_rows(path) if path.stat().st_size else ([], [])
    if problems:
        res.block("BAD_FILE", f"{path.name}: {'; '.join(problems[:3])}")
    bad = check_rows("news_enriched", rows, False, now, timedelta(minutes=vc["future_tolerance_minutes"]))
    if bad:
        res.block("SCHEMA", f"{path.name}: {'; '.join(bad)}")
    new_ids = {r[0] for r in con.execute("SELECT id FROM news WHERE CAST(first_seen_at AS DATE) = ?", [today]).fetchall()}
    new_ids |= {r[0] for r in con.execute("SELECT id FROM announcements WHERE CAST(first_seen_at AS DATE) = ?",
                                          [today]).fetchall()}
    done = {r[0] for r in con.execute("SELECT DISTINCT id FROM news_enriched").fetchall()}
    ids = [r.get("id") for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        res.block("DUPLICATE_ID", f"{path.name}: repeated ids {dup[:5]}")
    extra = sorted({i for i in ids if i not in new_ids})
    if extra:
        res.block("ENRICH_UNKNOWN_ID", f"{len(extra)} ids are not news/announcements first seen today, e.g. {extra[:5]}")
    again = sorted({i for i in ids if i in done})
    if again:
        res.block("ENRICH_ALREADY_STORED", f"{len(again)} ids already in news_enriched, e.g. {again[:5]}")
    missing = sorted(new_ids - done - set(ids))
    if missing:
        res.warn("ENRICH_MISSING", f"{len(missing)} of today's news/announcement ids have no enrichment, e.g. {missing[:5]}")
    for r in rows:
        why = []
        for k, lo, hi in (("relevance", 0, 1), ("sentiment", -1, 1), ("novelty", 0, 1)):
            v = r.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                why.append(f"{k} {v!r} not in {lo}..{hi}")
        why += [f"{k} {r.get(k)!r} not one of {sorted(ok)}" for k, ok in ENRICH_ENUMS.items() if r.get(k) not in ok]
        if not isinstance(r.get("summary"), str) or len(r["summary"].split()) > 25:
            why.append("summary missing or over 25 words")
        if not r.get("prompt_version"):
            why.append("prompt_version missing")
        if not r.get("analyzed_at"):
            why.append("analyzed_at missing")
        if why:
            res.block("ENRICH_RULE", f"{r.get('id')}: {'; '.join(why)}")
    res.info["news"] = {"records": len(rows), "new_ids_today": len(new_ids)}
