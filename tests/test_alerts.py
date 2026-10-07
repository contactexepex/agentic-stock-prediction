"""Slack notifications (B6; scripts/alerts.py, marketbrief/alerts/): each message type from W1's example records
(design/catalogue/), the empty days, long-message splitting, the day's thread, idempotent reruns and a token that
is never printed. Offline: a fake HTTP function stands in for Slack, and nothing is ever posted for real."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.alerts import cli, reads, text  # noqa: E402
from marketbrief.alerts.close import build_close, listed_rows, tally, trade_line  # noqa: E402
from marketbrief.alerts.client import SlackClient, SlackError  # noqa: E402
from marketbrief.alerts.constants import (  # noqa: E402
    MAX_MESSAGE_CHARS,
    MSG_NO_HEAD_TO_HEAD,
    MSG_NO_PICKS,
    MSG_NO_PREDICTIONS,
    MSG_NO_SETTLED,
    MSG_NO_STRONG,
    PAPER,
)
from marketbrief.alerts.intraday import build_alerts  # noqa: E402
from marketbrief.alerts.ledger import Ledger  # noqa: E402
from marketbrief.alerts.morning import agreement, build_morning, picks, strongest_other  # noqa: E402
from marketbrief.alerts.onboarding import onboarding_text, post_onboarding_confirmation  # noqa: E402
from marketbrief.alerts.publish import Message, NotConfiguredError, Publisher, post_brief, publisher  # noqa: E402
from marketbrief.alerts.weekly import build_weekly  # noqa: E402
from marketbrief.core import paths  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402

CATALOGUE = REPO / "design" / "catalogue"
TOKEN = "xoxb-test-0000-SECRET-never-printed"
HORIZONS = [1, 2, 3, 4, 5]
ADVICE = re.compile(r"\b(you should|we recommend|recommend(ed)?|must buy|buy now|sell now|guaranteed)\b", re.I)


def examples(name: str) -> list[dict]:
    return json.loads((CATALOGUE / f"{name}.json").read_text())["records"]


def of_market(rows: list[dict], market: str, **match) -> list[dict]:
    return [r for r in rows if r.get("market") == market and all(r.get(k) == v for k, v in match.items())]


def signal_lines(message: str) -> list[str]:
    """Lines that state a pick, a head-to-head trade, an alert or a settled trade."""
    return [line for line in message.splitlines() if re.match(r"^\s*(\d+\.|•)", line)
            and not line.lstrip().startswith(("• Rule:", "• AI:", "• No ", "• p-", "• Corroborated"))]


class FakeSlack:
    """chat.postMessage stand-in: records each call, answers ok with increasing ts (or the given failure)."""

    def __init__(self, fail_at: int | None = None, error: str = "channel_not_found"):
        self.calls: list[dict] = []
        self.fail_at, self.error = fail_at, error

    def __call__(self, url: str, data: bytes, headers: dict) -> tuple[int, bytes]:
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs(data.decode()).items()}
        self.calls.append({"url": url, "form": form, "auth": headers.get("Authorization")})
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            return 200, json.dumps({"ok": False, "error": self.error}).encode()
        return 200, json.dumps({"ok": True, "ts": f"1700000000.{len(self.calls):06d}"}).encode()


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A scratch repo root with the us/india configs, settings and the strategy registry."""
    root, config = tmp_path / "repo", tmp_path / "config"
    (config / "markets").mkdir(parents=True)
    for name in ("markets/us.yaml", "markets/india.yaml", "events.yaml", "settings.yaml", "strategies.yaml"):
        shutil.copy(REPO / "config" / name, config / name)
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "CONFIG", config)
    monkeypatch.delenv("MB_NOW", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)   # never reach a real webhook from a test
    return root


def store(root: Path, market: str, kind: str, rows: list[dict], time_key: str) -> None:
    for row in rows:
        day = str(row[time_key])[:10]
        path = root / "data" / market / kind / day[:4] / day[5:7] / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")


# ---------- message types from the W1 example records ----------

def test_agreement_matches_the_catalogue_example():
    preds = examples("prediction")
    expected = {(a["market"], a["ticker"], a["horizon_days"]): a for a in examples("agreement")}
    for market, ticker in (("india", "RELIANCE"), ("us", "NVDA")):
        for k in HORIZONS:
            row = agreement(of_market(preds, market), k)[0]
            want = expected[(market, ticker, k)]
            assert (row["ticker"], row["buy"], row["of"], row["by_family"]) == \
                   (ticker, want["buy"], want["of"], want["by_family"])
            assert row["avg_prob_up"] == pytest.approx(want["avg_prob_up"], abs=1e-4)


def test_morning_picks_from_examples():
    preds = of_market(examples("prediction"), "us")
    h2h = of_market(examples("head_to_head_pick"), "us", session_date="2026-10-07")
    names = {"NVDA": "NVIDIA", "rule.model_news.v1": "Model + news"}
    msg = build_morning("us", "2026-10-07", preds, h2h, HORIZONS, names)
    lines = msg.splitlines()
    assert lines[0] == "*US — morning paper picks for Wed 7 Oct 2026 (N+1)*"
    assert MSG_NO_STRONG in lines[1] and "Paper only" in lines[1]
    pick = lines[2]
    assert pick.startswith("1. *NVIDIA (NVDA)* [Paper] — 14 of 15 strategies buy at N+1 "
                           "(rule 7/8, baseline 3/3, AI 4/4)")
    assert "average P(up) 0.569" in pick and "$1,000.00 per trade" in pick and "last close $239.24" in pick
    # strongest other horizon: N+3 and N+5 both have 14 buyers; the shorter wins
    assert lines[3] == "   Strongest other horizon: N+3 (14 of 15, average P(up) 0.581)."
    trades = [line for line in lines if line.startswith("   • ")]
    assert len(trades) == 4
    assert trades[0].startswith("   • Rule, best expected gain: Model + news (rule.model_news.v1) at N+1, P(up) 0.566")
    assert "target $239.54" in trades[0] and "expected gain -1.16%" in trades[0]
    assert trades[3].startswith("   • AI, highest probability: ai.combined.opus.v1 at N+5, P(up) 0.615")
    assert all(PAPER in line for line in signal_lines(msg))
    assert not ADVICE.search(msg)


