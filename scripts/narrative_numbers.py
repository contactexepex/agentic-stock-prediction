"""Numbers in agent-written narrative against their sources (validate.py --stage report).

A number shown in the narrative passes only when a source number of the same kind and scope
rounds to it:
- kind: a percentage (`%`, `pp`, or `bp` as 1/100 of a percent) matches only percentages: numbers
  shown with `%` in a source, numbers in a context-pack section whose heading says "in %", or
  stored fractions x100 (returns, vol, change_pct; FRACTION_COLS). A plain number (with or
  without a currency or a cr/bn/k unit, converted) matches only plain source numbers.
- scope: a sentence that names watchlist companies or market symbols (ticker, symbol or
  configured name, falling back to the names on its line) is checked against those entities'
  rows plus market-level rows; a sentence that names none, against market-level rows only
  (regime, counts, script-written lines that name no company). Numbers from stored news,
  filings and announcement text count only for the ids the sentence (or its line) cites.
Ignored: dates, times, years, ids, links, tokens mixing letters and digits (5d, Q2, FY26), names
with digits (S&P 500), list numbering, and bare integers up to `small_int` (counts and labels).
Residual risk: an invented number can still pass when it equals, after rounding, some source
number of the same kind in scope (measured in the build report)."""
from __future__ import annotations

import bisect
import json
import math
import re
from collections import defaultdict
from numbers import Real

MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
NUM = re.compile(r"(?<![\w.])([-+−]?)\s?([₹$€£]|Rs\.?\s?|US\$)?\s?(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                 r"(\s?%|\s?bps?\b|\s?pp\b|\s?(?:cr|crore|lakh|mn|million|bn|billion|tn|trillion|k)\b)?(?![\w.]*\d)", re.I)
MASKS = [re.compile(p, re.I) for p in (
    r"<!--.*?-->", r"https?://\S+", r"\]\([^)]*\)", r"!\[[^\]]*\]",
    r"\bnse-ann-\d+\b", r"\b\d{10}-\d{2}-\d{6}\b", r"\b[0-9a-f]{16}\b",
    r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+Z-]+)?\b", r"\b\d{4}-W\d{2}\b",
    rf"\b{MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s*[-–]\s*(?:{MONTHS}\.?\s+)?\d{{1,2}})?(?:,?\s+\d{{4}})?\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s*(?:[-–]\s*\d{{1,2}}\s+)?{MONTHS}\b(?:,?\s+\d{{4}})?",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
    # a year: no decimals, no currency before, no unit after ("Rs 1915.85", "1950 crore" are amounts)
    r"(?<![₹$\d.,])(?<!Rs)(?<!Rs\s)(?<!Rs\.)(?<!Rs\.\s)(?<!₹\s)(?<!\$\s)(?<!USD\s)(?<!INR\s)"
    r"\b(?:19|20)\d{2}\b(?![.,]\d)"
    r"(?!\s?(?:%|pp\b|bps?\b|x\b|k\b|cr\b|crore|lakh|mn\b|million|bn\b|billion|tn\b|trillion))",
    r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]*\w\b",      # tokens mixing letters and digits: 5d, Q2, FY26, W40, 10y
    r"^\s*(?:\d+[.)]|#+)\s",                             # list numbering, headings
)]
IDS = re.compile(r"\b(?:[0-9a-f]{16}|nse-ann-\d+|\d{10}-\d{2}-\d{6})\b")
SENTENCE = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(*•\-])")
UNIT_MULT = {"cr": 1e7, "crore": 1e7, "lakh": 1e5, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9,
             "tn": 1e12, "trillion": 1e12, "k": 1e3}
EXTRA_NAMES = {"S&P 500", "Nifty 50", "Nasdaq 100", "Nasdaq-100", "Nikkei 225", "FTSE 100", "DAX 40", "Sensex 30",
               "Russell 2000", "Dow 30", "Nifty Bank", "COVID-19", "Section 232", "Item 2.02", "Form 4"}
