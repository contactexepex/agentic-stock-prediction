"""Levels, signals, notes and grids of the rule-based replay (replay.py)."""

from __future__ import annotations

LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)  # calibration curve (stated coverage)

SIGNALS = ("always_up", "momentum_1d", "momentum_5d", "rsi_reversion")

SIGNAL_LABELS = {
    "always_up": "Always up",
    "momentum_1d": "1-day momentum",
    "momentum_5d": "5-day momentum",
    "rsi_reversion": "RSI(14) mean reversion",
}

RSI_LOW, RSI_HIGH = 30.0, 70.0

DEFAULT_LEVELS = {"q10": 0.10, "q25": 0.25, "q75": 0.75, "q90": 0.90}  # fixed band quantiles (ACI off)

MIN_MONTH_DAYS = 5  # the coverage-over-time chart leaves out months with fewer as-of days (kept in the JSON)

LIMITATIONS = [
    "No AI: the forecaster's drift and widening are judged only live (the model may have seen past prices).",
    "No overnight own-stock cue: pre-market gaps (US) and ADR moves (India) have no stored history, and the "
    "next open would be look-ahead.",
    "Implied volatility has no stored history and is off in config/ranges.yaml.",
    "The vol index level is the as-of close; live runs use the pre-open quote.",
    "The calibration pool holds stored history only (no live scored ranges, which include AI changes).",
    "Relationship and smart-money widening are off in config/ranges.yaml and not replayed.",
    "Past earnings and ex-dividend dates are treated as known in advance (they are scheduled); a backfilled "
    "row does not say when its date was first announced.",
    "Confidence intervals are clustered by date blocks (all stocks share a day; 5-day outcomes overlap), "
    "so they are wider than a naive binomial interval.",
]

SCORE_NOTE = (
    "Score = interval score: the 80% range's width plus a penalty when the price lands outside it, in % of "
    "the price; lower is better. Naive = a simple range of last close +/- the last 20 days' typical move."
)

CI_NOTE = (
    "95% interval = the span the true rate most likely lies in, allowing for stocks moving together on the same day."
)

CMP_KEYS = ("n", "cover50", "cover80", "width50_pct", "width80_pct", "score50", "score80", "qs_pct")

ACI_GRID = tuple((g, br) for g in (0.002, 0.005, 0.01, 0.02) for br in (False, True))  # held-out tuning grid

MIN_EWMA_BARS = 31  # ranges.py needs an EWMA volatility of 31 bars

# ---------- rule replay: cli ----------
MSG_ACI_GAMMA_ACI_BY_REGIME_AND = "--aci-gamma, --aci-by-regime and --aci-tune-end need --aci"
MSG_NO_TRADING_DAYS_IN_THE_WINDOW = "no trading days in the window"
