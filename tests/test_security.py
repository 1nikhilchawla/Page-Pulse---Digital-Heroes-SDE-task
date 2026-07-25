import pytest

from backend.exceptions import BlockedURLError, FetchConnectionError, InvalidURLError
from backend.security import assert_not_internal, normalize_and_validate


def test_bare_domain_gets_https_prefix():
    assert normalize_and_validate("example.com") == "https://example.com"


def test_rejects_empty_url():
    with pytest.raises(InvalidURLError):
        normalize_and_validate("   ")


def test_rejects_unsupported_scheme():
    with pytest.raises(InvalidURLError):
        normalize_and_validate("ftp://example.com")


def test_rejects_no_hostname():
    with pytest.raises(InvalidURLError):
        normalize_and_validate("https:///path-only")


def test_rejects_unresolvable_looking_hostname():
    with pytest.raises(InvalidURLError):
        normalize_and_validate("just some random words")


@pytest.mark.asyncio
async def test_blocks_loopback_address():
    with pytest.raises(BlockedURLError):
        await assert_not_internal("127.0.0.1")


@pytest.mark.asyncio
async def test_blocks_localhost_by_name():
    with pytest.raises(BlockedURLError):
        await assert_not_internal("localhost")


@pytest.mark.asyncio
async def test_allows_public_hostname(monkeypatch):
    # Don't depend on real DNS in CI: stub the loop's resolver.
    import asyncio

    class FakeLoop:
        async def getaddrinfo(self, host, port):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]  # a public-looking IP

    monkeypatch.setattr(asyncio, "get_event_loop", lambda: FakeLoop())
    await assert_not_internal("example.com")  # should not raise


@pytest.mark.asyncio
async def test_dns_failure_raises_connection_error_not_blocked(monkeypatch):
    import asyncio
    import socket

    class FailingLoop:
        async def getaddrinfo(self, host, port):
            raise socket.gaierror("simulated DNS failure")

    monkeypatch.setattr(asyncio, "get_event_loop", lambda: FailingLoop())
    with pytest.raises(FetchConnectionError):
        await assert_not_internal("this-does-not-resolve.invalid")