GENERIC = {"General", "United", "India", "Indian", "US", "USD", "American", "National", "First", "State", "Bank",
           "Nifty", "Hang", "Oil", "Crude", "Dollar", "The"}

# Stored columns holding fractions (0.012 = 1.2%); every other numeric column is a plain number.
FRACTION_COLS = {"ret_1d", "ret_3d", "ret_5d", "ret_20d", "roc_10", "atr_pct", "realized_vol_10d", "ewma_vol",
                 "bb_width", "rel_sector_5d", "cue_change_pct", "price_vs_20d_high", "change_pct",
                 "vol_change_1d", "bench_ret_5d", "bench_vol_10d", "center", "sigma_h", "iv_sigma_h"}


def mask(text: str, names: list[str]) -> str:
    for n in names:
        text = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", " ", text)
    for m in MASKS:
        text = m.sub(" ", text)
    return text


def numbers(text: str, names: list[str], small_int: int | None = None) -> list[dict]:
    """Numbers shown in text: value in base units, kind (pct | plain), rounding tolerance, token."""
    out = []
    for line in text.splitlines():
        for m in NUM.finditer(mask(line, names)):
            sign, cur, digits, unit = m.group(1), m.group(2), m.group(3), (m.group(4) or "").strip().lower()
            val = float(digits.replace(",", ""))
            dec = len(digits.split(".")[1]) if "." in digits else 0
            if small_int is not None and dec == 0 and not unit and not cur and not sign and val <= small_int:
                continue
            tol = 0.5 * 10 ** -dec + 1e-9
            kind = "plain"
            if unit in ("%", "pp"):
                kind = "pct"
            elif unit in ("bp", "bps"):
                kind, val, tol = "pct", val / 100, tol / 100
            elif unit in UNIT_MULT:
                val, tol = val * UNIT_MULT[unit], tol * UNIT_MULT[unit]
            out.append({"value": val, "kind": kind, "tol": tol, "token": m.group(0).strip(), "line": line.strip()})
    return out


class Entities:
    """Watchlist tickers and market symbols, found in text by key or configured name."""

    def __init__(self, cfg: dict):
        aliases: dict[str, set[str]] = defaultdict(set)
        for key, meta in [*cfg["tickers"].items(), *cfg["symbols"].items()]:
            aliases[key].add(key)
            for extra in [meta.get("adr"), *(meta.get("aliases") or []), *(meta.get("wire_names") or [])]:
                if extra:
                    aliases[key].add(str(extra))
            name = str(meta.get("name") or "").strip()
            if name:
                aliases[key].add(name)
                aliases[key].add(re.sub(r"\s*\(.*?\)\s*", "", name).strip())
        first: dict[str, set[str]] = defaultdict(set)
        for key, names in aliases.items():
            for n in list(names):
                w = n.split()[0] if n.split() else ""
                if len(n.split()) > 1 and len(w) >= 4 and w.isalpha() and w[0].isupper() and w not in GENERIC:
                    first[w].add(key)
        bench = next((k for k, m in cfg["symbols"].items() if m.get("role") == "benchmark"), None)
        for w, keys in first.items():
            if len(keys) == 1:
                aliases[next(iter(keys))].add(w)
            elif bench in keys:          # "Nifty" alone means the benchmark (Nifty 50), not Nifty Bank
                aliases[bench].add(w)
        if bench:
            for w in (cfg["symbols"][bench].get("name") or "").split()[:1]:
                if w in GENERIC and w.isalpha():
                    aliases[bench].add(w)
        self.patterns = {k: re.compile("|".join(rf"(?<![\w&]){re.escape(a)}(?![\w&])"
                                                for a in sorted(v, key=len, reverse=True) if a))
                         for k, v in aliases.items()}
        self.mask_names = sorted({a for v in aliases.values() for a in v if any(c.isdigit() for c in a) or len(a) > 2}
                                 | EXTRA_NAMES, key=len, reverse=True)

    def find(self, text: str) -> set[str]:
        return {k for k, p in self.patterns.items() if p.search(text)}


