"""The reader's page without JavaScript (C2): the page reaches the owner as a file attached in Slack, and some phone
file viewers show HTML with scripts off. This renders the same embedded numbers as plain HTML inside <noscript>: the
20-second summary and one table per company (N+1/N+3/N+5 expected price, ranges, chance of going up, why, warnings).
Every value is escaped; nothing is recomputed (the same rows the script draws)."""
from __future__ import annotations

from html import escape

from marketbrief.analytics import scoring
from marketbrief.constants import reader as text

LEAN_WORDS = {"up": "lean up", "down": "lean down", "none": "no clear lean"}


def money(symbol: str, value) -> str:
    return "–" if value is None else f"{symbol}{value:,.2f}"


def signed(value, unit: str = "%") -> str:
    if value is None:
        return "–"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.2f}{unit}"


def lean_word(row: dict | None) -> str:
    if not row or row.get("prob_up") is None:
        return "no score"
    word = LEAN_WORDS[row["lean"]]
    return word.replace("lean", "slight lean") if row["strength"] == text.STRENGTH_SLIGHT else word


def summary(data: dict, horizon: int) -> str:
    reader, symbol = data["reader"], data.get("symbol", "")
    mood, bench = reader.get("mood"), reader.get("benchmark")
    glance = (reader.get("glance") or {}).get(str(horizon)) or {}
    by = {c["ticker"]: c for c in reader.get("companies", [])}
    names = {c["ticker"]: c.get("name", c["ticker"]) for c in data.get("companies", [])}
    parts = [f"<h2>The day in 20 seconds (N+{horizon})</h2><ul>"]
    if mood:
        parts.append(f"<li>Market mood: <b>{escape(mood['word'])}</b></li>")
    if bench and bench.get("change_pct") is not None:
        parts.append(f"<li>{escape(bench['name'])}: <b>{signed(bench['change_pct'])}</b> "
                     f"on {escape(bench['close_date'])}</li>")
    parts.append(f"<li>{glance.get('up', 0)} lean up · {glance.get('none', 0)} no clear lean · "
                 f"{glance.get('down', 0)} lean down</li>")
    for ticker in glance.get("moves", []):
        row = next((f for f in by[ticker]["forecasts"] if f["h"] == horizon), None)
        if row:
            parts.append(f"<li>Big expected move: {escape(names.get(ticker, ticker))} {signed(row['move_pct'])} to "
                         f"{money(symbol, row['target'])} by {escape(row['exit_label'] or '')}</li>")
    parts.append(f"<li><b>{escape(reader.get('paper_label') or '')}</b></li></ul>")
    return "".join(parts)


def company_table(company: dict, card: dict, horizon: int, symbol: str) -> str:
    rows = card["forecasts"]
    head = "".join(f"<th>N+{r['h']}</th>" for r in rows)
    line = lambda label, fn: f"<tr><th>{label}</th>" + "".join(f"<td>{fn(r)}</td>" for r in rows) + "</tr>"  # noqa: E731
    rng = lambda lo, hi: "–" if lo is None or hi is None else f"{lo:,.2f}–{hi:,.2f}"  # noqa: E731
    main = next((r for r in rows if r["h"] == horizon), rows[0] if rows else None)
    out = [f"<h3>{escape(company.get('name', card['ticker']))} ({escape(card['ticker'])}): {lean_word(main)}</h3>",
           f"<p>Last close {money(symbol, main['base_close'] if main else company.get('close'))}</p>"]
    if rows:
        out.append(f"<table><tr><th></th>{head}</tr>"
                   + line("Sell at close", lambda r: escape(r["exit_label"] or "–"))
                   + line("Expected", lambda r: money(symbol, r["target"]))
                   + line("50% range", lambda r: rng(r["lo50"], r["hi50"]))
                   + line("80% range", lambda r: rng(r["lo80"], r["hi80"]))
                   + line("Chance up", lambda r: "–" if r["prob_up"] is None else scoring.percent(r["prob_up"]))
                   + "</table>")
    if main:
        out.append(f"<p>{escape(main['why'])}</p>")
    out += [f"<p><b>Warning:</b> {escape(flag['text'])}</p>" for flag in card.get("flags", [])]
    return "".join(out)


def noscript_html(data: dict) -> str:
    """The <noscript> body for the page's data (view + narrative + reader)."""
    reader = data.get("reader") or {}
    horizon = reader.get("default_horizon")
    if not reader.get("companies") or horizon is None:
        return "<p>Open this file in a web browser to see the report.</p>"
    names = {c["ticker"]: c for c in data.get("companies", [])}
    cards = sorted(reader["companies"], key=lambda c: names.get(c["ticker"], {}).get("name", c["ticker"]))
    body = [summary(data, horizon), "<p>Ranges: the price should close inside the 80% range about 8 times in 10 and "
            "inside the 50% range about half the time. Chance up: the model's estimate; 50% is a coin flip. "
            "Open this file in a web browser for charts and filters.</p>"]
    body += [company_table(names.get(c["ticker"], {}), c, horizon, data.get("symbol", "")) for c in cards]
    return f'<div class="wrap noscript">{"".join(body)}</div>'
