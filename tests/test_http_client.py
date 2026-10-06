"""The one HTTP client (marketbrief/sources/http.py) and the clients built on it: request counts, the sleeps
between attempts, which failures are retried and how each caller's error reads. urlopen and sleep are
replaced, so nothing touches the network."""
from __future__ import annotations

import http.client
import io
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.constants.sources import (FREE_SOURCE_USER_AGENT, NEO4J_RETRY_STATUSES,  # noqa: E402
                                           NSE_USER_AGENT)
from marketbrief.sources.errors import FetchError  # noqa: E402
from marketbrief.sources.free_source_client import FreeSourceClient  # noqa: E402
from marketbrief.sources.http import HttpClient, HttpPolicy, constant_wait, linear_wait  # noqa: E402
from marketbrief.sources.neo4j_client import Neo4jClient, Neo4jError  # noqa: E402
from marketbrief.sources.nse_client import Nse  # noqa: E402
from marketbrief.sources.sec_client import Edgar, sec_retry_wait  # noqa: E402
from marketbrief.sources.slack_client import SlackHttp  # noqa: E402


class Answer:
    """A urlopen result: a context manager with read() and a status."""

    def __init__(self, body: bytes = b"{}", status: int = 200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class Server:
    """Replaces urllib.request.urlopen: plays the scripted answers (exceptions are raised) and records requests."""

    def __init__(self, monkeypatch, script):
        self.script, self.requests = list(script), []
        monkeypatch.setattr(urllib.request, "urlopen", self)

    def __call__(self, request, timeout=None):
        self.requests.append((request.full_url, timeout, dict(request.header_items()), request.get_method()))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture
def sleeps(monkeypatch):
    """Records every time.sleep call instead of sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr(time, "sleep", recorded.append)
    return recorded


def http_error(code: int, url: str = "https://x.example/a", body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "status", {}, io.BytesIO(body))


def test_policy_waits_are_constant_or_linear():
    assert [constant_wait(2)(n) for n in (1, 2, 3)] == [2, 2, 2]
    assert [linear_wait(1.5)(n) for n in (1, 2, 3)] == [1.5, 3.0, 4.5]
    assert [sec_retry_wait(n) for n in (1, 2)] == [2, 5]


def test_base_client_returns_the_body_or_the_open_response(monkeypatch, sleeps):
    server = Server(monkeypatch, [Answer(b"one"), Answer(b"two")])
    client = HttpClient(HttpPolicy(timeout=7))
    assert client.send("https://x.example/a", headers={"A": "b"}) == b"one"
    assert client.send("https://x.example/b", stream=True).read() == b"two"
    assert [r[1] for r in server.requests] == [7, 7] and server.requests[0][2] == {"A": "b"}
    assert client.requests == 2 and sleeps == []          # no pause configured: no sleep at all


def test_base_client_raises_http_and_network_errors_as_they_are(monkeypatch, sleeps):
    Server(monkeypatch, [http_error(500), urllib.error.URLError("down")])
    client = HttpClient(HttpPolicy(timeout=1, attempts=3))
    with pytest.raises(urllib.error.HTTPError):
        client.send("https://x.example/a")
    with pytest.raises(urllib.error.URLError):
        client.send("https://x.example/a")                 # network_errors is empty: nothing is caught or retried
    assert sleeps == []


def test_free_source_client_gives_up_after_three_attempts_sleeping_backoff_then_pause(monkeypatch, sleeps):
    server = Server(monkeypatch, [urllib.error.URLError("boom")] * 3)
    client = FreeSourceClient(pause=0.5, backoff=3.0)
    with pytest.raises(FetchError) as error:
        client.get("https://a.example/x")
    assert error.value.error == "a.example unreachable after 3 attempts: boom" and error.value.host is None
    assert sleeps == [3.0, 0.5, 3.0, 0.5, 0.5]            # backoff before each retry, pause after every try
    assert client.requests == 3 and len(server.requests) == 3
    assert server.requests[0][1] == 45 and server.requests[0][2]["User-agent"] == FREE_SOURCE_USER_AGENT


def test_free_source_client_retries_then_succeeds_and_posts_data(monkeypatch, sleeps):
    server = Server(monkeypatch, [http.client.RemoteDisconnected("closed connection"), Answer(b"ok")])
    client = FreeSourceClient(pause=0)
    assert client.get("https://a.example/x", data=b"d", headers={"X-Extra": "1"}) == b"ok"
    assert sleeps == [3.0, 0, 0] and client.requests == 2
    assert server.requests[1][3] == "POST" and server.requests[1][2]["X-extra"] == "1"
    assert client.dead_hosts == {}


@pytest.mark.usefixtures("sleeps")
def test_free_source_client_json_error_names_the_start_of_the_body(monkeypatch):
    Server(monkeypatch, [Answer(b"<html>no</html>")])
    with pytest.raises(FetchError) as error:
        FreeSourceClient(pause=0).json("https://a.example/x")
    assert error.value.error == "not JSON: b'<html>no</html>'"


def test_nse_client_retries_once_with_a_two_second_wait(monkeypatch, sleeps):
    client = Nse(pause=0.1)
    calls = []

    def always_eof(_request, timeout=None):
        calls.append(timeout)
        raise urllib.error.URLError(OSError("EOF occurred in violation of protocol"))

    monkeypatch.setattr(client.opener, "open", always_eof)
    with pytest.raises(FetchError) as error:
        client.text("/content/x.csv")
    assert error.value.error == ("nsearchives.nseindia.com unreachable after a retry: "
                                 "EOF occurred in violation of protocol")
    assert calls == [30, 30] and client.requests == 2
    assert sleeps == [2, 0.1, 0.1]


def test_nse_client_treats_a_tunnel_failure_or_403_as_a_proxy_refusal_at_once(monkeypatch, sleeps):
    client = Nse(pause=0)
    attempts = []

    def denied(_request, **_kwargs):
        attempts.append(1)
        raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))

    monkeypatch.setattr(client.opener, "open", denied)
    with pytest.raises(FetchError) as error:
        client.text("/content/x.csv")
    assert error.value.host == "nsearchives.nseindia.com" and error.value.error.startswith("egress proxy denied")
    assert len(attempts) == 1 and sleeps == [0]           # no retry; only the pause after the attempt


@pytest.mark.usefixtures("sleeps")
def test_nse_client_http_status_is_final_and_sends_browser_headers(monkeypatch):
    client = Nse(pause=0)
    seen = []

    def refused(request, **_kwargs):
        seen.append(dict(request.header_items()))
        raise http_error(403, request.full_url)

    monkeypatch.setattr(client.opener, "open", refused)
    client.warmed = True
    with pytest.raises(FetchError) as error:
        client.json("fiidiiTradeReact")
    assert error.value.error == "HTTP 403 from www.nseindia.com (NSE refused or no such file)"
    assert len(seen) == 1 and seen[0]["User-agent"] == NSE_USER_AGENT
    assert seen[0]["Referer"] == "https://www.nseindia.com/reports/fii-dii"


def test_the_nse_and_free_source_errors_are_one_class():
    import nse
    import sources
    assert nse.FetchError is sources.FetchError is FetchError
    error = FetchError("u", "x" * 300, status=503, host="h.example")
    assert error.entry("src", extra=1) == {"source": "src", "url": "u", "error": "x" * 200, "extra": 1,
                                          "status": 503, "allowlist": "h.example"}
    assert "status" not in FetchError("u", "e").entry("src")


def test_edgar_waits_two_then_five_seconds_on_429_and_raises_the_http_error(monkeypatch, sleeps):
    monkeypatch.delenv("MB_SEC_FIXTURES", raising=False)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    server = Server(monkeypatch, [http_error(429)] * 3)
    edgar = Edgar("test test@example.com")
    with pytest.raises(urllib.error.HTTPError) as error:
        edgar.open("https://data.sec.gov/x.json")
    assert error.value.code == 429 and len(server.requests) == 3
    assert edgar.requests == 1                              # one per call, not per attempt
    assert [round(s, 3) for s in sleeps] == [2, 0.15, 5, 0.15]   # back off, then the throttle before each retry
    assert server.requests[0][1] == 60 and server.requests[0][2]["Accept-encoding"] == "identity"


def test_edgar_does_not_retry_a_404_or_a_network_error(monkeypatch, sleeps):
    monkeypatch.delenv("MB_SEC_FIXTURES", raising=False)
    server = Server(monkeypatch, [http_error(404), urllib.error.URLError("down")])
    edgar = Edgar("test test@example.com")
    with pytest.raises(urllib.error.HTTPError) as error:
        edgar.get("https://data.sec.gov/a.json")
    assert error.value.code == 404
    with pytest.raises(urllib.error.URLError):
        edgar.get("https://data.sec.gov/b.json")
    assert len(server.requests) == 2 and 2 not in sleeps and 5 not in sleeps


def test_neo4j_client_retries_throttling_with_a_growing_wait_then_returns_the_payload(monkeypatch, sleeps):
    payload = json.dumps({"data": {"fields": [], "values": []}, "counters": {}}).encode()
    server = Server(monkeypatch, [http_error(503, body=b"busy"), http_error(429, body=b"slow"), Answer(payload)])
    client = Neo4jClient("https://n.example", "db", ("user", "secret"), backoff=1.5)
    assert client.run("RETURN 1")["counters"] == {}
    assert sleeps == [1.5, 3.0] and len(server.requests) == 3
    url, timeout, headers, method = server.requests[0]
    assert url == "https://n.example/db/db/query/v2" and timeout == 60 and method == "POST"
    assert headers["Authorization"].startswith("Basic ") and client.requests == 0


def test_neo4j_client_errors_never_show_the_password(monkeypatch, sleeps):
    errors = [{"code": "Neo.ClientError.Security.Unauthorized", "message": "bad secret"}]
    body = json.dumps({"errors": errors}).encode()
    Server(monkeypatch, [http_error(401, body=body)])
    client = Neo4jClient("https://n.example", "db", ("user", "secret"), backoff=0)
    with pytest.raises(Neo4jError) as error:
        client.run("RETURN 1")
    assert str(error.value) == "HTTP 401: Neo.ClientError.Security.Unauthorized: bad ***" and sleeps == []
    Server(monkeypatch, [urllib.error.URLError("no route")] * 3)
    with pytest.raises(Neo4jError) as error:
        client.run("RETURN 1")
    assert str(error.value) == "connection failed: no route" and sleeps == [0, 0]
    Server(monkeypatch, [http_error(502, body=b"x")] * 3)
    with pytest.raises(Neo4jError) as error:
        client.run("RETURN 1")
    assert str(error.value) == "HTTP 502: x"
    assert set(NEO4J_RETRY_STATUSES) == {429, 500, 502, 503, 504}


def test_slack_http_returns_status_and_body_for_answers_and_error_statuses(monkeypatch, sleeps):
    server = Server(monkeypatch, [Answer(b'{"ok": true}', status=200), http_error(429, body=b"rate limited")])
    slack = SlackHttp()
    assert slack.post("https://slack.com/api/x", b"a=b", {"Content-Type": "x"}) == (200, b'{"ok": true}')
    assert slack.post("https://slack.com/api/y", b"", {}) == (429, b"rate limited")
    assert [r[3] for r in server.requests] == ["POST", "POST"] and server.requests[0][1] == 60 and sleeps == []


def test_notify_slack_keeps_its_urllib_http_entry_point(monkeypatch):
    import notify_slack
    Server(monkeypatch, [Answer(b"fine", status=202)])
    assert notify_slack.urllib_http("https://hooks.example/x", b"{}", {}) == (202, b"fine")
