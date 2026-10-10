"""Plain-language meaning of one company's stored numbers for the reader's report: the lean of the signal model's
P(up), a one-line "why" built from the score's points per feature group (model/explain.py), and the flags (results
soon, BLOCKED data, contradicted news). Pure functions of stored values: nothing is estimated here."""
from __future__ import annotations

from marketbrief.analytics import scoring
from marketbrief.constants import reader as text


def lean(prob_up: float | None) -> tuple[str, str]:
    """(side, strength) of a P(up): side up/down/none, strength clear/slight/none (constants LEAN_CLEAR/SLIGHT)."""
    if prob_up is None:
        return text.LEAN_NONE, text.STRENGTH_NONE
    distance = abs(prob_up - 0.5)
    if distance < text.LEAN_SLIGHT:
        return text.LEAN_NONE, text.STRENGTH_NONE
    side = text.LEAN_UP if prob_up > 0.5 else text.LEAN_DOWN
    return side, text.STRENGTH_CLEAR if distance >= text.LEAN_CLEAR else text.STRENGTH_SLIGHT


def group_phrase(group: str, points: float, news_items: int | None) -> str:
    """One feature group's push on the model's estimate in plain words, with the item count for the news group:
    'recent verified news (6 items) pushes the chance down'."""
    label, plural = text.GROUP_LABELS.get(group, (text.GROUP_FALLBACK.format(group=group), True))
    items = text.WHY_NEWS_ITEMS.format(n=news_items, s="" if news_items == 1 else "s") \
        if group == "news" and news_items else ""
    return text.GROUP_PUSH.format(label=label, items=items, verb="push" if plural else "pushes",
                                  side="up" if points > 0 else "down")


def reasons(contributions: dict | None) -> list[tuple[str, float]]:
    """The feature groups (baseline left out) whose points reach MIN_DRIVER_POINTS, strongest first."""
    groups = (contributions or {}).get("groups") or {}
    rows = [(name, float(points)) for name, points in groups.items()
            if name != text.GROUP_BASELINE and points is not None and abs(float(points)) >= text.MIN_DRIVER_POINTS]
    return sorted(rows, key=lambda row: (-abs(row[1]), row[0]))


def why_line(score: dict | None) -> str:
    """'Leans down mainly because recent verified news is negative (34 items); on the other side, ...'."""
    if not score or score.get("prob_up") is None:
        return text.WHY_NO_SCORE
    side, strength = lean(score["prob_up"])
    contributions = score.get("contributions") or {}
    news_items = (contributions.get("news") or {}).get("items")
    rows = reasons(contributions)
    if side == text.LEAN_NONE or not rows:
        base = score.get("base_rate")
        line = text.WHY_NO_SIGNAL.format(base=scoring.percent(base) if base is not None else "about half")
        return line if side == text.LEAN_NONE else f"{text.LEAN_PHRASE[(side, strength)]}. {line}"
    sign = 1 if side == text.LEAN_UP else -1
    main = [row for row in rows if row[1] * sign > 0]
    counter = [row for row in rows if row[1] * sign < 0]
    baseline = float((contributions.get("groups") or {}).get(text.GROUP_BASELINE) or 0.0)
    base = score.get("base_rate")
    if base is not None and baseline * sign > 0 and (not main or abs(baseline) > abs(main[0][1])):
        # the usual odds of this horizon (the model's baseline) push the lean more than any signal
        line = text.WHY_BASELINE.format(lean=text.LEAN_PHRASE[(side, strength)], base=scoring.percent(base))
        if main:
            line += text.WHY_ALSO.format(reason=group_phrase(main[0][0], main[0][1], news_items))
    elif main:
        line = text.WHY_MAIN.format(lean=text.LEAN_PHRASE[(side, strength)],
                                    reason=group_phrase(main[0][0], main[0][1], news_items))
    else:
        line = text.LEAN_PHRASE[(side, strength)]
    if counter:
        line += text.WHY_COUNTER.format(reason=group_phrase(counter[0][0], counter[0][1], news_items))
    return line + "."


def flags(quality: str | None, days_to_earnings: int | None, contradicted: bool) -> list[dict]:
    """The card's warning chips: results soon, BLOCKED data, contradicted news."""
    out = []
    if days_to_earnings is not None and 0 <= days_to_earnings <= text.EARNINGS_SOON_DAYS:
        label = text.EARNINGS_TODAY if days_to_earnings <= 1 else text.FLAG_TEXT[text.FLAG_EARNINGS].format(
            days=days_to_earnings, s="" if days_to_earnings == 1 else "s")
        out.append({"code": text.FLAG_EARNINGS, "text": label})
    if quality == "BLOCKED":
        out.append({"code": text.FLAG_BLOCKED, "text": text.FLAG_TEXT[text.FLAG_BLOCKED]})
    if contradicted:
        out.append({"code": text.FLAG_CONTRADICTED, "text": text.FLAG_TEXT[text.FLAG_CONTRADICTED]})
    return out
