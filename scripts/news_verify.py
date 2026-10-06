"""News verification, phase A (deterministic, no LLM; docs/DESIGN.md section 3a). Shared helpers for
collect_articles.py (fetch and extract allowlisted article pages) and news_clusters.py (group
same-event items, count independent origins, attach primary-source candidates).

Rules (config/news_sources.yaml):
- Only HTTPS URLs on an allowlisted domain are requested, with TLS verification on (the session's
  CA bundle via REQUESTS_CA_BUNDLE); every redirect hop is checked the same way. Anything else is
  never requested (access=skipped_unlisted).
- Extraction order: JSON-LD articleBody, then trafilatura, then newspaper4k (per-domain order in
  `extract`). A page whose JSON-LD says isAccessibleForFree=false is paywalled: only its description
  and OpenGraph text are read, never the body.
- Article text is untrusted data: it is only measured (numbers, shingles, attribution patterns) and
  at most 3 key sentences of at most 40 words each are kept. The full text is never stored.
- Origins: an agency byline, JSON-LD provider, dateline ("(Reuters) -"), title ("By Reuters") or
  text attribution ("Reuters reported", "told PTI") marks a copy of that agency's story; MinHash
  6-shingle containment >= 0.5 between two texts marks a copy too (news_clusters.py)."""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from functools import lru_cache
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml

from marketbrief.core import paths
from marketbrief.sources.article_fetch import get_article_page

METHOD_VERSION = "nv-a1"
ACCESS = ("full", "partial", "paywalled", "blocked", "undecoded", "skipped_unlisted")
LISTED_TIERS = ("primary", "tier1", "tier2")
NUM_PERM = 128
LEDE_SENTENCES = 3
SHINGLE = 6


# ---------- config ----------

def load_sources() -> "Sources":
    return Sources(yaml.safe_load((paths.CONFIG / "news_sources.yaml").read_text()))


