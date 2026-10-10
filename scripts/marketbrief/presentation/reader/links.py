"""Links of the public brief (C2 batch 2): the per-page token and path. The token is HMAC-SHA256 of the market and
session with the BRIEF_LINK_SECRET environment variable, cut to 128 bits: deterministic (a rerun gives the same link),
never stored (the repo is public; rm.brief keeps only its SHA-256). Without the secret there is no token and no link."""
from __future__ import annotations

import hashlib
import hmac
import os

import yaml

from marketbrief.core import paths

from marketbrief.constants import reader as text
from marketbrief.constants.warehouse import FILE_WAREHOUSE_CONFIG


def has_secret(env=None) -> bool:
    """True when BRIEF_LINK_SECRET is set (non-empty)."""
    return bool(((env if env is not None else os.environ).get(text.ENV_BRIEF_SECRET) or "").strip())


def brief_token(market: str, session: str, env=None) -> str | None:
    """The page's token (32 lowercase hex), or None when BRIEF_LINK_SECRET is unset or empty."""
    secret = ((env if env is not None else os.environ).get(text.ENV_BRIEF_SECRET) or "").strip()
    if not secret:
        return None
    mac = hmac.new(secret.encode(), f"brief:{market}:{session}".encode(), hashlib.sha256)
    return mac.hexdigest()[:text.BRIEF_TOKEN_HEX]


def token_sha256(token: str) -> str:
    """The SHA-256 (hex) of a token: what rm.brief stores and the route compares in constant time."""
    return hashlib.sha256(token.encode()).hexdigest()


def brief_path(market: str, session: str, env=None) -> str | None:
    """'/brief/<market>/<session>-<token>', or None without the secret (callers keep their other link)."""
    token = brief_token(market, session, env)
    return None if token is None else text.BRIEF_PATH.format(market=market, session=session, token=token)


def app_link(market: str) -> str | None:
    """The private app's market page (config/warehouse.yaml app_url + /<market>): the public brief's one link into
    the app (behind Vercel Authentication); None when the config or the URL is missing."""
    path = paths.CONFIG / FILE_WAREHOUSE_CONFIG
    url = (yaml.safe_load(path.read_text()) or {}).get("app_url") if path.exists() else None
    return f"{str(url).rstrip('/')}/{market}" if url else None
