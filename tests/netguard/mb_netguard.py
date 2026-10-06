"""Test-only network guard: the tests run offline, so any socket connection or name lookup to a host
other than this machine (loopback) is refused and recorded.

Installed in the pytest process by tests/conftest.py and in every child Python process through
tests/netguard/sitecustomize.py (conftest puts this folder on PYTHONPATH). Each refused attempt is
appended to the file named by MB_NETGUARD_LOG; conftest fails the test that made it. Covers Python's
socket module only (urllib, http.client, ssl, asyncio); a C library opening its own sockets is not seen.
MB_NETGUARD=off lets everything through (tests marked `network`)."""
from __future__ import annotations

import ipaddress
import os
import socket
import sys


class NetworkBlocked(socket.gaierror):
    """A refused connection or lookup (an OSError, like a failed lookup, so callers handle it)."""


LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_real = {}


def is_local(host) -> bool:
    if host is None or host == "" or host == b"":
        return True
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    h = str(host).strip("[]").split("%")[0].lower()
    if h in LOCAL_NAMES or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


def _off() -> bool:
    return os.environ.get("MB_NETGUARD") == "off"


def _refuse(what: str, target) -> NetworkBlocked:
    msg = f"network access blocked in tests: {what} {target!r} (pid {os.getpid()}: {' '.join(sys.argv)[:200]})"
    path = os.environ.get("MB_NETGUARD_LOG")
    if path:
        try:
            with open(path, "a") as f:
                f.write(msg + "\n")
        except OSError:
            sys.stderr.write(msg + "\n")
    else:
        sys.stderr.write(msg + "\n")
    return NetworkBlocked(socket.EAI_NONAME, msg)


def _check_address(sock, address, what: str) -> None:
    if _off() or sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    if isinstance(address, tuple) and address and not is_local(address[0]):
        raise _refuse(what, address)


def _connect(self, address):
    _check_address(self, address, "connect")
    return _real["connect"](self, address)


def _connect_ex(self, address):
    _check_address(self, address, "connect")
    return _real["connect_ex"](self, address)


def _sendto(self, data, *args):
    if args:
        _check_address(self, args[-1], "sendto")
    return _real["sendto"](self, data, *args)


def _getaddrinfo(host, *args, **kwargs):
    if not _off() and not is_local(host):
        raise _refuse("lookup", host)
    return _real["getaddrinfo"](host, *args, **kwargs)


def _gethostbyname(host):
    if not _off() and not is_local(host):
        raise _refuse("lookup", host)
    return _real["gethostbyname"](host)


def _gethostbyname_ex(host):
    if not _off() and not is_local(host):
        raise _refuse("lookup", host)
    return _real["gethostbyname_ex"](host)


def install() -> None:
    """Patch the socket module once per process."""
    if _real:
        return
    for name, fn in (("connect", _connect), ("connect_ex", _connect_ex), ("sendto", _sendto)):
        _real[name] = getattr(socket.socket, name)
        setattr(socket.socket, name, fn)
    for name, fn in (("getaddrinfo", _getaddrinfo), ("gethostbyname", _gethostbyname),
                     ("gethostbyname_ex", _gethostbyname_ex)):
        _real[name] = getattr(socket, name)
        setattr(socket, name, fn)
