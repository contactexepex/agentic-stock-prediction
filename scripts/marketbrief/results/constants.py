"""Names, enums and messages of the results digests (WS6; docs/ws/ws6.md)."""

from __future__ import annotations

import re

KIND_RESULTS_DIGESTS = "results_digests"
FILE_RESULTS_CONFIG = "results.yaml"
METHOD_VERSION_RESULTS = "ws6-r1"
DEFAULT_INPUTS = "work/results_inputs.jsonl"
DEFAULT_DRY_TEXTS = "work/results_texts.jsonl"

# release kinds
KIND_RESULTS, KIND_CONCALL = "results", "concall"
RELEASE_KINDS = (KIND_RESULTS, KIND_CONCALL)

# digest status: ok (bullets stored), no_bullets (the agent found nothing to quote), text_unavailable (no stored
# primary text to quote), transcript_unavailable (US: no call text filed with the SEC; India: no transcript filed)
STATUS_OK, STATUS_NO_BULLETS = "ok", "no_bullets"
STATUS_TEXT_UNAVAILABLE, STATUS_TRANSCRIPT_UNAVAILABLE = "text_unavailable", "transcript_unavailable"
AUTO_STATUSES = (STATUS_TEXT_UNAVAILABLE, STATUS_TRANSCRIPT_UNAVAILABLE)

# numbers status: ok, pending_report (US: the quarter's 10-Q/10-K is not filed yet), unavailable
NUMBERS_OK, NUMBERS_PENDING, NUMBERS_UNAVAILABLE = "ok", "pending_report", "unavailable"

# consensus status: the newest Yahoo consensus collected before the release, or none (the surprise is context only)
CONSENSUS_BEFORE, CONSENSUS_NONE = "before_release", "none_before_release"
CONTEXT_ONLY = "context only"
SURPRISE_VS_YAHOO, SURPRISE_VS_FILED = "yahoo_reported_vs_consensus", "filed_eps_vs_consensus"

# release time basis
TIME_FILED, TIME_ACCEPTED, TIME_DATE_ONLY = "nse_filed_at", "sec_accepted_at", "date_only"

# text sources
SOURCE_SEC, SOURCE_NSE = "sec", "nse"
SOURCE_KIND_FILING, SOURCE_KIND_ANNOUNCEMENT, SOURCE_KIND_ATTACHMENT = "filing", "announcement", "attachment"
DOC_ATTACHMENT = "attachment"
NSE_ARCHIVE_PREFIX = "https://nsearchives.nseindia.com/"
TEXT_SUFFIXES = (".txt", ".xml", ".htm", ".html")
PDF_SUFFIX = ".pdf"
PDF_PARSER_PYPDF = "pypdf"
ATTACH_PDF_NOT_PARSED, ATTACH_NOT_ARCHIVE, ATTACH_UNSUPPORTED = "pdf_not_parsed", "not_nse_archive", "unsupported_type"
CONCALL_HEAD_CHARS = 3000

# agent record fields
AGENT_FIELDS = ("release_id", "kind", "bullets", "prompt_version")
BULLET_FIELDS = ("topic", "text", "quote", "source_id")
PROMPT_VERSION_PATTERN = r"results-v\d+"
# words the agent's own text may not use: the digest reports, it never predicts prices or recommends trades
ADVICE_WORDS = re.compile(
    r"\b(buy|sell|recommend\w*|price target|target price|outperform|underperform|overweight|underweight|"
    r"stock (?:will|should|could)|shares (?:will|should|could))\b",
    re.I,
)
DISCLAIMER = "Research only; not investment advice. Paper only — no proven edge yet."

MSG_NOT_DUE = "release_id {release_id!r} is not a current release with text to quote"
MSG_KIND_MISMATCH = "kind {kind!r} does not match release {release_id!r} ({expected})"
MSG_REPEATED = "release {release_id!r} appears twice in the file"
MSG_SOURCE = "source_id {source_id!r} is not a stored text of release {release_id!r}"
MSG_QUOTE = "quote not found verbatim in the stored text of {source_id}"
MSG_NUMBER = "numbers in text neither in the quote nor among the release's numbers: {numbers}"
MSG_ADVICE = "text must not predict prices or recommend trades (found {word!r})"
