from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from urllib.parse import urlsplit

import httpx


class HttpClient:
    def __init__(self, concurrency: int = 12, per_domain: int = 2, timeout: float = 25, retries: int = 3):
        self.global_limit = asyncio.Semaphore(concurrency)
        self.domain_limits: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(per_domain))
        self.retries = retries
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": "PersonalInternshipMonitor/1.0 (+contact: personal-use)"})

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        domain = urlsplit(url).netloc.lower()
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                async with self.global_limit, self.domain_limits[domain]:
                    response = await self.client.request(method, url, **kwargs)
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return response
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.6 * (2**attempt) + random.random() * 0.25
            # TransportError also covers protocol-level disconnects such as a
            # server closing an HTTP/2 stream before returning a response.
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                delay = 0.6 * (2**attempt) + random.random() * 0.25
            if attempt + 1 < self.retries:
                await asyncio.sleep(delay)
        if last_error:
            raise last_error
        response.raise_for_status()
        return response

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("POST", url, **kwargs)
