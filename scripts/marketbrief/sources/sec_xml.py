"""XML helpers for the SEC documents the collectors read (Form 4, 13D/13G, 13F): path text, flags, dates."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

TRUE_FLAGS = ("1", "true", "y", "yes")
US_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")
ISO_DATE_LENGTH = 10


def raw_doc(primary_doc: str) -> str:
    """Form 4 / 13D / 13G primary documents are listed as an XSL rendering
    ("xslF345X06/form4.xml"); the raw XML is the same file without the XSL folder."""
    return primary_doc.split("/", 1)[1] if primary_doc.startswith("xsl") and "/" in primary_doc else primary_doc


def xml_root(data: bytes) -> ET.Element:
    """Parse XML and drop namespaces so paths read like the plain tag names."""
    root = ET.fromstring(data)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def xml_text(element: ET.Element | None, path: str) -> str | None:
    """The stripped text at `path` below an element, or None when the element or the text is missing."""
    if element is None:
        return None
    value = element.findtext(path)
    value = value.strip() if value else None
    return value or None


def xml_flag(value: str | None) -> bool | None:
    """True for 1/true/y/yes (any case), False for other text, None when missing."""
    if value is None:
        return None
    return value.strip().lower() in TRUE_FLAGS


def parse_us_date(value: str | None) -> str | None:
    """MM/DD/YYYY (13D/13G cover pages) or ISO -> ISO date string."""
    if not value:
        return None
    for fmt in US_DATE_FORMATS:
        try:
            return datetime.strptime(value.strip()[:ISO_DATE_LENGTH], fmt).date().isoformat()
        except ValueError:
            pass
    return None
