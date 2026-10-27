"""Bounded browser-compatible fetches with public DNS pinned into libcurl."""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin

from yarl import URL

from ..errors import ExternalServiceError
from .http_client import HttpResponse
from .network_policy import PublicResolver, public_address, validate_public_url


class BrowserHttpClient:
    def __init__(self, *, timeout=15, max_bytes=2 * 1024 * 1024):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.slots = asyncio.Semaphore(2)

    async def get_text(self, url):
        # Lazy import keeps disabled fallback usable on platforms without a wheel.
        try:
            from curl_cffi import CurlInfo, CurlOpt
            from curl_cffi.requests import AsyncSession
        except ImportError:
            raise ExternalServiceError("Browser-compatible fallback dependency is unavailable.") from None

        try:
            async with asyncio.timeout(self.timeout), self.slots:
                for _ in range(4):
                    validate_public_url(url)
                    canonical = URL(url)
                    url = str(canonical)
                    validate_public_url(url)
                    host, port = canonical.raw_host, canonical.port
                    records = await PublicResolver().resolve(host, port, socket.AF_UNSPEC)
                    # The resolver rejects mixed public/private DNS answers.
                    address = records[0]["host"]
                    if not public_address(address):
                        raise ExternalServiceError("Private/local DNS destinations are blocked.")
                    options = {
                        CurlOpt.PROXY: b"",  # Override ALL_PROXY/http_proxy too.
                        CurlOpt.NOPROXY: b"*",
                        CurlOpt.FOLLOWLOCATION: 0,
                        CurlOpt.PROTOCOLS: 3,  # HTTP | HTTPS only.
                        CurlOpt.MAXFILESIZE_LARGE: self.max_bytes,
                    }
                    try:
                        ipaddress.ip_address(host)
                    except ValueError:
                        pinned = f"[{address}]" if ":" in address else address
                        options[CurlOpt.RESOLVE] = [f"{host}:{port}:{pinned}".encode()]
                    body = bytearray()
                    overflow = False

                    def consume(chunk):
                        nonlocal overflow
                        if len(body) + len(chunk) > self.max_bytes:
                            overflow = True
                            return 0  # Abort transfer; never accumulate an unbounded body.
                        body.extend(chunk)
                        return len(chunk)

                    # A new session per hop: no shared DNS, connection, cookie or auth state.
                    async with AsyncSession(
                        impersonate="chrome",
                        trust_env=False,
                        curl_options=options,
                        curl_infos=[CurlInfo.PRIMARY_IP],
                        max_clients=1,
                    ) as session:
                        try:
                            response = await session.get(
                                url,
                                allow_redirects=False,
                                timeout=self.timeout,
                                content_callback=consume,
                                verify=True,
                            )
                        except Exception:
                            if overflow:
                                raise ExternalServiceError("Response exceeds the download limit.") from None
                            raise
                        peer = response.infos.get(CurlInfo.PRIMARY_IP, "")
                        if isinstance(peer, bytes):
                            peer = peer.decode("ascii")
                        if not public_address(peer) or ipaddress.ip_address(peer) != ipaddress.ip_address(
                            address
                        ):
                            raise ExternalServiceError("Connected destination did not match validated DNS.")
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location", "")
                            if not location:
                                raise ExternalServiceError("Invalid redirect.")
                            url = urljoin(url, location)
                            continue
                        result = HttpResponse(response.status_code, dict(response.headers), bytes(body), url)
                        return result.status, result.text(), result.headers
                raise ExternalServiceError("Too many redirects.")
        except ExternalServiceError:
            raise
        except Exception:
            # Never return native exception strings: they can contain request details.
            raise ExternalServiceError("Browser-compatible request failed or timed out.") from None
