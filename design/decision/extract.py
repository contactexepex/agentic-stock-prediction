"""Extract per-day HDFCBANK rows for the decision page: rule-replay ranges (1d/5d), walk-forward
out-of-sample model probabilities (1d/5d open_to_close) and the live rows. Writes only to the scratch dir."""
import json, sys, os
from datetime import date
sys.path.insert(0, "/home/user/agentic-stock-prediction/scripts")
import pandas as pd
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market, load_ranges_config
from marketbrief.replay.rule_replay.inputs import load_inputs
from marketbrief.replay.rule_replay.range_rows import replay_rows
from marketbrief.model.settings import load_model_config
from marketbrief.model.panel import build_panel
from marketbrief.model.panel_inputs import read_inputs
from marketbrief.model.walk_forward import walk_forward

OUT = os.path.dirname(os.path.abspath(__file__))
T = "HDFCBANK"
START, END = date(2026, 8, 17), date(2026, 10, 6)

cfg = load_market("india")
rc = load_ranges_config()
con = connect("india")

# 1. rule replay ranges per day
bars, extra = load_inputs(cfg, rc, con)
res, reg = replay_rows(cfg, rc, bars, extra, START, END)
rows = {}
for h, frame in res.items():
    f = frame[frame["ticker"] == T].copy()
    f = f.sort_values(f.columns[0])
    rows[str(h)] = json.loads(f.to_json(orient="records", date_format="iso"))
    print("replay horizon", h, len(f), list(f.columns))
reg_out = {str(k.date() if hasattr(k, "date") else k): v for k, v in reg["regime"].items()} if "regime" in reg else {}
print("regime cols", list(reg.columns))

# 2. walk-forward OOS probabilities
settings = load_model_config()
inputs = read_inputs(con, "india")
panel = build_panel(cfg, inputs, settings["warmup_bars"])
oos = {}
for h in (1, 5):
    o, fits = walk_forward(panel, ("india", "open_to_close", h), settings)
    f = o[(o["ticker"] == T) & (o["date"] >= pd.Timestamp(START)) & (o["date"] <= pd.Timestamp(END))].copy()
    f = f.sort_values("date")
    oos[str(h)] = json.loads(f.to_json(orient="records", date_format="iso"))
    print("oos horizon", h, len(f), list(f.columns), "fits", len(fits), "last cutoff", fits[-1].cutoff)

json.dump({"replay": rows, "regime": reg_out, "oos": oos,
           "regime_frame": json.loads(reg.reset_index().to_json(orient="records", date_format="iso"))},
          open(os.path.join(OUT, "hdfcbank_history.json"), "w"), indent=0, default=str)
print("written")
