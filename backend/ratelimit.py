"""A deliberately small in-memory rate limiter.

Page Pulse fetches third-party URLs on a caller's behalf, so the audit
endpoint doubles as an outbound request generator — worth capping per
client so one caller can't turn this into a free-for-all crawler or a
denial-of-service tool against a target site.

This is a sliding-window counter per client IP, kept in a plain dict.
That's the right amount of engineering for a single-process free-tier
deployment; it resets on restart and doesn't share state across workers.
A production multi-instance deployment would move this to Redis — noted
in the README rather than built here, since it'd add a hard dependency
for a problem this deployment doesn't have.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.responses import JSONResponse

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 20

_hits: dict[str, deque] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # Respect a trusted reverse proxy header if present (Render/Railway/etc.
    # sit behind one), else fall back to the raw peer address.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path != "/api/audit":
        return await call_next(request)

    key = _client_key(request)
    now = time.monotonic()
    window = _hits[key]

    while window and now - window[0] > WINDOW_SECONDS:
        window.popleft()

    if len(window) >= MAX_REQUESTS_PER_WINDOW:
        retry_after = int(WINDOW_SECONDS - (now - window[0])) + 1
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "message": f"Too many audits from this client. Try again in {retry_after}s.",
                "details": {"limit_per_minute": MAX_REQUESTS_PER_WINDOW},
            },
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)
    return await call_next(request)
