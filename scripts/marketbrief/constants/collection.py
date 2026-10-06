"""Thresholds shared by the collectors."""
# Yahoo collectors report a series as stale when its newest data is older than this many calendar
# days (cues and factors on other exchanges; the market's own symbols use its previous session).
STALE_DAYS = 7
