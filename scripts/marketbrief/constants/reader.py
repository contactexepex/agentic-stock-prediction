"""Constants of the reader's daily HTML report (presentation/reader/; C2, 2026-10-10): the horizons it shows, the
lean thresholds and every plain-language phrase the page builds from stored numbers. Research only: no phrase reads
as advice ("lean up / lean down", never "buy" or "sell")."""
from __future__ import annotations

READER_HORIZONS = (1, 3, 5)          # N+1, N+3, N+5 per company card (owner request, 2026-10-10), of the
                                     # configured horizons only (reader.forecasts.shown_horizons)
INDEX_LOOKBACK_DAYS = 30            # calendar days of benchmark closes read for the 1- and 5-session change
HISTORY_SESSIONS = 20                # closes drawn before the fan
NEWS_LOOKBACK_DAYS = 4               # contradicted-news flag: items first seen this many days before the cut-off
EARNINGS_SOON_DAYS = 5               # "results soon" flag: days_to_earnings at most this
TOP_MOVES = 3                        # biggest expected moves shown at the top
TOP_CHANGES = 5                      # biggest target moves listed under "What changed"
CHANGE_MIN_TARGET_PCT = 0.5          # a target move (percent) worth listing
CHANGE_MIN_PROB_PTS = 0.02           # a P(up) move (fraction) worth listing
NEW_NEWS_LIMIT = 5                   # new news items listed under "What changed"
MIN_DRIVER_POINTS = 0.05             # a feature group's points that count as a reason

# lean of the signal model's P(up): distance from 0.5
LEAN_CLEAR = 0.05                    # >= this: "Lean up / down"
LEAN_SLIGHT = 0.02                   # >= this: "Slight lean"; below: "No clear lean"
LEAN_UP, LEAN_DOWN, LEAN_NONE = "up", "down", "none"
STRENGTH_CLEAR, STRENGTH_SLIGHT, STRENGTH_NONE = "clear", "slight", "none"

MOOD_WORDS = {"CALM": "Calm", "TRENDING": "Trending", "EVENT_HEAVY": "Event-heavy", "UNSTABLE": "Unstable"}

# the model's feature groups (model/explain.py) in plain words. A group's points are its push on the model's estimate
# (coefficient x feature), not the state of the market (a falling price can push the estimate up), so the why line
# names the group and its push only: "<label> push(es) the chance up/down"
GROUP_LABELS = {   # group -> (label, plural)
    "news": ("recent verified news", False),
    "momentum": ("the model's price-trend signals", True),
    "market": ("the model's whole-market signals", True),
    "oscillator": ("the model's short-term price signals", True),
    "regime": ("the market mood", False),
    "relative strength": ("the model's relative-strength signals (vs the sector and the market)", True),
    "volatility": ("the model's price-swing signals", True),
    "volume": ("the model's trading-volume signals", True),
}
GROUP_FALLBACK = "the model's {group} signals"
GROUP_PUSH = "{label}{items} {verb} the chance {side}"
GROUP_BASELINE = "baseline"

WHY_NO_SCORE = "No model score for this horizon today."
WHY_NO_SIGNAL = "No strong signal: the model stays close to the usual odds ({base} of past cases went up)."
WHY_MAIN = "{lean} mainly because {reason}"
WHY_COUNTER = "; on the other side, {reason}"
WHY_BASELINE = "{lean}, mostly from the usual odds (in the past {base} of such cases went up)"
WHY_ALSO = "; also {reason}"
WHY_NEWS_ITEMS = " ({n} item{s})"
LEAN_PHRASE = {(LEAN_UP, STRENGTH_CLEAR): "Leans up", (LEAN_DOWN, STRENGTH_CLEAR): "Leans down",
               (LEAN_UP, STRENGTH_SLIGHT): "Leans slightly up", (LEAN_DOWN, STRENGTH_SLIGHT): "Leans slightly down",
               (LEAN_NONE, STRENGTH_NONE): "No clear lean"}

FLAG_EARNINGS, FLAG_BLOCKED, FLAG_CONTRADICTED, FLAG_INACTIVE_DATA = "earnings", "blocked", "contradicted", "no_data"
FLAG_TEXT = {
    FLAG_EARNINGS: "Results in {days} day{s}: prices can jump",
    FLAG_BLOCKED: "Data problem: no forecast is trusted today",
    FLAG_CONTRADICTED: "Some recent news was contradicted by other sources",
}
EARNINGS_TODAY = "Results today or tomorrow: prices can jump"

# B2/WS4 signal tiers in lean words (never "buy" or "sell" on the reader's page)
TIER_WORDS = {"Strong Buy": "Strong lean up", "Buy": "Lean up", "Hold/No call": "No lean", "Sell": "Lean down",
              "Strong Sell": "Strong lean down"}
SIMULATED = "SIMULATED"
PAPER_NOT_LIVE = "Paper trading (simulated, no real money) starts on {day}."
PAPER_NO_START = "Paper trading (simulated, no real money) has no start date yet."
