"""Constants of the news-only light run (marketbrief/pipeline/news_light_run.py, routine/NEWS_PROMPT.md)."""
STEP_NEWS_LIGHT_RUN = "news_light_run"
INDIA = "india"
# (summary name in work/steps/, [script in scripts/, arguments...])
NEWS_STEP = ("collect_news", ("collect_news.py",))
NSE_STEP = ("collect_nse_india", ("collect_nse_india.py", "--only", "announcements"))
ARTICLES_STEP = ("collect_articles", ("collect_articles.py",))
CLUSTERS_STEP = ("news_clusters", ("news_clusters.py",))
VALIDATE_STEP = ("validate_news_collect", ("validate.py", "--stage", "news_collect"))