def _name(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'")).strip().lower().removeprefix("by ").strip(" .")


class Sources:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sel = cfg.get("selection") or {}
        self.clusters = cfg.get("clusters") or {}
        self.domains: dict[str, dict] = {d.lower(): (m or {}) for d, m in (cfg.get("domains") or {}).items()}
        self.label_domain = {_name(n): d for d, m in self.domains.items() for n in m.get("names") or []}
        self.wires: dict[str, dict] = cfg.get("wires") or {}
        self.wire_names = {_name(n): w for w, m in self.wires.items() for n in [w, *(m.get("names") or [])]}
        self.wire_domains = {d: w for w, m in self.wires.items() for d in m.get("domains") or []}
        promo = cfg.get("promotional") or {}
        self.promo_names = {_name(n) for n in promo.get("providers") or []}
        self.promo_domains = {d.lower() for d in promo.get("domains") or []}
        self.promo_text = re.compile("|".join(f"(?:{p})" for p in promo.get("text") or []) or r"(?!x)x", re.I)
        self.material = [(int(w), re.compile(r"\b(?:" + "|".join(ps) + r")\b", re.I))
                         for w, ps in (cfg.get("material_terms") or {}).items()]
        att = [n for m in self.wires.values() for n in m.get("attribution") or []]
        alt = "|".join(sorted(map(re.escape, att), key=len, reverse=True))
        self._wire_att = re.compile(
            rf"\b(?:({alt})\s+(?i:has\s+|had\s+|first\s+)?(?i:reported|reports|said in a report|news agency reported)"
            rf"|(?i:according to (?:a |an )?)({alt})(?:\s+(?i:(?:news\s+)?report))?"
            rf"|(?i:told )({alt})\b|(?i:citing (?:a |an )?)({alt})\b)")
        # "(With inputs from PTI)" closes an Indian agency-based story, so it is read anywhere
        self._inputs = re.compile(rf"(?i:with (?:additional )?inputs from )({alt})\b")
        dl = "|".join(sorted(map(re.escape, [n for m in self.wires.values() for n in m.get("names") or []]),
                             key=len, reverse=True))
        self._dateline = re.compile(rf"\(({dl})\)\s*[-–—:]?")
        self._title_wire = re.compile(rf"(?:\bBy\s+({alt}|AP)\s*$|[-:|]\s*({alt})(?:\s+reports?)?\s*$"
                                      rf"|\b({alt})\s+(?:reports?|reported)\b|\bciting\s+({alt})\b)", re.I)
        self._att_wire = {_name(n): w for w, m in self.wires.items() for n in m.get("attribution") or []}

    # domains
    def lookup(self, host: str | None) -> tuple[str | None, dict | None]:
        """(allowlisted domain, its settings) for a host or one of its parent domains; (None, None)."""
        host = (host or "").lower().strip(".")
        host = host[4:] if host.startswith("www.") else host
        parts = host.split(".")
        for i in range(len(parts) - 1):
            d = ".".join(parts[i:])
            if d in self.domains:
                return d, self.domains[d]
        return None, None

    def tier(self, host: str | None) -> str:
        d, meta = self.lookup(host)
        return meta.get("tier", "tier2") if d else "unlisted"

    def domain_of_label(self, label: str | None) -> str | None:
        """Allowlisted domain of a source label: a configured name ('Business Today'), or a label
        that is itself a host ('businesstoday.in', 'bfsi.economictimes.indiatimes.com')."""
        d = self.label_domain.get(_name(label))
        if d is None and label and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", label.strip()):
            d = self.lookup(label.strip())[0]
        return d

    def is_promotional(self, *, name: str | None = None, domain: str | None = None, text: str | None = None) -> str | None:
        """Why an item is vendor or promotional content, or None."""
        if name and _name(name) in self.promo_names:
            return f"provider {name}"
        host = (domain or "").lower()
        if host and any(host == d or host.endswith("." + d) for d in self.promo_domains):
            return f"domain {domain}"
        if text:
            m = self.promo_text.search(text)
            if m:
                return f"text '{m.group(0)[:40]}'"
        return None

    def priority(self, title: str) -> int:
        return sum(w for w, pat in self.material if pat.search(title or ""))

    # wires
    def wire_of_name(self, name: str | None) -> str | None:
        return self.wire_names.get(_name(name)) if name else None

    def wire_of_domain(self, host: str | None) -> str | None:
        host = (host or "").lower()
        return next((w for d, w in self.wire_domains.items() if host == d or host.endswith("." + d)), None)

    def wire_in_title(self, title: str | None) -> str | None:
        m = self._title_wire.search(title or "")
        if not m:
            return None
        n = next(g for g in m.groups() if g)
        return "AP" if n.upper() == "AP" else self._att_wire.get(_name(n))

    def wire_in_text(self, text: str | None) -> tuple[str | None, str | None]:
        """(agency, 'dateline'|'attribution') from an article's text, or (None, None): a dateline in
        the first 400 characters, an attribution phrase in the lede, or "with inputs from" anywhere."""
        text = text or ""
        m = self._dateline.search(text[:400])
        if m:
            return self.wire_of_name(m.group(1)), "dateline"
        # attribution only in the lede (first LEDE_SENTENCES sentences): a later "Reuters reported"
        # usually quotes background, not the story's origin
        m = self._wire_att.search(" ".join(sentences(text)[:LEDE_SENTENCES])) or self._inputs.search(text)
        if m:
            return self._att_wire.get(_name(next(g for g in m.groups() if g))), "attribution"
        return None, None

    def detect_wire(self, *, byline=None, provider=None, text=None, title=None, source=None,
                    domain=None) -> tuple[str | None, str | None]:
        """(agency, evidence) of an item's origin: provider, byline, source label/domain, title, then text."""
        if provider and self.wire_of_name(provider):
            return self.wire_of_name(provider), "provider"
        for b in re.split(r"\s*(?:,|;|\band\b|&)\s*", byline or ""):
            if b and self.wire_of_name(b):
                return self.wire_of_name(b), "byline"
        w = self.wire_of_name(source) or self.wire_of_domain(domain)
        if w:
            return w, "source"
        w = self.wire_in_title(title)
        if w:
            return w, "title"
        return self.wire_in_text(text)


# ---------- outlets of source labels ----------

def label_domains(pairs, src: "Sources | None" = None) -> dict[str, str]:
    """norm(source label) -> outlet domain, learned from (label, domain) pairs of one run's rows
    (Google News <source url>), so a label-only row and a domain row of one outlet are one outlet:
    a label used with exactly one domain ("The CSR Universe" -> thecsruniverse.com), and a label
    without one whose letters equal a seen domain's first part ("Pluang" -> pluang.com) unless that
    domain is allowlisted in `src` (vetting comes only from a configured name or the row's own domain)."""
    from news_tags import norm
    seen: dict[str, set] = {}
    labels = set()
    for label, dom in pairs:
        if label:
            labels.add(label)
        if label and dom:
            seen.setdefault(norm(label), set()).add(dom)
    out = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
    first = {}
    for v in seen.values():
        for d in v:
            first.setdefault(re.sub(r"[^a-z0-9]", "", d.split(".")[0]), d)
    for label in labels:
        k = norm(label)
        if k not in out:
            c = re.sub(r"[^a-z0-9]", "", label.lower())
            if c in first and not (src and src.lookup(first[c])[0]):
                out[k] = first[c]
    return out


def outlet_of(source: str | None, src: "Sources", learned: dict[str, str]) -> str | None:
    """Outlet domain of a source label: configured name, learned mapping, or a label that is a host."""
    from news_tags import norm
    if not source:
        return None
    d = src.domain_of_label(source) or learned.get(norm(source))
    if d is None and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", source.strip()):
        d = source.strip().lower().removeprefix("www.")
    return d


def outlet_key(domain: str | None, source: str | None) -> str:
    """Key of an outlet in summaries and clusters: its domain, else 'label:<normalised label>'."""
    from news_tags import norm
    return domain or f"label:{norm(source)}"


# ---------- URLs ----------

def host_of(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def url_check(url: str | None, src: Sources) -> tuple[bool, str, str | None]:
    """(may fetch, reason, allowlisted domain). Only https:// URLs on an allowlisted domain whose
    entry does not say `fetch: false` may be requested."""
    if not url:
        return False, "no url", None
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False, f"not https ({parts.scheme or 'no scheme'})", None
    if parts.port not in (None, 443):
        return False, f"non-standard port {parts.port}", None
    d, meta = src.lookup(parts.hostname)
    if not d:
        return False, f"host {parts.hostname} not on the allowlist", None
    if meta.get("fetch") is False:
        return False, f"{d} not fetched: {meta.get('note') or 'fetch: false'}", d
    return True, "ok", d


def canonical_url(url: str | None) -> str | None:
    """https://host/path without query, fragment, 'www.', 'm.' or a trailing slash (dedupe key)."""
    if not url:
        return None
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    for pre in ("www.", "m.", "amp."):
        host = host.removeprefix(pre)
    path = re.sub(r"/amp(?=/|$)|/amp_articleshow/", lambda m: "/articleshow/" if "articleshow" in m.group(0) else "",
                  p.path or "/").rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


# ---------- fetching ----------

class FetchResult:
    def __init__(self, status=None, final_url=None, html=None, error=None, requests=0, skipped=None):
        self.status, self.final_url, self.html, self.error = status, final_url, html, error
        self.requests, self.skipped = requests, skipped


def fetch_page(session, url: str, src: Sources) -> FetchResult:
    """GET an allowlisted HTTPS page, following at most `max_redirects` redirects by hand so that
    every hop is checked (HTTPS, allowlisted) before it is requested. TLS verification stays on."""
    sel, n = src.sel, 0
    for _ in range(int(sel.get("max_redirects", 5)) + 1):
        ok, why, _d = url_check(url, src)
        if not ok:
            return FetchResult(final_url=url, error=why, requests=n, skipped=why)
        try:
            n += 1
            r = get_article_page(session, url, sel)
        except Exception as e:   # TLS, proxy refusal, timeout: never retried without verification
            kind = "tls" if "SSL" in type(e).__name__ or "certificate" in str(e).lower() else "network"
            return FetchResult(final_url=url, error=f"{kind}: {type(e).__name__}: {str(e)[:160]}", requests=n)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location")
            r.close()
            if not loc:
                return FetchResult(status=r.status_code, final_url=url, error="redirect without location", requests=n)
            url = urljoin(url, loc)
            continue
        if r.status_code != 200:
            r.close()
            return FetchResult(status=r.status_code, final_url=url, error=f"HTTP {r.status_code}", requests=n)
        ctype = (r.headers.get("content-type") or "").lower()
        if ctype and "html" not in ctype:
            r.close()
            return FetchResult(status=200, final_url=url, error=f"not HTML ({ctype[:40]})", requests=n)
        body, limit = b"", int(sel.get("max_bytes", 4_000_000))
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) >= limit:
                break
        r.close()
        # requests assumes ISO-8859-1 for text/* without a charset; pages are UTF-8 unless they say so
        enc = r.encoding if "charset=" in ctype and r.encoding else "utf-8"
        return FetchResult(status=200, final_url=url, html=body.decode(enc, errors="replace"), requests=n)
    return FetchResult(final_url=url, error="too many redirects", requests=n)


# ---------- extraction ----------

def _ld_objects(doc) -> list[dict]:
    out = []
    for s in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            d = json.loads(s, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                if "@graph" in x:
                    stack += x["@graph"] if isinstance(x["@graph"], list) else [x["@graph"]]
                types = x.get("@type")
                types = types if isinstance(types, list) else [types]
                if any(isinstance(t, str) and ("Article" in t or t in ("BlogPosting", "LiveBlogPosting")) for t in types):
                    out.append(x)
    return out


def _names(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [v["name"]] if isinstance(v.get("name"), str) else []
    if isinstance(v, list):
        return [n for x in v for n in _names(x)]
    return []


def _false(v) -> bool:
    return v is False or (isinstance(v, str) and v.strip().lower().rsplit("/", 1)[-1] == "false")


def _meta(doc, *names) -> str | None:
    for n in names:
        v = doc.xpath(f'//meta[@property="{n}" or @name="{n}" or @itemprop="{n}"]/@content')
        if v and v[0].strip():
            return v[0].strip()
    return None


_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


def _clean(text: str | None) -> str:
    """Plain text: HTML entities decoded (JSON-LD bodies carry '&#39;', '&zwnj;'), zero-width characters
    dropped, whitespace collapsed, and a space put back where paragraphs were glued ('said.The', 'post.HDFC')."""
    text = _ZERO_WIDTH.sub("", html_lib.unescape(text or ""))
    text = re.sub(r"(?<=[A-Za-z0-9]{2}[.!?])(?=[A-Z][A-Za-z])", " ", text)   # 'said.The', 'post.HDFC'
    return re.sub(r"\s+", " ", text).strip()


def extract_jsonld(ld: dict | None) -> str:
    return _clean((ld or {}).get("articleBody")) if isinstance((ld or {}).get("articleBody"), str) else ""


def extract_trafilatura(html: str, url: str) -> str:
    import trafilatura
    return _clean(trafilatura.extract(html, url=url, favor_precision=True, include_comments=False) or "")


def extract_newspaper(html: str, url: str) -> str:
    import newspaper
    # fetch_images=False: newspaper4k would otherwise download images to score them
    a = newspaper.Article(url, fetch_images=False)
    a.download(input_html=html)
    a.parse()
    return _clean(a.text)


EXTRACTORS = {"jsonld": None, "trafilatura": extract_trafilatura, "newspaper": extract_newspaper}


def parse_article(html: str, url: str, src: Sources, hints: dict | None = None) -> dict:
    """Metadata and body text of one page (the body stays in memory only). access: full | partial |
    paywalled. Paywalled (isAccessibleForFree false on the article or a part of it): only the
    description / OpenGraph text."""
    from lxml import html as lh
    hints = hints or {}
    try:
        doc = lh.fromstring(html)
    except (ValueError, Exception):
        return {"access": "partial", "text": "", "extractor": None, "note": "unparsable HTML"}
    lds = _ld_objects(doc)
    ld = next((x for x in lds if x.get("articleBody")), lds[0] if lds else None)
    info: dict = {
        "date_published": (ld or {}).get("datePublished") or _meta(doc, "article:published_time", "datePublished",
                                                                    "parsely-pub-date", "publish-date", "pubdate"),
        "date_modified": (ld or {}).get("dateModified") or _meta(doc, "article:modified_time", "dateModified"),
        "byline": ", ".join(_names((ld or {}).get("author"))) or _meta(doc, "article:author", "author", "parsely-author"),
        "provider": ", ".join(_names((ld or {}).get("provider"))) or None,
        "description": _clean((ld or {}).get("description") or _meta(doc, "og:description", "description")),
    }
    parts = (ld or {}).get("hasPart")
    parts = parts if isinstance(parts, list) else [parts] if parts else []
    paywalled = bool(ld) and (_false(ld.get("isAccessibleForFree"))
                              or any(isinstance(p, dict) and _false(p.get("isAccessibleForFree")) for p in parts))
    if paywalled:
        return {**info, "access": "paywalled", "text": info["description"], "extractor": "description"}
    order = hints.get("extract") or ["jsonld", "trafilatura", "newspaper"]
    min_chars, full_chars = int(src.sel.get("min_chars", 400)), int(src.sel.get("full_chars", 800))
    best, best_by, errors = "", None, []
    for name in order:
        try:
            text = extract_jsonld(ld) if name == "jsonld" else EXTRACTORS[name](html, url)
        except Exception as e:   # an extractor failing on one page is not fatal
            errors.append(f"{name}: {type(e).__name__}")
            continue
        if len(text) > len(best):
            best, best_by = text, name
        if len(text) >= min_chars:
            break
    if not best and info["description"]:
        best, best_by = info["description"], "description"
    access = "full" if len(best) >= full_chars and best_by != "description" else "partial"
    return {**info, "access": access, "text": best, "extractor": best_by,
            "note": "; ".join(errors) or None}


# ---------- text measures ----------

_SENT = re.compile(r"(?<=[.!?])[\"'”’)]?\s+(?=[\"'“‘(]?[A-Z0-9₹$])")
_NUM = re.compile(
    r"(?P<cur>US\$|\$|₹|Rs\.?\s?|INR\s?|USD\s?|€|£)?\s?"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<scale>lakh crore|trillion|billion|million|thousand|crore|lakh|tn|bn|mn|cr|k|b|m)\b)?"
    r"\s?(?P<pct>%|per ?cent\b|percent\b|bps\b|basis points\b)?", re.I)
_SCALE = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6,
          "thousand": 1e3, "k": 1e3, "crore": 1e7, "cr": 1e7, "lakh": 1e5, "lakh crore": 1e12}
