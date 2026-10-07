"""Slack notifications (B6; scripts/alerts.py, marketbrief/alerts/): each message type from W1's example records
(design/catalogue/), the empty days, long-message splitting, the day's thread, idempotent reruns and a token that
is never printed. Offline: a fake HTTP function stands in for Slack, and nothing is ever posted for real."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.alerts import cli, text  # noqa: E402
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


def test_intraday_alerts_from_trade_checks():
    rows = of_market(examples("trade_check"), "us")
    msg = build_alerts("us", rows, {"rule.model_news.v1": "Model + news"}, "USD")
    flagged = [r for r in rows if r["flagged"]]
    head = f"*US — intraday check at 16:27 UTC: {len(flagged)} flagged open paper trades*"
    assert msg.splitlines()[0].startswith(head)
    nvda = next(line for line in msg.splitlines() if "Model + news" in line and "NVDA" in line)
    assert "$241.10, +5.16% since entry at $229.27; above its 80% range ($215.86–$240.88)" in nvda
    assert "target $228.03 already passed (-5.42%)" in nvda and "outside its predicted range" in nvda
    assert len(signal_lines(msg)) == len(flagged)
    assert all(PAPER in line for line in signal_lines(msg))
    assert "AAPL" not in msg   # AAPL's checks are not flagged
    assert build_alerts("us", [r for r in rows if not r["flagged"]]) is None


def test_intraday_news_alert_record():
    news = {"id": "na-1", "kind": "news", "market": "us", "ticker": "NVDA", "check_at": "2026-10-07T16:27:00Z",
            "news_id": "a41c9e07b2d35f18", "title": "Nvidia unveils new chip", "status": "corroborated",
            "materiality": "high", "trade_ids": ["acc:rule.model_news.v1:2026-09-29-NVDA-5d"]}
    msg = build_alerts("us", [news])
    assert "0 flagged open paper trades, 1 news alert*" in msg
    assert '• *NVDA* news (corroborated, materiality high): "Nvidia unveils new chip" [a41c9e07b2d35f18];' \
           ' 1 open paper trade on it. [Paper]' in msg


def test_close_results_from_examples():
    rows = [r for r in of_market(examples("paper_trade"), "us") if r["settled_at"].startswith("2026-10-01")]
    eod = {"id": "eod-us-2026-10-01", "summary": "Two paper trades settled."}
    msg = build_close("us", "2026-10-01", rows, eod, {}, "USD")
    rule_rows = [r for r in rows if r["view"] == "accuracy" and r["family"] == "rule"]
    rule = tally(rule_rows)
    assert rule["net_pnl"] == round(sum(r["net_pnl"] for r in rule_rows), 2)
    assert f"Rule {rule['trades']} trade" in msg
    assert "Analyst note (eod-us-2026-10-01): Two paper trades settled." in msg
    line = next(x for x in msg.splitlines() if "rule.model_news.v1 (accuracy)" in x and "NVDA* N+1" in x)
    assert "bought $229.27 on 2026-09-30, sold $230.86 on 2026-10-01; net +$4.60 (+0.46%) after $2.34 costs" in line
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
    with pytest.raises(NotConfiguredError, match="SLACK_BOT_TOKEN not set"):
        publisher("us", dry_run=False, environ={})
    (paths.CONFIG / "settings.yaml").write_text("repo_url: x\n")
    with pytest.raises(NotConfiguredError, match="slack_channel_id"):
        publisher("us", dry_run=False, environ={"SLACK_BOT_TOKEN": TOKEN})


# ---------- the CLI on stored records ----------

def store_us_examples(root: Path) -> None:
    store(root, "us", "strategy_predictions", of_market(examples("prediction"), "us"), "made_at")
    store(root, "us", "head_to_head_picks", of_market(examples("head_to_head_pick"), "us"), "made_at")
    store(root, "us", "trade_checks", of_market(examples("trade_check"), "us"), "check_at")
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
    assert code == 2 and "SLACK_BOT_TOKEN not set" in out["error"]


# ---------- as of the clock (judge round 1) ----------

def test_trade_checks_computed_after_the_clock_are_not_used(scratch, monkeypatch, capsys):
    late = [{**r, "computed_at": "2026-10-07T16:40:00Z"} for r in of_market(examples("trade_check"), "us")]
    store(scratch, "us", "trade_checks", late, "check_at")
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:30:00+00:00")   # after check_at 16:27, before computed_at 16:40
    assert run(["--market", "us", "--dry-run", "intraday"], capsys)[1]["reason"] == "nothing to post"
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:45:00+00:00")
    assert run(["--market", "us", "--dry-run", "intraday"], capsys)[1]["posted"]


def test_feed_records_after_the_clock_are_dropped(scratch, monkeypatch, capsys, tmp_path):
    feed = tmp_path / "feed.jsonl"
    rows = [{**r, "computed_at": "2026-10-07T16:27:00Z"} for r in of_market(examples("trade_check"), "us")]
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
    news = {"kind": "news", "ticker": "NVDA", "check_at": "2026-10-07T16:27:00Z", "news_id": "n1", "title": "t",
            "trade_ids": ["x"]}
    messages = [
        build_morning("us", "2026-10-07", of_market(examples("prediction"), "us"), [], HORIZONS),
        build_alerts("us", of_market(examples("trade_check"), "us")), build_alerts("us", [news]),
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
    assert sent["text"].startswith("Correction: *NVDA* N+1, Model + news (rule.model_news.v1) (accuracy) is now net"
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