def test_strongest_other_ties_go_to_the_shorter_horizon_and_need_a_buyer():
    def call(k, qualifies, sid="s"):
        return {"id": f"{sid}-{k}", "ticker": "X", "horizon_days": k, "qualifies": qualifies, "family": "rule",
                "prob_up": 0.6}
    preds = [call(1, True), call(2, False), call(3, True), call(4, True), call(5, False)]
    assert strongest_other(preds, "X", HORIZONS)["horizon_days"] == 3
    assert strongest_other([call(1, True), call(2, False)], "X", HORIZONS) is None


def test_morning_empty_days():
    no_preds = build_morning("india", "2026-10-07", [], [], HORIZONS)
    assert MSG_NO_PREDICTIONS in no_preds and MSG_NO_STRONG in no_preds
    nobody = [{**p, "qualifies": False} for p in of_market(examples("prediction"), "india")]
    assert MSG_NO_PICKS in build_morning("india", "2026-10-07", nobody, [], HORIZONS)
    # HDFCBANK: two baselines buy, but neither family has a candidate -> no head-to-head trades
    hdfc = [{**p, "ticker": "HDFCBANK", "id": p["id"].replace("RELIANCE", "HDFCBANK"),
             "qualifies": p["family"] == "baseline" and p["horizon_days"] == 1}
            for p in of_market(examples("prediction"), "india")]
    h2h = of_market(examples("head_to_head_pick"), "india", ticker="HDFCBANK")
    msg = build_morning("india", "2026-10-07", hdfc, h2h, HORIZONS)
    assert [r["ticker"] for r in picks(hdfc)] == ["HDFCBANK"]
    assert f"   {MSG_NO_HEAD_TO_HEAD}" in msg.splitlines()
    assert "Strongest other horizon: no other horizon has a buyer." in msg


def feed_rows(checks: list[dict], computed_at: str | None = None) -> list[dict]:
    """B9's trade alerts (docs/ws/b9.md "The alerts feed") built from W1's example trade checks: one
    open_trade_flagged row per check and ticker with flagged trades."""
    rows = {}
    for c in (c for c in checks if c["flagged"]):
        row = rows.setdefault((c["check_id"], c["ticker"]), {
            "id": f"{c['check_id']}-{c['ticker']}-trades", "check_id": c["check_id"], "check_at": c["check_at"],
            "session_date": c["session_date"], "market": c["market"], "ticker": c["ticker"],
            "alert_type": "open_trade_flagged", "check_row_id": c["check_row_id"], "trade_ids": [], "trades": [],
            "flags": [], "repeat": False, "method_version": "tc-v1", "computed_at": computed_at or c["computed_at"]})
        row["trade_ids"].append(c["trade_id"])
        row["trades"].append({k: c[k] for k in ("trade_id", "strategy_id", "view", "horizon_days", "flags", "band",
                                                 "ret_since_entry_pct", "to_target_pct")} | {"target_reached": False})
        row["flags"] = sorted(set(row["flags"]) | set(c["flags"]))
    return list(rows.values())


NEWS = {"id": "ic-us-202610071627-NVDA-news-a41c9e07b2d35f18", "check_id": "ic-us-202610071627",
        "check_at": "2026-10-07T16:27:00Z", "session_date": "2026-10-07", "market": "us", "ticker": "NVDA",
        "alert_type": "material_news_open_trade", "check_row_id": "ic-us-202610071627-NVDA",
        "trade_ids": ["acc:rule.model_news.v1:2026-09-29-NVDA-5d"], "trades": None, "flags": [], "repeat": False,
        "news_id": "a41c9e07b2d35f18", "news_title": "Nvidia unveils new chip", "news_source": "Reuters",
        "news_status": "corroborated", "news_materiality": "high", "news_first_seen_at": "2026-10-07T15:00:00Z",
        "method_version": "tc-v1", "computed_at": "2026-10-07T16:27:00Z"}


def test_intraday_trade_alerts_from_b9_feed():
    checks = of_market(examples("trade_check"), "us")
    feed = feed_rows(checks)
    msg = build_alerts("us", feed, {"rule.model_news.v1": "Model + news"})
    head = f"*US — intraday check at 16:27 UTC: {len(feed)} companies with newly flagged open paper trades*"
    assert msg.splitlines()[0].startswith(head) and msg.splitlines()[1] == "Paper only — no proven edge yet."
    nvda = next(line for line in msg.splitlines() if "Model + news" in line)
    assert nvda == ("   – N+5 Model + news (rule.model_news.v1), accuracy view: +5.16% since entry, above its 80%"
                    " range, target already reached; flags: outside its predicted range [Paper]")
    assert "• *NVDA*: 2 flagged open paper trades [Paper]" in msg.splitlines()
    assert sum(len(r["trades"]) for r in feed) == sum(c["flagged"] for c in checks)
    assert len([x for x in msg.splitlines() if x.startswith("   – ")]) == sum(c["flagged"] for c in checks)
    assert all(PAPER in line for line in signal_lines(msg)) and "AAPL" not in msg   # AAPL is not flagged
    assert build_alerts("us", [{**r, "repeat": True} for r in feed]) is None        # already posted this session


def test_intraday_note_and_news_alert():
    feed = feed_rows(of_market(examples("trade_check"), "us"))
    noted = [{**r, "explanation": "NVDA rose with its sector.", "attribution": "sector", "cited_ids": ["XLK"]}
             if r["ticker"] == "NVDA" else r for r in feed]
    msg = build_alerts("us", noted + [NEWS])
    assert "   Note (sector): NVDA rose with its sector. [XLK]" in msg
    assert "1 news alert*" in msg.splitlines()[0]
    assert ('• *NVDA* news (corroborated, materiality high): "Nvidia unveils new chip" (Reuters)'
            ' [a41c9e07b2d35f18]; 1 open paper trade on it. [Paper]') in msg
    only_news = build_alerts("us", [{**r, "repeat": True} for r in feed] + [NEWS])
    assert "0 companies with newly flagged open paper trades, 1 news alert*" in only_news