_CUR = {"$": "usd", "us$": "usd", "usd": "usd", "₹": "inr", "rs": "inr", "rs.": "inr", "inr": "inr",
        "€": "eur", "£": "gbp"}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(_clean(text)) if s.strip()]


def numbers(text: str | None, limit: int = 30) -> list[str]:
    """Normalised numbers: value with scale applied, then a unit (usd, inr, eur, gbp, pct, bps):
    '$3.8 billion' -> '3.8e+09 usd', 'Rs 5,77,094 crore' -> '5.77094e+12 inr', '24.7%' -> '24.7 pct',
    '486,532' -> '486532'. Plain years (1900-2100) and plain numbers below 10 are left out."""
    out: list[str] = []
    for m in _NUM.finditer(text or ""):
        raw = m.group("num")
        if m.start("num") > 0 and (text[m.start("num") - 1].isalnum()):
            continue                                # Q3, FY26, H1
        v = float(raw.replace(",", ""))
        cur = _CUR.get((m.group("cur") or "").strip().lower().replace(" ", ""))
        scale, pct = (m.group("scale") or "").lower(), (m.group("pct") or "").lower()
        if scale in ("m", "b", "k") and not cur:
            scale = ""                              # "5m" alone is ambiguous (minutes, metres)
        v *= _SCALE.get(scale, 1)
        unit = "pct" if pct and pct[0] in "%p" else "bps" if pct else cur
        if not unit and not scale and ((1900 <= v <= 2100 and "." not in raw and "," not in raw) or v < 10):
            continue
        s = f"{v:.6g}" + (f" {unit}" if unit else "")
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def distinctive(nums: list[str]) -> set[str]:
    """Numbers that identify an event in a headline: a currency amount, a percent with decimals, or a
    plain number >= 1000 (not a year). '2%' or 'Q3' are not distinctive."""
    out = set()
    for s in nums:
        val, _, unit = s.partition(" ")
        v = float(val)
        if unit in ("usd", "inr", "eur", "gbp") or (unit == "pct" and v != int(v)) or (not unit and v >= 1000):
            out.add(s)
    return out


