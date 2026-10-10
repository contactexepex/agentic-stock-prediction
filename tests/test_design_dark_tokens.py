"""The design system's dark colour roles (design/system/dark_tokens.py, B7): current, AA, and only known token names."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "design" / "system"))
import dark_tokens  # noqa: E402


def test_dark_css_is_current_and_aa():
    assert dark_tokens.failures() == []
    assert dark_tokens.OUT.read_text(encoding="utf-8") == dark_tokens.css()


def test_dark_tokens_only_override_existing_names():
    tokens_css = (ROOT / "design" / "system" / "tokens.css").read_text(encoding="utf-8")
    light = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens_css))
    unknown = [name for name in dark_tokens.DARK if name.startswith("--") and name not in light]
    assert unknown == []


def test_every_checked_pair_names_dark_tokens():
    for fg, bg in dark_tokens.PAIRS:
        assert fg in dark_tokens.DARK and bg in dark_tokens.DARK


def test_contrast_formula():
    assert round(dark_tokens.contrast("#000000", "#ffffff"), 2) == 21.0
    assert round(dark_tokens.contrast("#5a5ee6", "#ffffff"), 1) == 5.0
