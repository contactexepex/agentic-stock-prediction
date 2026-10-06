"""Names of the stored data kinds (data/<market>/<kind>/...) and their file formats."""
KIND_NEWS = "news"
KIND_FUNDAMENTALS = "fundamentals"
KIND_SEC_TIMES = "sec_times"

NEWS_STORED_VIEW = "news_stored"   # the view over the stored news rows; `news` re-tags them (views.sql)
FILE_FORMAT_JSONL = "jsonl"
