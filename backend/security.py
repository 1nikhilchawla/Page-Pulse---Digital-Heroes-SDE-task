"""URL validation + SSRF (server-side request forgery) guard.

Page Pulse fetches whatever URL a caller gives it. Left unchecked, that
makes the audit endpoint a ready-made proxy for probing internal
infrastructure: "audit http://169.254.169.254/latest/meta-data/" would
happily fetch cloud instance metadata; "audit http://localhost:6379/"
would poke at a local Redis. We block those before a request is ever sent.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from .exceptions import BlockedURLError, FetchConnectionError, InvalidURLError

ALLOWED_SCHEMES = {"http", "https"}
DNS_TIMEOUT_SECONDS = 5.0


def normalize_and_validate(raw_url: str) -> str:
    """Basic shape validation. Raises InvalidURLError with a specific reason."""
    candidate = raw_url.strip()
    if not candidate:
        raise InvalidURLError("URL is empty.")

    # Users routinely paste bare domains ("example.com"); be forgiving there,
    # but don't guess at anything more mangled than that.
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parts = urlsplit(candidate)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise InvalidURLError(
            f"Unsupported scheme '{parts.scheme}'. Only http and https are audited.",
            details={"scheme": parts.scheme},
        )

    if not parts.hostname:
        raise InvalidURLError("URL has no hostname.")

    if "." not in parts.hostname and parts.hostname != "localhost":
        raise InvalidURLError(
            "URL doesn't look like a resolvable hostname.",
            details={"hostname": parts.hostname},
        )

    return candidate


async def assert_not_internal(hostname: str) -> None:
    """Resolve `hostname` and reject it if it points at private/reserved
    address space. Raises BlockedURLError if it does.

    This runs *after* DNS resolution (not just a string check on the
    hostname) so a public-looking name that resolves to a private IP,
    "DNS rebinding", is still caught.

    Uses the event loop's own resolver (loop.getaddrinfo) rather than
    calling socket.getaddrinfo directly: the socket module's version is a
    blocking call, and running it straight inside an async request
    handler would stall every other in-flight request for as long as
    that one DNS lookup takes. The loop's version offloads it to a
    thread; wrapping that in wait_for() also gives us a hard timeout,
    since an unresponsive resolver should fail fast, not hang the request.
    """
    loop = asyncio.get_event_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None), timeout=DNS_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise FetchConnectionError(
            f"DNS lookup for '{hostname}' timed out after {DNS_TIMEOUT_SECONDS:.0f}s.",
            details={"hostname": hostname},
        ) from exc
    except socket.gaierror as exc:
        raise FetchConnectionError(
            f"Could not resolve hostname '{hostname}'. Check the URL is correct.",
            details={"hostname": hostname},
        ) from exc

    for info in infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BlockedURLError(
                "This URL resolves to a private, loopback, or reserved address "
                "and can't be audited.",
                details={"hostname": hostname, "resolved_ip": ip_str},
            )
