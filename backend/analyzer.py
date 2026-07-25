"""Core audit logic.

`audit_url()` is the single entry point: give it a raw URL string, get back
an AuditReport. Every way this can fail is a specific PagePulseError
subclass — see exceptions.py — so main.py never has to guess what went
wrong.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from .exceptions import (
    FetchConnectionError,
    FetchTimeoutError,
    ResponseTooLargeError,
    TooManyRedirectsError,
)
from .models import AuditMetrics, AuditReport
from .scoring import score_report
from .security import assert_not_internal, normalize_and_validate

USER_AGENT = "PagePulseBot/1.0 (+https://digitalheroesco.com; audit tool, one-off fetch)"
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB — plenty for HTML, stops abuse via huge files
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0

TIMEOUT = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=5.0, pool=5.0)


async def audit_url(raw_url: str) -> AuditReport:
    url = normalize_and_validate(raw_url)
    hostname = urlsplit(url).hostname
    await assert_not_internal(hostname)

    warnings: list[str] = []
    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            async with client.stream("GET", url) as response:
                # Re-check the *final* host after redirects — a public URL
                # can redirect to an internal one just as easily as DNS can
                # rebind to one.
                await assert_not_internal(urlsplit(str(response.url)).hostname)

                body_chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_BODY_BYTES:
                        raise ResponseTooLargeError(
                            f"Response exceeded the {MAX_BODY_BYTES // (1024*1024)}MB limit.",
                            details={"limit_bytes": MAX_BODY_BYTES},
                        )
                    body_chunks.append(chunk)
                raw_body = b"".join(body_chunks)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                final_url = str(response.url)
                status_code = response.status_code
                content_type = response.headers.get("content-type", "")
    except httpx.TooManyRedirects as exc:
        raise TooManyRedirectsError(
            f"Exceeded {MAX_REDIRECTS} redirects following this URL.",
        ) from exc
    except httpx.TimeoutException as exc:
        raise FetchTimeoutError(
            f"The server didn't respond within {READ_TIMEOUT:.0f}s.",
            details={"timeout_seconds": READ_TIMEOUT},
        ) from exc
    except httpx.ConnectError as exc:
        raise FetchConnectionError(
            "Couldn't connect to that host (DNS failure, refused connection, or TLS error).",
            details={"reason": str(exc)},
        ) from exc
    except httpx.HTTPError as exc:
        # Catch-all for anything else httpx can throw (protocol errors,
        # decoding issues) so a weird edge case degrades to a clean 502
        # instead of an unhandled 500.
        raise FetchConnectionError(
            "The request failed unexpectedly while talking to that host.",
            details={"reason": str(exc)},
        ) from exc

    is_html = "text/html" in content_type.lower()
    metrics_kwargs = dict(
        http_status=status_code,
        response_time_ms=elapsed_ms,
        content_type=content_type or None,
        is_html=is_html,
    )

    if is_html:
        try:
            text_body = raw_body.decode(response.encoding or "utf-8", errors="replace")
            parsed = _parse_html(text_body)
            metrics_kwargs.update(parsed)
        except Exception as exc:  # noqa: BLE001 - genuinely last-resort
            # BeautifulSoup is very forgiving of malformed markup, so this
            # should be rare, but per spec: never crash. Degrade to a
            # partial report and say why.
            warnings.append(f"Could not parse page content: {exc}")
    else:
        warnings.append(
            f"Content-Type is '{content_type or 'unknown'}', not HTML — "
            "skipping title/meta/heading/image/word-count analysis."
        )

    if status_code >= 400:
        warnings.append(f"Server responded with HTTP {status_code}.")

    metrics = AuditMetrics(**metrics_kwargs)
    score = score_report(metrics)

    return AuditReport(
        requested_url=raw_url,
        resolved_url=final_url,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        metrics=metrics,
        score=score,
        warnings=warnings,
    )


def _parse_html(html: str) -> dict:
    """Pull the report fields out of an HTML document. Pure function, no
    network/IO, which is what makes this cheaply unit-testable (see
    tests/test_analyzer.py) without mocking HTTP at all.
    """
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag and title_tag.get_text(strip=True) else None

    meta_desc_tag = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    meta_description = None
    if meta_desc_tag:
        content = meta_desc_tag.get("content", "")
        meta_description = content.strip() or None

    h1_count = len(soup.find_all("h1"))

    images = soup.find_all("img")
    images_total = len(images)
    missing_alt = [img for img in images if not (img.get("alt") or "").strip()]
    images_missing_alt = len(missing_alt)
    images_missing_alt_examples = [
        (img.get("src") or "(no src)")[:200] for img in missing_alt[:10]
    ]

    # Strip elements that don't contribute reader-visible words before counting.
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    visible_text = soup.get_text(separator=" ")
    word_count = len(visible_text.split())

    return dict(
        title=title,
        meta_description=meta_description,
        h1_count=h1_count,
        images_total=images_total,
        images_missing_alt=images_missing_alt,
        images_missing_alt_examples=images_missing_alt_examples,
        word_count=word_count,
    )