def key_sentences(text: str, names: list[str] | None = None, k: int = 3, max_words: int = 40) -> list[str]:
    """At most k sentences (each cut to max_words words): the lede, then sentences with a number or
    one of the company names, in text order."""
    sents = [s for s in sentences(text) if len(s.split()) >= 6]
    if not sents:
        sents = [s for s in sentences(text) if s]
    pat = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b", re.I) if names else None
    chosen = sents[:1]
    for s in sents[1:]:
        if len(chosen) >= k:
            break
        if re.search(r"\d", s) or (pat and pat.search(s)):
            chosen.append(s)
    for s in sents[1:]:
        if len(chosen) >= k:
            break
        if s not in chosen:
            chosen.append(s)
    chosen.sort(key=sents.index)
    return [" ".join(s.split()[:max_words]) for s in chosen[:k]]


SOURCES_SAY = re.compile(
    r"\b(?:sources?|people|persons?|officials?|executives?)\s+(?:familiar|aware|close|with (?:direct )?knowledge)\b"
    r"|\bsources?\s+(?:said|say|says|told)\b|\bsaid\s+(?:\w+\s+){0,3}sources?\b|\bciting\s+(?:\w+\s+){0,4}sources?\b"
    r"|\baccording to (?:\w+\s+){0,3}sources?\b|\bwho (?:declined to be|did not want to be|asked not to be) "
    r"(?:named|identified)\b|:\s*sources?\s*$|\bsources say\b", re.I)


