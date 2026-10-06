"""Resolving Google News redirect links to the publisher's URL (googlenewsdecoder: one GET per link and one POST
per batch to news.google.com). A request hook refuses any request, redirects included, that is not HTTPS to
google.com, so the decoder can reach nothing else."""
from __future__ import annotations

from marketbrief.constants.article_collection import (DEFAULT_PAUSE_SECONDS, DEFAULT_TIMEOUT_SECONDS, GOOGLE_DOMAIN,
                                                      MSG_DECODER_REQUEST_REFUSED)
from marketbrief.constants.articles import HTTPS


def google_only(request) -> None:
    """httpx request hook for the decoder's client: it follows redirects itself (also on its POST),
    so every request it sends, redirects included, must be HTTPS to google.com or a subdomain."""
    import httpx
    host = (request.url.host or "").lower()
    if request.url.scheme != HTTPS or not (host == GOOGLE_DOMAIN or host.endswith("." + GOOGLE_DOMAIN)):
        raise httpx.RequestError(MSG_DECODER_REQUEST_REFUSED.format(scheme=request.url.scheme, host=host),
                                 request=request)


def decode_google(links: list[str], src) -> list[dict]:
    """googlenewsdecoder results for a batch of Google News links ({'success', 'decoded_url' | 'message'})."""
    from googlenewsdecoder import GoogleDecoder
    selection = src.sel
    with GoogleDecoder(timeout=float(selection.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
                       user_agent=selection.get("user_agent")) as decoder:
        decoder.client.event_hooks = {"request": [google_only], "response": []}
        interval = max(1, int(round(float(selection.get("pause_seconds", DEFAULT_PAUSE_SECONDS)))))
        return decoder.decode_google_news_urls(links, interval=interval)
