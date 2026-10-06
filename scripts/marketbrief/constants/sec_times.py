"""Constants of the SEC acceptance-time check: the stored kinds it reads, their SQL and the row source name."""
COLLECTOR_SEC_TIMES = "sec_times"
SOURCE_SGML_HEADER = "sgml_header"
WRONG_ROWS_LIMIT = 50
ERROR_TEXT_LIMIT = 200
MSG_NO_HEADER_TIME = "no ACCEPTANCE-DATETIME in header"

# kind -> SQL giving (accession, cik folder, stored accepted_at) of its rows, read raw from the files
SEC_TIME_SOURCES = {
    "filings": "SELECT id AS accession, cik, accepted_at, url FROM {source_relation}",
    "insiders": "SELECT accession, issuer_cik AS cik, accepted_at, url FROM {source_relation}",
    "stakes": "SELECT id AS accession, issuer_cik AS cik, accepted_at, url FROM {source_relation}",
    "holdings": "SELECT accession, filer_cik AS cik, accepted_at, url FROM {source_relation}",
    "fundamentals": "SELECT accession, cik, accepted_at, NULL AS url FROM {source_relation}",
}
SEC_TIME_ONLY_ACCEPTED = " WHERE accepted_at IS NOT NULL"
SEC_TIME_CHECKED_SQL = "SELECT DISTINCT accession FROM sec_times"
