"""Illustrative portfolio-volatility scenarios for design section 8.2 (run from scripts/: PYTHONPATH=. python plan_volatility.py).

Method (canonical, v16): the market's watchlist companies; `bars` view, 1 Oct 2024 - 9 Oct 2026; the SESSION PANEL =
the dates on which every one of those companies has a stored close (dates where only some have a bar are dropped,
not treated as gaps); daily simple returns from consecutive panel dates; 2,000 random draws (NumPy default_rng seed 0)
of 6 distinct companies split into two disjoint 3-stock equal-weight portfolios A and B; report the mean over draws of
sd(A), sd(A - B) and corr(A, B), in percent."""
import numpy as np
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market

for market in ("india", "us"):
    con = connect(market)
    tickers = list(load_market(market)["tickers"])
    df = con.execute("select ticker, date, close from bars where date >= '2024-10-01' and date <= '2026-10-09'").df()
    panel = df.pivot(index="date", columns="ticker", values="close").sort_index()[tickers]
    sessions = panel.dropna()
    returns = sessions.pct_change().iloc[1:]
    rng = np.random.default_rng(0)
    sd_a, sd_diff, corr = [], [], []
    for _ in range(2000):
        pick = rng.choice(len(tickers), 6, replace=False)
        a = returns.iloc[:, pick[:3]].mean(axis=1)
        b = returns.iloc[:, pick[3:]].mean(axis=1)
        sd_a.append(a.std()); sd_diff.append((a - b).std()); corr.append(np.corrcoef(a, b)[0, 1])
    print(market, "dates", len(panel), "session panel", len(sessions),
          "sd(A) %.4f%%  sd(A-B) %.4f%%  corr %.4f" % (np.mean(sd_a) * 100, np.mean(sd_diff) * 100, np.mean(corr)))
