"""The news-source allowlist (config/news_sources.yaml): vetted outlets and their tiers, news agencies (wires)
and how an item's origin is read from its byline, provider, source label, title or text."""

from __future__ import annotations

import re

import yaml

from marketbrief.analytics.news_tags import norm
from marketbrief.analytics.text_measures import sentences
from marketbrief.constants.articles import LEDE_SENTENCES, SOURCE_LABEL_PATTERN, TIER_2, TIER_UNLISTED
from marketbrief.constants.files import FILE_NEWS_SOURCES_CONFIG
from marketbrief.core import paths

NEVER_MATCHES = r"(?!x)x"
WWW_PREFIX = "www."


def normalise_label(label: str | None) -> str:
    """A source label or name for comparison: spaces collapsed, curly apostrophes straightened, lower case,
    without a leading 'by ' or trailing dots."""
    return re.sub(r"\s+", " ", (label or "").replace("’", "'")).strip().lower().removeprefix("by ").strip(" .")


def alternation(names: list[str]) -> str:
    """A regex alternation of the names, longest first."""
    return "|".join(sorted(map(re.escape, names), key=len, reverse=True))


class Sources:
    """The settings of config/news_sources.yaml with lookups by host, label and wire name."""

    def __init__(self, cfg: dict):
        """The news-source rules of a market config."""
        self.cfg = cfg
        self.sel = cfg.get("selection") or {}
        self.clusters = cfg.get("clusters") or {}
        self.domains: dict[str, dict] = {
            domain.lower(): (settings or {}) for domain, settings in (cfg.get("domains") or {}).items()
        }
        self.label_domain = {
            normalise_label(name): domain
            for domain, settings in self.domains.items()
            for name in settings.get("names") or []
        }
        self.wires: dict[str, dict] = cfg.get("wires") or {}
        self.wire_names = {
            normalise_label(name): wire
            for wire, settings in self.wires.items()
            for name in [wire, *(settings.get("names") or [])]
        }
        self.wire_domains = {
            domain: wire for wire, settings in self.wires.items() for domain in settings.get("domains") or []
        }
        promo = cfg.get("promotional") or {}
        self.promo_names = {normalise_label(name) for name in promo.get("providers") or []}
        self.promo_domains = {domain.lower() for domain in promo.get("domains") or []}
        self.promo_text = re.compile(
            "|".join(f"(?:{pattern})" for pattern in promo.get("text") or []) or NEVER_MATCHES, re.I
        )
        self.material = [
            (int(weight), re.compile(r"\b(?:" + "|".join(patterns) + r")\b", re.I))
            for weight, patterns in (cfg.get("material_terms") or {}).items()
        ]
        attribution = [name for settings in self.wires.values() for name in settings.get("attribution") or []]
        alt = alternation(attribution)
        self._wire_att = re.compile(
            rf"\b(?:({alt})\s+(?i:has\s+|had\s+|first\s+)?(?i:reported|reports|said in a report|news agency reported)"
            rf"|(?i:according to (?:a |an )?)({alt})(?:\s+(?i:(?:news\s+)?report))?"
            rf"|(?i:told )({alt})\b|(?i:citing (?:a |an )?)({alt})\b)"
        )
        # "(With inputs from PTI)" closes an Indian agency-based story, so it is read anywhere
        self._inputs = re.compile(rf"(?i:with (?:additional )?inputs from )({alt})\b")
        datelines = alternation([name for settings in self.wires.values() for name in settings.get("names") or []])
        self._dateline = re.compile(rf"\(({datelines})\)\s*[-–—:]?")
        self._title_wire = re.compile(
            rf"(?:\bBy\s+({alt}|AP)\s*$|[-:|]\s*({alt})(?:\s+reports?)?\s*$"
            rf"|\b({alt})\s+(?:reports?|reported)\b|\bciting\s+({alt})\b)",
            re.I,
        )
        self._att_wire = {
            normalise_label(name): wire
            for wire, settings in self.wires.items()
            for name in settings.get("attribution") or []
        }

    # domains
    def lookup(self, host: str | None) -> tuple[str | None, dict | None]:
        """(allowlisted domain, its settings) for a host or one of its parent domains; (None, None)."""
        host = (host or "").lower().strip(".")
        host = host.removeprefix(WWW_PREFIX)
        parts = host.split(".")
        for start in range(len(parts) - 1):
            domain = ".".join(parts[start:])
            if domain in self.domains:
                return domain, self.domains[domain]
        return None, None

    def tier(self, host: str | None) -> str:
        """The tier of an outlet's host (primary, tier1, tier2), or 'unlisted'."""
        domain, meta = self.lookup(host)
        return meta.get("tier", TIER_2) if domain else TIER_UNLISTED

    def domain_of_label(self, label: str | None) -> str | None:
        """Allowlisted domain of a source label: a configured name ('Business Today'), or a label
        that is itself a host ('businesstoday.in', 'bfsi.economictimes.indiatimes.com')."""
        domain = self.label_domain.get(normalise_label(label))
        if domain is None and label and re.fullmatch(SOURCE_LABEL_PATTERN, label.strip()):
            domain = self.lookup(label.strip())[0]
        return domain

    def is_promotional(
        self, *, name: str | None = None, domain: str | None = None, text: str | None = None
    ) -> str | None:
        """Why an item is vendor or promotional content, or None."""
        if name and normalise_label(name) in self.promo_names:
            return f"provider {name}"
        host = (domain or "").lower()
        if host and any(
            host == promo_domain or host.endswith("." + promo_domain) for promo_domain in self.promo_domains
        ):
            return f"domain {domain}"
        if text:
            found = self.promo_text.search(text)
            if found:
                return f"text '{found.group(0)[:40]}'"
        return None

    def priority(self, title: str) -> int:
        """The summed weight of the `material_terms` a title matches."""
        return sum(weight for weight, pattern in self.material if pattern.search(title or ""))

    # wires
    def wire_of_name(self, name: str | None) -> str | None:
        """The news agency a name stands for, or None."""
        return self.wire_names.get(normalise_label(name)) if name else None

    def wire_of_domain(self, host: str | None) -> str | None:
        """The news agency that owns a host (or a parent domain of it), or None."""
        host = (host or "").lower()
        return next(
            (wire for domain, wire in self.wire_domains.items() if host == domain or host.endswith("." + domain)), None
        )

    def wire_in_title(self, title: str | None) -> str | None:
        """The agency a title credits ('By Reuters', '- Reuters', 'Reuters reports'), or None."""
        found = self._title_wire.search(title or "")
        if not found:
            return None
        name = next(group for group in found.groups() if group)
        return "AP" if name.upper() == "AP" else self._att_wire.get(normalise_label(name))

    def wire_in_text(self, text: str | None) -> tuple[str | None, str | None]:
        """(agency, 'dateline'|'attribution') from an article's text, or (None, None): a dateline in
        the first 400 characters, an attribution phrase in the lede, or "with inputs from" anywhere."""
        text = text or ""
        found = self._dateline.search(text[:400])
        if found:
            return self.wire_of_name(found.group(1)), "dateline"
        # attribution only in the lede (first LEDE_SENTENCES sentences): a later "Reuters reported"
        # usually quotes background, not the story's origin
        found = self._wire_att.search(" ".join(sentences(text)[:LEDE_SENTENCES])) or self._inputs.search(text)
        if found:
            return self._att_wire.get(normalise_label(next(group for group in found.groups() if group))), "attribution"
        return None, None

    def detect_wire(
        self, *, byline=None, provider=None, text=None, title=None, source=None, domain=None
    ) -> tuple[str | None, str | None]:
        """(agency, evidence) of an item's origin: provider, byline, source label/domain, title, then text."""
        if provider and self.wire_of_name(provider):
            return self.wire_of_name(provider), "provider"
        for credit in re.split(r"\s*(?:,|;|\band\b|&)\s*", byline or ""):
            if credit and self.wire_of_name(credit):
                return self.wire_of_name(credit), "byline"
        wire = self.wire_of_name(source) or self.wire_of_domain(domain)
        if wire:
            return wire, "source"
        wire = self.wire_in_title(title)
        if wire:
            return wire, "title"
        return self.wire_in_text(text)


