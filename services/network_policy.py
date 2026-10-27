"""Public Internet requests cannot use private, local or transitional addresses."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from aiohttp.abc import AbstractResolver
from yarl import URL

from ..errors import ExternalServiceError


def endpoint(value: str):
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
        ):
            raise ValueError()
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        return parts, (parts.scheme, parts.hostname.lower(), port)
    except (ValueError, TypeError):
        raise ExternalServiceError("Invalid HTTP(S) URL.") from None


def public_address(address):
    ip = ipaddress.ip_address(address)
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return public_address(ip.ipv4_mapped)
        # Do not permit transition mechanisms to tunnel private IPv4 destinations.
        for network in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"):
            if ip in ipaddress.ip_network(network):
                return False
    return True


def validate_public_url(url):
    parts, origin = endpoint(url)
    if origin[2] not in {80, 443}:
        raise ExternalServiceError("Public URLs must use port 80 or 443.")
    # Apply the same IDNA canonicalization as aiohttp before deciding whether
    # it can bypass DNS resolution as a numeric host.
    try:
        host = URL(url).raw_host.rstrip(".").lower()
    except (ValueError, AttributeError):
        raise ExternalServiceError("Invalid public URL.") from None
    if "%" in host:
        raise ExternalServiceError("Scoped/encoded host addresses are blocked.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ExternalServiceError("Private/local destinations are blocked.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or host.replace(".", "").isdigit():
            raise ExternalServiceError("Noncanonical numeric addresses are blocked.") from None
        return
    if not public_address(ip):
        raise ExternalServiceError("Private/local destinations are blocked.")


class PublicResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, family=family
        )
        if not records or any(not public_address(record[4][0]) for record in records):
            raise ExternalServiceError("Private/local DNS destinations are blocked.")
        return [
            {
                "hostname": host,
                "host": addr[0],
                "port": port,
                "family": fam,
                "proto": proto,
                "flags": socket.AI_NUMERICHOST,
            }
            for fam, _, proto, _, addr in records
        ]

    async def close(self):
        pass
