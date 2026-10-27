import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin

import aiohttp

from ..errors import ExternalServiceError
from .network_policy import PublicResolver, endpoint, validate_public_url


@dataclass(slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    def text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.body.decode(encoding, errors=errors)

    def json(self) -> Any:
        if not self.body:
            return {}
        return json.loads(self.text())


class HttpClient:
    def __init__(
        self, *, proxy=None, timeout=15, user_agent=None, trusted_base=None, max_bytes=2 * 1024 * 1024
    ):
        if proxy:
            raise ExternalServiceError("HTTP proxies are disabled to enforce destination validation.")
        self.timeout = timeout
        self.user_agent = user_agent or "astrbot-guarded-search/1.2"
        self.trusted_base = trusted_base.rstrip("/") if trusted_base else None
        self.max_bytes = max_bytes
        self.slots = asyncio.Semaphore(4)

    def validate(self, url):
        if self.trusted_base:
            # Trusted infrastructure is not a general-purpose private-network client.
            parts, origin = endpoint(url)
            base, expected = endpoint(self.trusted_base)
            if origin != expected or parts.path != base.path.rstrip("/") + "/search":
                raise ExternalServiceError("Request outside the configured search endpoint is blocked.")
        else:
            validate_public_url(url)

    async def request(self, method, url, *, params=None, headers=None, allow_redirects=True):
        self.validate(url)
        merged_headers = {"User-Agent": self.user_agent, **(headers or {})}
        try:
            async with asyncio.timeout(self.timeout), self.slots:
                connector = aiohttp.TCPConnector(
                    resolver=None if self.trusted_base else PublicResolver(), use_dns_cache=False
                )
                async with aiohttp.ClientSession(
                    connector=connector,
                    trust_env=False,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers=merged_headers,
                ) as session:
                    for _ in range(4):
                        self.validate(url)
                        async with session.request(
                            method, url, params=params, allow_redirects=False
                        ) as response:
                            if response.status in {301, 302, 303, 307, 308}:
                                if not allow_redirects or self.trusted_base:
                                    raise ExternalServiceError("Infrastructure redirects are blocked.")
                                url = urljoin(url, response.headers.get("Location", ""))
                                params = None
                                # Public redirect targets never receive an API credential header.
                                session.headers.pop("Authorization", None)
                                continue
                            body = bytearray()
                            if method != "HEAD":
                                async for chunk in response.content.iter_chunked(65536):
                                    body.extend(chunk)
                                    if len(body) > self.max_bytes:
                                        raise ExternalServiceError("Response exceeds the download limit.")
                            return HttpResponse(
                                response.status, dict(response.headers), bytes(body), str(response.url)
                            )
                    raise ExternalServiceError("Too many redirects.")
        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError):
            raise ExternalServiceError("Network request failed or timed out.") from None

    async def get_json(self, url, *, params=None, headers=None):
        response = await self.request("GET", url, params=params, headers=headers)
        return response.status, response.json()

    async def get_text(self, url, *, params=None, headers=None):
        response = await self.request("GET", url, params=params, headers=headers)
        return response.status, response.text(), response.headers

    async def get_bytes(self, url, *, params=None, headers=None):
        response = await self.request("GET", url, params=params, headers=headers)
        return response.status, response.body, response.headers

    async def head_ok(self, url):
        try:
            response = await self.request("HEAD", url)
            return 200 <= response.status < 300
        except ExternalServiceError:
            return False
