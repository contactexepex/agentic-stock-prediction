"""The backtest page of the signal model: one self-contained HTML file from the backtest JSON (no network)."""
from __future__ import annotations

import html

STYLE = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--good:#1a7f37;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--muted:#aaa;--line:#333;--good:#5fd38d;--bad:#ff7b72}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;
padding:16px}
table{border-collapse:collapse;margin:8px 0 16px;font-variant-numeric:tabular-nums;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:3px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}
h2{margin-top:32px}.muted{color:var(--muted)}code{font-size:12px}
"""


def esc(value) -> str:
    """HTML-escaped text; None as a dash."""
    return "–" if value is None else html.escape(str(value))


def table(header: list[str], rows: list[list]) -> str:
    """A plain HTML table."""
    head = "".join(f"<th>{esc(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def scores_table(by_spec: dict) -> str:
    """Brier, log loss and AUC per horizon and convention."""
    rows = [[key, res.get("n"), f"{res.get('first_date')} .. {res.get('last_date')}", res.get("up_share"),
             res.get("brier"), res.get("brier_base_rate"), res.get("brier_skill"), res.get("log_loss"),
             res.get("log_loss_base_rate"), res.get("auc"), res.get("auc95"), res.get("calibrated_share"),
             (res.get("gbm_comparison") or {}).get("auc"), (res.get("gbm_comparison") or {}).get("brier")]
            for key, res in sorted(by_spec.items()) if "brier" in res]
    return table(["horizon / label", "n", "as-of dates", "up share", "Brier", "Brier base rate", "Brier skill",
                  "log loss", "log loss base rate", "AUC", "AUC 95%", "calibrated share", "GBM AUC", "GBM Brier"],
                 rows)


def reliability_table(res: dict) -> str:
    """Reliability bins of one result."""
    return table(["p bin", "n", "mean p", "up share", "Wilson 95%"],
                 [[b["bin"], b["n"], b["mean_p"], b["up_share"], b["wilson95"]] for b in res["reliability"]])


def thresholds_table(res: dict) -> str:
    """Hit rates and coverage at each threshold."""
    rows = []
    for threshold, sides in res["thresholds"].items():
        long, short = sides["long"], sides["short"]
        rows.append([threshold, long["n"], long["coverage"], long["hit_rate"], long["wilson95"],
                     long["hit_after_cost"], short["n"], short["coverage"], short["hit_rate"], short["wilson95"]])
    return table(["t", "long n", "long coverage", "long hit", "long 95%", "long hit after cost", "short n",
                  "short coverage", "short hit", "short 95%"], rows)


def paper_tables(paper: dict) -> str:
    """Baselines, model long and the differences, and sell-if-held, all in % per date after costs."""
    base = table(["baseline (after costs)", "dates", "positions", "mean % per date", "95%"],
                 [[k, v["dates"], v["positions"], v["mean_pct"], v["ci95_pct"]] for k, v in paper["baselines"].items()])
    rows, diffs, sells = [], [], []
    for threshold, block in paper["thresholds"].items():
        long = block["long"]
        rows.append([threshold, long["dates"], long["positions"], long["gross_mean_pct"], long["mean_pct"],
                     long["ci95_pct"]])
        diffs += [[threshold, k, v["dates"], v["mean_pct"], v["ci95_pct"]] for k, v in block["vs"].items()]
        sell = block["sell_if_held"]
        sells.append([threshold, sell["gross"]["positions"], sell["gross"]["mean_pct"], sell["gross"]["ci95_pct"],
                      sell["net_of_round_trip"]["mean_pct"], sell["net_of_round_trip"]["ci95_pct"]])
    return (f"<p class=muted>Mean round-trip cost {esc(paper['mean_cost_pct'])}% per position.</p>" + base
            + table(["t", "dates", "positions", "gross mean %", "net mean % per date", "95%"], rows)
            + table(["t", "model minus", "common dates", "mean % per date", "95%"], diffs)
            + "<p class=muted>Sell if held (p &le; 1 - t): the return a holder avoids; not a short sale.</p>"
            + table(["t", "positions", "avoided gross %", "95%", "avoided net of round trip %", "95%"], sells))


def model_tables(model: dict) -> str:
    """The latest fit's coefficients, group importance and excluded features."""
    coefficients = table(["feature", "group", "coefficient (logit per 1 sd)", "training mean", "training sd"],
                         [[c["feature"], c["group"], c["coefficient"], round(c["mean"], 5), round(c["sd"], 5)]
                          for c in model["coefficients"]])
    importance = table(["group", "sum |coefficient|"], [[k, v] for k, v in model["group_importance"].items()])
    excluded = table(["excluded feature", "reason"], [[k, v] for k, v in model["excluded"].items()])
    head = (f"<p>{model['fits']} monthly fits, {model['first_cutoff']} .. {model['last_cutoff']}; latest: "
            f"{model['last_train_rows']} training rows, base rate {model['last_base_rate']}, intercept "
            f"{model['last_intercept']}, Platt (slope, offset) {esc(model['last_platt'])}.</p>")
    return head + coefficients + importance + excluded


def render_html(result: dict) -> str:
    """The whole page."""
    parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
             f"content='width=device-width,initial-scale=1'><title>Signal model backtest</title><style>{STYLE}"
             f"</style></head><body><h1>Signal model backtest</h1><p class=muted>Computed {esc(result['computed_at'])}"
             ". Walk-forward, expanding window, monthly refit, out-of-sample only. Research only; not advice.</p>"
             "<h2>Verdicts</h2><pre>" + esc("\n".join(result["verdicts"])) + "</pre>"]
    for market, by_spec in result["results"].items():
        parts.append(f"<h2>{esc(market)}</h2><p class=muted>{esc(result['data'][market])}</p>")
        parts.append(scores_table(by_spec))
        for key, res in sorted(by_spec.items()):
            if "brier" not in res:
                continue
            parts.append(f"<h3>{esc(market)} {esc(key)}</h3><p class=muted>{esc(res['label'])}</p>")
            parts.append(reliability_table(res) + thresholds_table(res))
            if "paper" in res:
                parts.append(paper_tables(res["paper"]))
            parts.append(model_tables(res["model"]))
    return "".join(parts) + "</body></html>"