def sources_say(*texts: str | None) -> bool:
    return any(t and SOURCES_SAY.search(t) for t in texts)


_TOK = re.compile(r"[a-z0-9$₹%.]+")


def shingles(text: str | None, n: int = SHINGLE) -> set[str]:
    w = [t.strip(".") for t in _TOK.findall((text or "").lower()) if t.strip(".")]
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def minhash_hex(sh: set[str]) -> str | None:
    """MinHash signature (datasketch, NUM_PERM permutations, seed 1) as hex: NUM_PERM x 8 hex digits."""
    if not sh:
        return None
    from datasketch import MinHash
    m = MinHash(num_perm=NUM_PERM, seed=1)
    m.update_batch([s.encode("utf-8") for s in sorted(sh)])
    return "".join(f"{int(v):08x}" for v in m.hashvalues)


def _sig(h: str) -> list[int]:
    return [int(h[i:i + 8], 16) for i in range(0, len(h), 8)]


def jaccard_est(a: str, b: str) -> float:
    sa, sb = _sig(a), _sig(b)
    return sum(x == y for x, y in zip(sa, sb)) / len(sa)


def containment_est(a: str | None, na: int | None, b: str | None, nb: int | None) -> float | None:
    """Estimated |A∩B| / min(|A|,|B|) from two MinHash signatures and their shingle counts."""
    if not a or not b or not na or not nb:
        return None
    j = jaccard_est(a, b)
    inter = j * (na + nb) / (1 + j)
    return min(1.0, inter / min(na, nb))


def containment_exact(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def content_hash(text: str | None) -> str | None:
    w = _TOK.findall((text or "").lower())
    return hashlib.sha256(" ".join(w).encode()).hexdigest() if w else None


@lru_cache(maxsize=1)
def _stop() -> frozenset:
    return frozenset("""a an the and or but of to in on at for from by with as is are was were be been has have
    had it its this that these those after before over under amid into out up down about than vs via per new
    says said say report reports reported live update updates today stock stocks share shares price prices market
    markets ltd inc corp co company limited plc nse bse nyse nasdaq what why how will may could should can
    reuters bloomberg pti ians ap afp ani billion billions million millions crore crores lakh trillion
    here you your why who his her their our more than just now""".split())


def title_tokens(title: str | None, drop: set[str] | None = None) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9&'-]*", (title or "").lower().replace("’", "'"))
    words = [w.removesuffix("'s") for w in words]
    return {w for w in words if len(w) >= 3 and w not in _stop() and w not in (drop or set())}
