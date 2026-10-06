"""The test network guard (tests/conftest.py, tests/netguard/): the suite runs offline. A connection or
name lookup to anything but loopback is refused and recorded, in this process and in child Python
processes; loopback servers (the fake Neo4j endpoint) still work.
Run: pytest -q"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import mb_netguard

REMOTE_IP = "192.0.2.1"             # TEST-NET-1 (RFC 5737): never routed, so a broken guard cannot leak
REMOTE_NAME = "example.invalid"     # reserved name (RFC 2606), never resolves


@pytest.fixture
def own_log(tmp_path, monkeypatch):
    """Refusals made on purpose go to this test's own file, not the one conftest fails the test on."""
    log = tmp_path / "netguard.log"
    monkeypatch.setenv("MB_NETGUARD_LOG", str(log))
    return log


def test_is_local():
    for h in ("localhost", "127.0.0.1", "127.8.9.1", "::1", "[::1]", "0.0.0.0", "::ffff:127.0.0.1", None, "",
              b"localhost", "foo.localhost"):
        assert mb_netguard.is_local(h), h
    for h in (REMOTE_IP, REMOTE_NAME, "8.8.8.8", "2001:db8::1", "www.sec.gov", "::ffff:8.8.8.8"):
        assert not mb_netguard.is_local(h), h


def test_guard_is_on_and_proxies_removed():
    assert os.environ["MB_NETGUARD"] == "on"
    assert not any(k in os.environ for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"))
    assert socket.getaddrinfo is mb_netguard._getaddrinfo


def test_in_process_connect_and_lookup_are_refused(own_log):
    with socket.socket() as s:
        with pytest.raises(OSError, match="network access blocked"):
            s.connect((REMOTE_IP, 80))
    with pytest.raises(OSError, match="network access blocked"):
        socket.getaddrinfo(REMOTE_NAME, 443)
    with pytest.raises(OSError):                        # urllib wraps it (URLError is an OSError)
        urllib.request.urlopen(f"http://{REMOTE_NAME}/", timeout=2)
    lines = own_log.read_text().splitlines()
    assert len(lines) == 3 and all("network access blocked" in x for x in lines)
    assert REMOTE_IP in lines[0] and REMOTE_NAME in lines[1] and REMOTE_NAME in lines[2]


def test_child_python_process_is_guarded(own_log, tmp_path):
    code = ("import socket, urllib.request\n"
            "try:\n"
            f"    urllib.request.urlopen('https://{REMOTE_NAME}/', timeout=2)\n"
            "except OSError as e:\n"
            "    print('refused', type(e).__name__)\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=dict(os.environ),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("refused")
    assert REMOTE_NAME in own_log.read_text()


def test_loopback_server_still_works():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for host in ("127.0.0.1", "localhost"):
            with urllib.request.urlopen(f"http://{host}:{server.server_port}/", timeout=5) as resp:
                assert resp.read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.network
def test_network_marker_turns_the_guard_off():
    assert os.environ["MB_NETGUARD"] == "off"
    with socket.socket() as s:                          # the check passes (no connection is made here)
        assert mb_netguard._check_address(s, (REMOTE_IP, 9), "connect") is None