def label_domains(pairs, src: Sources | None = None) -> dict[str, str]:
    """norm(source label) -> outlet domain, learned from (label, domain) pairs of one run's rows
    (Google News <source url>), so a label-only row and a domain row of one outlet are one outlet:
    a label used with exactly one domain ("The CSR Universe" -> thecsruniverse.com), and a label
    without one whose letters equal a seen domain's first part ("Pluang" -> pluang.com) unless that
    domain is allowlisted in `src` (vetting comes only from a configured name or the row's own domain)."""
    seen: dict[str, set] = {}
    labels = set()
    for label, domain in pairs:
        if label:
            labels.add(label)
        if label and domain:
            seen.setdefault(norm(label), set()).add(domain)
    learned = {key: next(iter(domains)) for key, domains in seen.items() if len(domains) == 1}
    first_part = {}
    for domains in seen.values():
        for domain in domains:
            first_part.setdefault(re.sub(r"[^a-z0-9]", "", domain.split(".")[0]), domain)
    for label in labels:
        key = norm(label)
        if key not in learned:
            letters = re.sub(r"[^a-z0-9]", "", label.lower())
            if letters in first_part and not (src and src.lookup(first_part[letters])[0]):
                learned[key] = first_part[letters]
    return learned


def outlet_of(source: str | None, src: Sources, learned: dict[str, str]) -> str | None:
    """Outlet domain of a source label: configured name, learned mapping, or a label that is a host."""
    if not source:
        return None
    domain = src.domain_of_label(source) or learned.get(norm(source))
    if domain is None and re.fullmatch(SOURCE_LABEL_PATTERN, source.strip()):
        domain = source.strip().lower().removeprefix(WWW_PREFIX)
    return domain


def outlet_key(domain: str | None, source: str | None) -> str:
    """Key of an outlet in summaries and clusters: its domain, else 'label:<normalised label>'."""
    return domain or f"label:{norm(source)}"


def load_sources() -> Sources:
    """The allowlist settings of config/news_sources.yaml."""
    return Sources(yaml.safe_load((paths.CONFIG / FILE_NEWS_SOURCES_CONFIG).read_text()))