class Pool:
    """Source numbers by scope (None = market level, an entity key, or ("id", <evidence id>)) and kind."""

    def __init__(self, ents: Entities):
        self.ents = ents
        self._raw: dict = defaultdict(lambda: {"pct": set(), "plain": set()})
        self._sorted: dict | None = None
        self.notes: list[str] = []     # sources that could not be read (validate.py info.number_sources)

    def add(self, scope, kind: str, value) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if math.isfinite(v):
            self._raw[scope][kind].add(round(abs(v), 10))
            self._sorted = None

    def add_text(self, text: str, scope_by_line: bool = True, scope=None, pct_sections: bool = False) -> None:
        """Numbers in a source text. Each line is scoped to the entities it names (none: market level);
        with pct_sections, bare numbers under a heading that says "in %" also count as percentages."""
        in_pct = False
        for line in text.splitlines():
            if line.startswith("#"):
                in_pct = pct_sections and "in %" in line
            scopes = [scope] if not scope_by_line else (sorted(self.ents.find(line)) or [None])
            for n in numbers(line, self.ents.mask_names):
                for s in scopes:
                    self.add(s, n["kind"], n["value"])
                    if in_pct and n["kind"] == "plain":
                        self.add(s, "pct", n["value"])

    def add_rows(self, rows: list[dict], scope_col: str | None) -> None:
        """Stored rows: fraction columns as percentages (x100), other numbers as plain numbers."""
        for r in rows:
            s = None
            if scope_col and r.get(scope_col):
                s = str(r[scope_col]).split(":")[0]   # quotes "HDFCBANK:ADR" -> HDFCBANK
            for c, v in r.items():
                if c == scope_col or isinstance(v, bool) or v is None:
                    continue
                if isinstance(v, Real):
                    if c in FRACTION_COLS:
                        self.add(s, "pct", v * 100)
                    else:
                        self.add(s, "plain", v)

    def add_json(self, obj, scope=None) -> None:
        """Numbers anywhere in a JSON value (collector summaries): plain, or from strings."""
        if isinstance(obj, dict):
            for v in obj.values():
                self.add_json(v, scope)
        elif isinstance(obj, list):
            for v in obj:
                self.add_json(v, scope)
        elif isinstance(obj, Real) and not isinstance(obj, bool):
            self.add(scope, "plain", obj)
        elif isinstance(obj, str):
            self.add_text(obj, scope_by_line=False, scope=scope)

    def _index(self):
        if self._sorted is None:
            self._sorted = {s: {k: sorted(v) for k, v in d.items()} for s, d in self._raw.items()}
        return self._sorted

    def scopes_for(self, sentence: str, line: str) -> list:
        ents = self.ents.find(sentence) or self.ents.find(line)
        ids = set(IDS.findall(sentence)) or set(IDS.findall(line))
        return [None, *sorted(ents)] + [("id", i) for i in sorted(ids)]

    def has(self, n: dict, scopes) -> bool:
        idx = self._index()
        x, t = n["value"], n["tol"]
        for s in scopes:
            vals = idx.get(s, {}).get(n["kind"], [])
            j = bisect.bisect_left(vals, x - t)
            if j < len(vals) and vals[j] <= x + t:
                return True
        return False


def unmatched(lines: list[str], pool: Pool, small_int: int) -> list[dict]:
    """Numbers in narrative lines with no same-kind source number in the sentence's scope."""
    bad = []
    for line in lines:
        for sentence in SENTENCE.split(line):
            scopes = pool.scopes_for(sentence, line)
            for n in numbers(sentence, pool.ents.mask_names, small_int):
                if not pool.has(n, scopes):
                    bad.append({**n, "line": line.strip(), "sentence": sentence.strip(),
                                "entities": sorted(pool.ents.find(sentence) or pool.ents.find(line))})
    return bad


def collector_summaries(pool: Pool, paths) -> None:
    for p in paths:
        try:
            pool.add_json(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as e:
            pool.notes.append(f"collector summary {p.name} unreadable ({e})")
