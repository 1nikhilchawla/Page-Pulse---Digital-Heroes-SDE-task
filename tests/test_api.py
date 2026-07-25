import httpx
import pytest
import respx
from httpx import ASGITransport

from backend.main import app

HTML_PAGE = """
<html><head><title>Test Page</title>
<meta name="description" content="A perfectly reasonable meta description for testing purposes here."></head>
<body><h1>Hello</h1><p>Some words on this test page for word counting purposes.</p>
<img src="a.png" alt="described"><img src="b.png"></body></html>
"""


async def _client():
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health_endpoint():
    async with await _client() as client:
        res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_audit_success_returns_full_report():
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, text=HTML_PAGE, headers={"content-type": "text/html"})
    )
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "https://example.com"})

    assert res.status_code == 200
    body = res.json()
    assert body["metrics"]["title"] == "Test Page"
    assert body["metrics"]["h1_count"] == 1
    assert body["metrics"]["images_total"] == 2
    assert body["metrics"]["images_missing_alt"] == 1
    assert 0 <= body["score"]["total"] <= 100


@pytest.mark.asyncio
async def test_audit_rejects_invalid_url():
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "not a url"})
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_url"


@pytest.mark.asyncio
async def test_audit_rejects_internal_url():
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "http://127.0.0.1/"})
    assert res.status_code == 400
    assert res.json()["error"] == "blocked_url"


@pytest.mark.asyncio
@respx.mock
async def test_audit_handles_timeout_cleanly():
    respx.get("https://example.com/slow").mock(side_effect=httpx.ReadTimeout("timed out"))
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "https://example.com/slow"})
    assert res.status_code == 504
    assert res.json()["error"] == "timeout"


@pytest.mark.asyncio
@respx.mock
async def test_audit_handles_connection_error_cleanly():
    respx.get("https://example.com/unreachable").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "https://example.com/unreachable"})
    assert res.status_code == 502
    assert res.json()["error"] == "connection_failed"


@pytest.mark.asyncio
@respx.mock
async def test_audit_handles_non_html_response_without_crashing():
    respx.get("https://example.com/data.json").mock(
        return_value=httpx.Response(200, json={"key": "value"}, headers={"content-type": "application/json"})
    )
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "https://example.com/data.json"})
    assert res.status_code == 200
    body = res.json()
    assert body["metrics"]["is_html"] is False
    assert body["metrics"]["title"] is None
    assert any("not HTML" in w for w in body["warnings"])


@pytest.mark.asyncio
@respx.mock
async def test_audit_reports_4xx_status_without_treating_it_as_an_error():
    respx.get("https://example.com/missing").mock(
        return_value=httpx.Response(404, text="<html><body>Not found</body></html>", headers={"content-type": "text/html"})
    )
    async with await _client() as client:
        res = await client.post("/api/audit", json={"url": "https://example.com/missing"})
    # A 404 is data about the page, not a Page Pulse error -- the audit itself succeeded.
    assert res.status_code == 200
    body = res.json()
    assert body["metrics"]["http_status"] == 404
    assert any("404" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_audit_rejects_malformed_request_body():
    async with await _client() as client:
        res = await client.post("/api/audit", json={"not_url": "oops"})
    assert res.status_code == 422  # FastAPI's own request-validation error
