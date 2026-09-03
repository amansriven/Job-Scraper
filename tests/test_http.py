import httpx
import pytest

from app.http import HttpClient


@pytest.mark.asyncio
async def test_retries_protocol_disconnect(monkeypatch):
    client = HttpClient(retries=2)
    attempts = 0

    async def request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("server disconnected")
        return httpx.Response(200, request=httpx.Request("GET", "https://example.com"))

    monkeypatch.setattr(client.client, "request", request)
    monkeypatch.setattr("app.http.asyncio.sleep", lambda delay: _no_wait())
    try:
        response = await client.get("https://example.com")
    finally:
        await client.close()

    assert response.status_code == 200
    assert attempts == 2


async def _no_wait():
    return None