def test_close_results_from_examples():
    rows = [r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01")]
    eod = {"id": "eod-us-2026-10-01", "summary": "Two paper trades settled."}
    msg = build_close("us", "2026-10-01", rows, eod, {}, "USD")
    rule_rows = [r for r in rows if r["view"] == "accuracy" and r["family"] == "rule"]
    rule = tally(rule_rows)
    assert rule["net_pnl"] == round(sum(r["net_pnl"] for r in rule_rows), 2)
    assert f"Rule {rule['trades']} trade" in msg
    assert "Analyst note (eod-us-2026-10-01): Two paper trades settled." in msg
    line = next(x for x in msg.splitlines() if "rule.model_news.v1, accuracy view" in x and "NVDA* N+1" in x)
    assert ("bought $229.27 on 2026-09-30, sold $230.86 on 2026-10-01; net +$4.60 (+0.46%) after $2.34 market"
            " costs") in line
    assert "target reached, closed inside its 80% range; main reason sector_lift" in line
    assert len(signal_lines(msg)) == len(rows)
    assert all(PAPER in line for line in signal_lines(msg))


def test_close_skipped_and_empty_days():
    skipped = [r for r in of_market(examples("paper_trade"), "india") if r["status"] == "skipped_price_above_amount"]
    assert skipped
    msg = build_close("india", "2026-10-06", skipped[:1])
    assert "no trade: one share costs more than the amount" not in msg   # not a win or loss: counted only
    assert "…and 1 more row settled today on the dashboard." in msg
    assert "no trade: one share costs more than the amount. [Paper]" in trade_line(skipped[0], {}, "INR")
    assert "Accuracy view: Rule 0 trades, 0 wins, net +₹0.00" in msg   # a skipped row is not a trade
    assert "Head-to-head: no head-to-head trades settled today." in msg
    empty = build_close("india", "2026-10-06", [])
    assert MSG_NO_SETTLED in empty and "Paper only" in empty


def test_weekly_and_onboarding_texts():
    msg = build_weekly("us", examples("research_review")[0], {}, "USD", "https://pages.example/")
    assert "*US — weekly research report 2026-W41* (2026-10-05 to 2026-10-09)" in msg
    assert "• Rule: rule.model_news.v1, net +$61.40 on 38 paper trades" in msg
    assert "[ni-us-2026-W41-product-corroborated-high-3]" in msg
    assert "p-2026-W41-1 (threshold, config/strategies.yaml, proposed)" in msg
    assert "Full report: https://pages.example/us/research-2026-W41.md" in msg
    accepted, refused = examples("command_log")[0], {**examples("command_log")[0], "result": "refused",
                                                     "refusal_code": "validation_failed", "record_ids": [],
                                                     "message": "SPY is an ETF; only common stocks can be added"}
    assert onboarding_text(accepted).startswith("Done: Microsoft (NASDAQ, Tech, CIK 0000789019)")
    assert onboarding_text(refused).startswith("Not done: SPY is an ETF; only common stocks can be added "
                                               "(validation_failed)")
    for message in (msg, onboarding_text(accepted)):
        assert not ADVICE.search(message)


# ---------- splitting, threads, idempotency ----------

def test_split_message_keeps_every_line_within_the_limit():
    body = "\n".join(f"• line {i} " + "x" * 80 for i in range(200))
    parts = text.split_message(body, 1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts)
    assert parts[1].startswith(f"(continued 2/{len(parts)})\n")
    rejoined = "\n".join(p.split("\n", 1)[1] if i else p for i, p in enumerate(parts))
    assert rejoined == body
    long_line = text.split_message("y" * 2500, 1000)
    assert all(len(p) <= 1000 for p in long_line) and "".join(p.split("\n", 1)[-1] for p in long_line) == "y" * 2500
    assert text.split_message("short") == ["short"]


def live(root: Path, http) -> Publisher:
    return Publisher("us", SlackClient(TOKEN, http), Ledger(root / "data" / "us" / "slack_posts"), "C123")


def test_day_thread_long_message_and_idempotent_rerun(scratch):
    http = FakeSlack()
    pub = live(scratch, http)
    long_text = "\n".join(f"• row {i} {PAPER} " + "z" * 100 for i in range(80))
    first = pub.publish(Message("morning", "morning:us:2026-10-07", long_text, "us:2026-10-07"))
    parts = first["parts"]
    assert parts == len(text.split_message(long_text)) > 1 and len(first["posted"]) == parts
    root_ts = "1700000000.000001"                                         # FakeSlack's first ts
    assert "thread_ts" not in http.calls[0]["form"]                       # the first part starts the thread
    assert {c["form"]["thread_ts"] for c in http.calls[1:]} == {root_ts}  # the rest reply into it
    assert all(len(c["form"]["text"]) <= MAX_MESSAGE_CHARS for c in http.calls)
    # later posts of the day go into the same thread; a rerun of any of them posts nothing
    alert = pub.publish(Message("alerts", "alerts:us:ic-1", "alert", "us:2026-10-07"))
    assert alert["thread_ts"] == root_ts and http.calls[-1]["form"]["thread_ts"] == root_ts
    calls = len(http.calls)
    again = live(scratch, http)   # a new run reads the ledger from data/
    assert again.publish(Message("morning", "morning:us:2026-10-07", long_text + "\nchanged", "us:2026-10-07"))[
        "posted"] == []
    assert again.publish(Message("alerts", "alerts:us:ic-1", "alert", "us:2026-10-07"))["posted"] == []
    assert len(http.calls) == calls
    # the next day starts a new thread
    pub.publish(Message("morning", "morning:us:2026-10-08", "next day", "us:2026-10-08"))
    assert "thread_ts" not in http.calls[-1]["form"]


def test_a_crash_midway_resumes_without_double_posting(scratch):
    long_text = "\n".join("w" * 200 for _ in range(60))
    parts = len(text.split_message(long_text))
    with pytest.raises(SlackError):
        live(scratch, FakeSlack(fail_at=2)).publish(Message("close", "close:us:2026-10-07", long_text, "us:2026-10-07"))
    http = FakeSlack()
    res = live(scratch, http).publish(Message("close", "close:us:2026-10-07", long_text, "us:2026-10-07"))
    assert res["skipped"] == ["close:us:2026-10-07#1"] and len(res["posted"]) == parts - 1
    assert {c["form"]["thread_ts"] for c in http.calls} == {"1700000000.000001"}   # the first run's part 1


@pytest.mark.usefixtures("scratch")
def test_onboarding_reply_goes_to_the_command_and_only_once(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", TOKEN)
    http = FakeSlack()
    command = examples("command_log")[0]
    first = post_onboarding_confirmation(command, "C999", "1699999999.000100", http=http)
    assert first["posted"] and http.calls[0]["form"]["thread_ts"] == "1699999999.000100"
    assert http.calls[0]["form"]["channel"] == "C999"
    assert post_onboarding_confirmation(command, "C999", "1699999999.000100", http=http)["posted"] == []
    pending = {**command, "result": "pending"}
    assert post_onboarding_confirmation(pending, "C999", "1699999999.000100", http=http)["posted"]


@pytest.mark.usefixtures("scratch")
def test_live_publisher_needs_token_and_channel():
    with pytest.raises(NotConfiguredError, match="SLACK_BOT_TOKEN and SLACK_WEBHOOK_URL not set"):
        publisher("us", dry_run=False, environ={})
    (paths.CONFIG / "settings.yaml").write_text("repo_url: x\n")
    with pytest.raises(NotConfiguredError, match="slack_channel_id"):
        publisher("us", dry_run=False, environ={"SLACK_BOT_TOKEN": TOKEN})


# ---------- the CLI on stored records ----------

def store_us_examples(root: Path) -> None:
    store(root, "us", "strategy_predictions", of_market(examples("prediction"), "us"), "made_at")
    store(root, "us", "head_to_head_picks", of_market(examples("head_to_head_pick"), "us"), "made_at")
    store(root, "us", "intraday_alerts", feed_rows(of_market(examples("trade_check"), "us")), "check_at")
    store(root, "us", "paper_trades_settled", of_market(examples("paper_trade"), "us"), "settled_at")
    store(root, "us", "research_reviews", examples("research_review"), "written_at")
    store(root, "us", "command_log", of_market(examples("command_log"), "us"), "received_at")


PRINTED: list[str] = []


def run(argv: list[str], capsys, http=None) -> tuple[int, dict]:
    code = cli.main(argv, http=http)
    captured = capsys.readouterr()
    PRINTED.append(captured.out + captured.err)
    return code, json.loads(captured.out.strip().splitlines()[-1])


def test_cli_dry_run_writes_work_file_and_reruns_post_nothing(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    monkeypatch.setenv("MB_NOW", "2026-10-07T12:00:00+00:00")
    code, out = run(["--market", "us", "--dry-run", "morning"], capsys)
    assert code == 0 and out["mode"] == "dry_run" and out["post_key"] == "morning:us:2026-10-07"
    sent = [json.loads(x) for x in (scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()]
    assert len(sent) == out["parts"] and sent[0]["thread_ts"] is None
    assert "NVIDIA" in sent[0]["text"] or "NVDA" in sent[0]["text"]
    assert not (scratch / "data/us/slack_posts").exists()        # a dry run never writes data/
    assert run(["--market", "us", "--dry-run", "morning"], capsys)[1]["posted"] == []
    # the check at 16:27 is after the clock: nothing to post yet; at 17:00 it goes into the morning's thread
    assert run(["--market", "us", "--dry-run", "intraday"], capsys)[1]["reason"] == "nothing to post"
    monkeypatch.setenv("MB_NOW", "2026-10-07T17:00:00+00:00")
    code, out = run(["--market", "us", "--dry-run", "intraday"], capsys)
    assert code == 0 and out["post_key"] == "alerts:us:ic-us-202610071627" and out["thread_ts"] == sent[0]["ts"]


def test_cli_reads_as_of_the_clock(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    monkeypatch.setenv("MB_NOW", "2026-10-07T11:00:00+00:00")   # before the 11:45 predictions
    run(["--market", "us", "--dry-run", "morning", "--date", "2026-10-07"], capsys)
    sent = (scratch / "work/alerts_dryrun/us/messages.jsonl").read_text()
    assert MSG_NO_PREDICTIONS in sent


def test_cli_close_and_weekly_dry_run(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    monkeypatch.setenv("MB_NOW", "2026-10-02T02:00:00+00:00")
    code, out = run(["--market", "us", "--dry-run", "close", "--date", "2026-10-01"], capsys)
    assert code == 0 and out["post_key"] == "close:us:2026-10-01"
    text_sent = json.loads((scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()[0])["text"]
    settled = [r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01")]
    assert f"*Settled today ({len(settled)} rows)*" in text_sent
    monkeypatch.setenv("MB_NOW", "2026-10-10T15:00:00+00:00")
    code, out = run(["--market", "us", "--dry-run", "weekly"], capsys)
    assert code == 0 and out["post_key"] == "weekly:us:2026-W41"
    assert run(["--market", "us", "--dry-run", "weekly"], capsys)[1]["posted"] == []


def test_token_is_never_printed(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    monkeypatch.setenv("MB_NOW", "2026-10-07T12:00:00+00:00")
    monkeypatch.setenv("SLACK_BOT_TOKEN", TOKEN)
    PRINTED.clear()
    assert TOKEN not in repr(SlackClient(TOKEN))
    code, out = run(["--market", "us", "morning"], capsys, http=FakeSlack(fail_at=1, error="invalid_auth"))
    assert code == 1 and out["error"] == "chat.postMessage: invalid_auth"
    http = FakeSlack()
    code, out = run(["--market", "us", "morning"], capsys, http=http)
    assert code == 0 and out["mode"] == "live" and out["posted"]
    assert http.calls[0]["auth"] == f"Bearer {TOKEN}"    # the header is the only place it goes
    code, out = run(["--market", "us", "onboarding", "--command-id", "cmd-20261005T135500Z-052b8228",
                     "--channel", "C9", "--thread-ts", "1.2"], capsys, http=http)
    assert code == 0 and out["posted"]
    written = "".join(p.read_text() for p in scratch.rglob("*") if p.is_file())
    assert len(PRINTED) == 3 and all(TOKEN not in printed for printed in PRINTED)
    assert TOKEN not in written


def test_cli_without_token_posts_nothing(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    monkeypatch.setenv("MB_NOW", "2026-10-07T12:00:00+00:00")
    code, out = run(["--market", "us", "morning"], capsys)
    assert code == 2 and "SLACK_BOT_TOKEN and SLACK_WEBHOOK_URL not set" in out["error"]


# ---------- as of the clock (judge round 1) ----------

def test_alerts_computed_after_the_clock_are_not_used(scratch, monkeypatch, capsys):
    late = feed_rows(of_market(examples("trade_check"), "us"), computed_at="2026-10-07T16:40:00Z")
    store(scratch, "us", "intraday_alerts", late, "check_at")
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:30:00+00:00")   # after check_at 16:27, before computed_at 16:40
    assert run(["--market", "us", "--dry-run", "intraday"], capsys)[1]["reason"] == "nothing to post"
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:45:00+00:00")
    assert run(["--market", "us", "--dry-run", "intraday"], capsys)[1]["posted"]


def test_explainer_note_written_after_the_clock_is_not_quoted(scratch, monkeypatch, capsys):
    store(scratch, "us", "intraday_alerts", feed_rows(of_market(examples("trade_check"), "us")), "check_at")
    store(scratch, "us", "intraday_explanations", [
        {"id": "ix-ic-us-202610071627-NVDA", "check_row_id": "ic-us-202610071627-NVDA", "attribution": "sector",
         "text": "NVDA rose with its sector.", "cited_ids": ["XLK"], "created_at": "2026-10-07T16:40:00Z"}],
        "created_at")
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:30:00+00:00")
    run(["--market", "us", "--dry-run", "intraday"], capsys)
    first = (scratch / "work/alerts_dryrun/us/messages.jsonl").read_text()
    assert "Note (" not in first
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:45:00+00:00")
    run(["--market", "us", "--dry-run", "intraday", "--check-id", "ic-us-202610071627"], capsys)
    assert "Note (" not in (scratch / "work/alerts_dryrun/us/messages.jsonl").read_text()   # posted once already
    shutil.rmtree(scratch / "work")   # a fresh ledger: the run posts at 16:45 with the note, read through the view
    run(["--market", "us", "--dry-run", "intraday"], capsys)
    assert "   Note (sector): NVDA rose with its sector. [XLK]" in (scratch / "work/alerts_dryrun/us/messages.jsonl"
                                                                    ).read_text()
    rows = reads.latest_alerts(connect("us"), "2026-10-07", pd.Timestamp("2026-10-07T16:45:00Z"))
    assert next(r for r in rows if r["ticker"] == "NVDA")["explanation"] == "NVDA rose with its sector."


def test_feed_records_after_the_clock_are_dropped(scratch, monkeypatch, capsys, tmp_path):
    feed = tmp_path / "feed.jsonl"
    rows = feed_rows(of_market(examples("trade_check"), "us"), computed_at="2026-10-07T16:27:00Z")
    feed.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:00:00+00:00")
    args = ["--market", "us", "--dry-run", "intraday", "--date", "2026-10-07", "--feed", str(feed)]
    assert run(args, capsys)[1]["reason"] == "nothing to post"
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:30:00+00:00")
    assert run(args, capsys)[1]["posted"]
    assert not (scratch / "data/us/slack_posts").exists()


def test_onboarding_command_after_the_clock_is_not_found(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    args = ["--market", "us", "--dry-run", "onboarding", "--command-id", "cmd-20261005T135500Z-052b8228",
            "--channel", "C9", "--thread-ts", "1.2"]
    monkeypatch.setenv("MB_NOW", "2026-10-01T00:00:00+00:00")   # received 2026-10-05
    code, out = run(args, capsys)
    assert code == 1 and "not found" in out["error"]
    monkeypatch.setenv("MB_NOW", "2026-10-05T14:01:00+00:00")   # received, not yet completed (14:02)
    assert run(args, capsys)[0] == 1
    monkeypatch.setenv("MB_NOW", "2026-10-05T15:00:00+00:00")
    assert run(args, capsys)[1]["posted"]


def test_every_message_carries_the_paper_label_and_footer():
    command = examples("command_log")[0]
    messages = [
        build_morning("us", "2026-10-07", of_market(examples("prediction"), "us"), [], HORIZONS),
        build_alerts("us", feed_rows(of_market(examples("trade_check"), "us"))), build_alerts("us", [NEWS]),
        build_close("us", "2026-10-01", []), build_weekly("us", examples("research_review")[0]),
        onboarding_text(command),
    ]
    for message in messages:
        assert "Paper only — no proven edge yet." in message
        assert "Research only, not investment advice. Paper trades are records, never orders." in message


# ---------- owner decisions of 2026-10-07: close list, corrections, one thread ----------

def settled_row(n: int, view: str, net: float, status: str = "settled") -> dict:
    return {"id": f"r{n}", "trade_id": f"t{n}", "ticker": f"T{n:02d}", "horizon_days": 1, "strategy_id": "s",
            "family": "rule", "view": view, "pick_rule": "highest_probability" if view == "head_to_head" else None,
            "status": status, "net_pnl": net, "return_pct": net / 10}


def test_close_lists_head_to_head_then_ten_wins_and_ten_losses():
    rows = ([settled_row(i, "head_to_head", -1.0) for i in range(3)]
            + [settled_row(10 + i, "accuracy", float(i + 1)) for i in range(15)]
            + [settled_row(40 + i, "accuracy", -float(i + 1)) for i in range(12)]
            + [settled_row(70 + i, "accuracy", 0.0, "no_entry") for i in range(2)])
    shown = listed_rows(rows)
    assert [r["id"] for r in shown[:3]] == ["r0", "r1", "r2"]
    assert [r["net_pnl"] for r in shown[3:13]] == [15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0]
    assert [r["net_pnl"] for r in shown[13:]] == [-12.0, -11.0, -10.0, -9.0, -8.0, -7.0, -6.0, -5.0, -4.0, -3.0]
    msg = build_close("us", "2026-10-01", rows, None, {}, "USD")
    assert "*Settled today (32 rows)*" in msg and "…and 9 more rows settled today on the dashboard." in msg
    assert "Accuracy view: Rule 27 trades, 15 wins, net +$42.00" in msg   # totals over every row
    assert len(signal_lines(msg)) == 23


def resettle(original: dict, settled_at: str, net: float) -> dict:
    return {**original, "id": f"{original['trade_id']}@resettled", "supersedes": original["id"],
            "settled_at": settled_at, "net_pnl": net, "return_pct": round(net / 10, 2),
            "flags": ["split_in_window", "resettled"]}


def test_correction_reply_in_the_day_thread_once(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    original = next(r for r in of_market(examples("paper_trade"), "us")
                    if r["trade_id"] == "acc:rule.model_news.v1:2026-09-29-NVDA-1d")
    store(scratch, "us", "paper_trades_settled", [resettle(original, "2026-10-02T03:00:00Z", 3.10)], "settled_at")
    monkeypatch.setenv("MB_NOW", "2026-10-02T02:00:00+00:00")
    close = run(["--market", "us", "--dry-run", "close", "--date", "2026-10-01"], capsys)[1]
    assert run(["--market", "us", "--dry-run", "corrections"], capsys)[1]["reason"] == "nothing to post"
    monkeypatch.setenv("MB_NOW", "2026-10-02T04:00:00+00:00")   # the re-settlement is now stored
    code, out = run(["--market", "us", "--dry-run", "corrections"], capsys)
    assert code == 0 and out["posted"] == ["correction:us:acc:rule.model_news.v1:2026-09-29-NVDA-1d@resettled#1"]
    sent = json.loads((scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()[-1])
    assert sent["thread_ts"] == close["thread_ts"]
    assert sent["text"].startswith("Correction: *NVDA* N+1, Model + news (rule.model_news.v1), accuracy view is now net"
                                   " +$3.10 (+0.31%), was +$4.60 (+0.46%); re-settled 2026-10-02T03:00:00+00:00"
                                   " (flags: split_in_window, resettled). [Paper]")
    assert run(["--market", "us", "--dry-run", "corrections"], capsys)[1]["posted"] == []


def test_resettlement_before_the_close_post_is_no_correction(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    original = next(r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01"))
    store(scratch, "us", "paper_trades_settled", [resettle(original, "2026-10-01T23:00:00Z", 1.0)], "settled_at")
    monkeypatch.setenv("MB_NOW", "2026-10-02T02:00:00+00:00")
    run(["--market", "us", "--dry-run", "close", "--date", "2026-10-01"], capsys)
    sent = json.loads((scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()[0])["text"]
    assert "net +$1.00" in sent   # the close post already shows the newest row of the trade
    assert run(["--market", "us", "--dry-run", "corrections"], capsys)[1]["reason"] == "nothing to post"


@pytest.mark.usefixtures("scratch")
def test_daily_brief_joins_the_day_thread(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", TOKEN)
    http = FakeSlack()
    morning = publisher("us", dry_run=False, http=http).publish(
        Message("morning", "morning:us:2026-10-07", "picks", "us:2026-10-07"))
    brief = post_brief("us", "2026-10-07", "daily brief", http=http)
    assert brief["thread_ts"] == morning["thread_ts"] and http.calls[-1]["form"]["thread_ts"] == morning["thread_ts"]
    assert post_brief("us", "2026-10-07", "daily brief", http=http)["posted"] == []
    # a brief posted first starts the thread, and the morning picks then reply to it
    first = post_brief("us", "2026-10-08", "brief", http=http)
    assert "thread_ts" not in http.calls[-1]["form"]
    publisher("us", dry_run=False, http=http).publish(Message("morning", "morning:us:2026-10-08", "p", "us:2026-10-08"))
    assert http.calls[-1]["form"]["thread_ts"] == first["thread_ts"]


# ---------- the owner's own costs (decisions 50-51; field names assumed until B2's docs/ws/b2.md) ----------

def with_your_cost(rows: list[dict], cost: float) -> list[dict]:
    """Fixture values in B6's assumed naming: the owner's round-trip cost on every call or pick."""
    return [{**r, "your_cost_pct": cost} for r in rows]


def test_morning_pick_viable_means_expected_gain_after_your_cost():
    preds = of_market(examples("prediction"), "us")
    row = agreement(preds, 1)[0]
    p, base = row["avg_prob_up"], row["base_close"]
    move, loss = (row["avg_target"] / base - 1) * 100, (1 - row["avg_lo80"] / base) * 100
    gain = round(p * move - (1 - p) * loss - 0.30, 2)            # F1.7.3 with your cost instead of market costs
    assert gain < 0                                               # wide ranges: the example pick does not pay
    msg = build_morning("us", "2026-10-07", with_your_cost(preds, 0.30), [], HORIZONS)
    assert f"Expected gain {gain:+.2f}% after your cost 0.30% — not viable." in msg
    assert msg.splitlines()[2] == "No pick clears your costs today."
    # a narrow range makes the same pick pay: loss 0.1% -> gain > 0
    narrow = [{**c, "lo80": c["base_close"] * 0.999} for c in with_your_cost(preds, 0.01)]
    row = agreement(narrow, 1)[0]
    gain = round(row["avg_prob_up"] * (row["avg_target"] / row["base_close"] - 1) * 100
                 - (1 - row["avg_prob_up"]) * (1 - row["avg_lo80"] / row["base_close"]) * 100 - 0.01, 2)
    viable = build_morning("us", "2026-10-07", narrow, [], HORIZONS)
    assert gain > 0 and f"Expected gain {gain:+.2f}% after your cost 0.01% — viable." in viable
    assert "No pick clears your costs today." not in viable
    assert "your cost" not in build_morning("us", "2026-10-07", preds, [], HORIZONS)   # no cost stored: no text


def test_head_to_head_line_shows_expected_gain_after_your_cost():
    preds = of_market(examples("prediction"), "us")
    h2h = with_your_cost(of_market(examples("head_to_head_pick"), "us", session_date="2026-10-07"), 0.30)
    lines = [x for x in build_morning("us", "2026-10-07", preds, h2h, HORIZONS).splitlines() if x.startswith("   • ")]
    first = next(p for p in h2h if p["family"] == "rule" and p["pick_rule"] == "best_expected_gain")
    gain = round(first["prob_up"] * first["move_pct"] - (1 - first["prob_up"]) * first["loss_pct"] - 0.30, 2)
    assert f"; expected gain {gain:+.2f}% after your cost 0.30% — not viable [Paper]" in lines[0]
    assert all("after your cost 0.30%" in x for x in lines)


def test_close_shows_your_cost_result_beside_market_cost():
    rows = [r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01")]
    mine = [{**r, "your_costs": round(r["costs"] + 0.46, 2), "your_net_pnl": round(r["net_pnl"] - 0.46, 2),
             "your_return_pct": round((r["net_pnl"] - 0.46) / r["amount"] * 100, 2)} for r in rows]
    msg = build_close("us", "2026-10-01", mine, None, {}, "USD")
    line = next(x for x in msg.splitlines() if "rule.model_news.v1, accuracy view" in x and "NVDA* N+1" in x)
    assert "net +$4.60 (+0.46%) after $2.34 market costs; after your costs ($2.80) net +$4.14 (+0.41%);" in line
    rule = [r for r in mine if r["view"] == "accuracy" and r["family"] == "rule"]
    total = sum(r["your_net_pnl"] for r in rule)
    assert f"(after your costs {text.signed_money('USD', round(total, 2))})" in msg
    assert "your costs" not in build_close("us", "2026-10-01", rows, None, {}, "USD")


def test_resettlement_on_a_later_day_is_only_a_correction(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    original = next(r for r in of_market(examples("paper_trade"), "us")
                    if r["trade_id"] == "acc:rule.model_news.v1:2026-09-29-NVDA-1d")
    # re-settled at 15:00 UTC on 10-02 = 11:00 New York time on 10-02, a later local day than the first settlement
    store(scratch, "us", "paper_trades_settled", [resettle(original, "2026-10-02T15:00:00Z", 3.10)], "settled_at")
    monkeypatch.setenv("MB_NOW", "2026-10-02T02:00:00+00:00")
    run(["--market", "us", "--dry-run", "close", "--date", "2026-10-01"], capsys)
    monkeypatch.setenv("MB_NOW", "2026-10-03T02:00:00+00:00")
    run(["--market", "us", "--dry-run", "close", "--date", "2026-10-02"], capsys)
    sent = [json.loads(x) for x in (scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()]
    second_day = next(m["text"] for m in sent if "close results for Fri 2 Oct 2026" in m["text"])
    assert not [x for x in second_day.splitlines() if "NVDA* N+1" in x and "(rule.model_news.v1), accuracy view" in x]
    assert "+$3.10" not in second_day
    expected = tally([r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-02")
                      and r["view"] == "accuracy" and r["family"] == "rule"])
    assert f"Rule {expected['trades']} trade" in second_day
    assert text.signed_money("USD", expected["net_pnl"]) in second_day
    code, out = run(["--market", "us", "--dry-run", "corrections"], capsys)
    assert out["posted"] == ["correction:us:acc:rule.model_news.v1:2026-09-29-NVDA-1d@resettled#1"]
    assert "bought $229.27 on 2026-09-30," in sent[0]["text"]   # DATE columns print as dates


# ---------- webhook fallback and the fixes of issues #67, #69, #98 ----------

HOOK = "https://hooks.slack.example/services/T000/B000/SECRET-hook"


class FakeHook:
    """Incoming-webhook stand-in: answers 'ok' (or the given status and body)."""

    def __init__(self, status: int = 200, body: bytes = b"ok"):
        self.calls: list[dict] = []
        self.status, self.body = status, body

    def __call__(self, url: str, data: bytes, headers: dict) -> tuple[int, bytes]:
        self.calls.append({"url": url, "json": json.loads(data.decode()), "headers": headers})
        return self.status, self.body


def test_webhook_fallback_posts_unthreaded_once(monkeypatch, scratch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", HOOK)
    hook = FakeHook()
    pub = publisher("us", dry_run=False, http=hook)
    long_text = "\n".join("v" * 200 for _ in range(40))
    res = pub.publish(Message("morning", "morning:us:2026-10-07", long_text, "us:2026-10-07"))
    assert res["mode"] == "webhook" and len(hook.calls) == res["parts"] > 1
    assert all(c["url"] == HOOK and set(c["json"]) == {"text"} for c in hook.calls)   # no thread field at all
    rows = [r for r in Ledger(scratch / "data/us/slack_posts").rows() if r["post_key"] == "morning:us:2026-10-07"]
    assert res["thread_ts"] is None and all(r["thread_ts"] is None for r in rows)    # nothing was threaded
    assert len({r["ts"] for r in rows}) == len(rows) and all(r["ts"].startswith("webhook.") for r in rows)
    again = publisher("us", dry_run=False, http=hook).publish(
        Message("morning", "morning:us:2026-10-07", long_text, "us:2026-10-07"))
    assert again["posted"] == [] and again["thread_ts"] is None                 # a rerun gives no made-up thread
    # a later run with the token starts a real thread (a webhook post is never a thread)
    monkeypatch.setenv("SLACK_BOT_TOKEN", TOKEN)
    http = FakeSlack()
    publisher("us", dry_run=False, http=http).publish(Message("alerts", "alerts:us:ic-1", "a", "us:2026-10-07"))
    assert "thread_ts" not in http.calls[0]["form"]
    # a token run of the post that went out by webhook posts nothing and names no webhook ts as a thread
    token_rerun = publisher("us", dry_run=False, http=http).publish(
        Message("morning", "morning:us:2026-10-07", long_text, "us:2026-10-07"))
    assert token_rerun["posted"] == [] and token_rerun["thread_ts"] is None
    written = "".join(p.read_text() for p in scratch.rglob("*") if p.is_file())
    assert HOOK not in written and "SECRET-hook" not in repr(pub.client)


def test_webhook_error_hides_the_url(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    monkeypatch.setenv("MB_NOW", "2026-10-07T12:00:00+00:00")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", HOOK)
    code, out = run(["--market", "us", "morning"], capsys, http=FakeHook(404, b"no_service"))
    assert code == 1 and out["error"] == "webhook: HTTP 404 no_service" and "SECRET" not in PRINTED[-1]


def test_partly_posted_message_with_a_new_split_is_flagged_incomplete(scratch):
    long_text = "\n".join("w" * 200 for _ in range(60))
    with pytest.raises(SlackError):
        live(scratch, FakeSlack(fail_at=2)).publish(Message("close", "close:us:2026-10-07", long_text, "us:2026-10-07"))
    http = FakeSlack()
    res = live(scratch, http).publish(Message("close", "close:us:2026-10-07", "short now", "us:2026-10-07"))
    expected = len(text.split_message(long_text))
    assert http.calls == [] and res["incomplete"] is True and res["missing_parts"] == list(range(2, expected + 1))


@pytest.mark.usefixtures("scratch")
def test_feed_time_without_offset_is_read_as_utc(monkeypatch, capsys, tmp_path):
    feed = tmp_path / "feed.jsonl"
    rows = [{**r, "check_at": "2026-10-07T16:27:00", "computed_at": None}
            for r in feed_rows(of_market(examples("trade_check"), "us"))]
    feed.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    args = ["--market", "us", "--dry-run", "intraday", "--date", "2026-10-07", "--feed", str(feed)]
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:00:00+00:00")
    assert run(args, capsys)[1]["reason"] == "nothing to post"
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:30:00+00:00")
    assert run(args, capsys)[1]["posted"]


def test_your_cost_total_only_when_every_row_has_it():
    rows = [r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01")]
    one = [{**r, "your_net_pnl": 1.0} if i == 0 else r for i, r in enumerate(rows)]
    assert "after your costs +" not in build_close("us", "2026-10-01", one, None, {}, "USD").split("*Settled")[0]


def test_no_pick_clears_with_some_picks_lacking_cost_numbers():
    preds = of_market(examples("prediction"), "us") + of_market(examples("prediction"), "india")
    costed = [{**p, "your_cost_pct": 0.30} if p["ticker"] == "NVDA" else p for p in preds]   # RELIANCE: no cost
    msg = build_morning("us", "2026-10-07", costed, [], HORIZONS)
    assert [r["ticker"] for r in picks(costed)] == ["NVDA", "RELIANCE"]
    assert msg.splitlines()[2] == "No pick clears your costs today."
    reliance = next(x for x in msg.splitlines() if "(RELIANCE)*" in x)
    assert "your cost" not in reliance                                    # no numbers: no cost text


# ---------- B2's cost_views joined on record_id (docs/ws/b2.md) ----------

def cost_view(kind: str, record: dict, computed_at: str, **values) -> dict:
    return {"id": f"cv:{kind}:{record['id']}", "record_kind": kind, "record_id": record["id"],
            "market": record["market"], "ticker": record["ticker"], "computed_at": computed_at, **values}


def test_cost_views_join_as_of_the_clock(scratch, monkeypatch, capsys):
    store_us_examples(scratch)
    preds = of_market(examples("prediction"), "us")
    settled = [r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01")]
    views = [cost_view("prediction", p, "2026-10-07T11:46:00Z", your_cost_pct=0.30) for p in preds]
    views += [cost_view("settlement", r, "2026-10-01T22:16:00Z", your_costs=round(r["costs"] + 0.46, 2),
                        net_pnl_your=round(r["net_pnl"] - 0.46, 2),
                        return_pct_your=round((r["net_pnl"] - 0.46) / r["amount"] * 100, 2)) for r in settled]
    store(scratch, "us", "cost_views", views, "computed_at")
    monkeypatch.setenv("MB_NOW", "2026-10-07T12:00:00+00:00")
    run(["--market", "us", "--dry-run", "morning", "--date", "2026-10-07"], capsys)
    sent = json.loads((scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()[0])["text"]
    assert "after your cost 0.30% — not viable." in sent
    shutil.rmtree(scratch / "work")
    monkeypatch.setenv("MB_NOW", "2026-10-07T11:45:30+00:00")
    run(["--market", "us", "--dry-run", "morning", "--date", "2026-10-07"], capsys)
    early = json.loads((scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines()[0])["text"]
    assert "your cost" not in early                                  # computed after the clock: not used
    monkeypatch.setenv("MB_NOW", "2026-10-02T02:00:00+00:00")
    shutil.rmtree(scratch / "work")
    run(["--market", "us", "--dry-run", "close", "--date", "2026-10-01"], capsys)
    close = "\n".join(json.loads(x)["text"] for x in
                      (scratch / "work/alerts_dryrun/us/messages.jsonl").read_text().splitlines())
    assert "net +$4.60 (+0.46%) after $2.34 market costs; after your costs ($2.80) net +$4.14 (+0.41%);" in close
    rule = [r for r in settled if r["view"] == "accuracy" and r["family"] == "rule" and r["status"] == "settled"]
    assert f"(after your costs {text.signed_money('USD', round(sum(r['net_pnl'] - 0.46 for r in rule), 2))})" in close
