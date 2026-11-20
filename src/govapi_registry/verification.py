import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx


class UnsafeURLError(ValueError):
    pass


def validate_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("Only HTTP(S) URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL hostname is required")

    try:
        addresses = {address for _, _, _, _, address in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as exc:
        raise UnsafeURLError("URL hostname could not be resolved") from exc

    if not addresses:
        raise UnsafeURLError("URL resolved to no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeURLError("Private and local network destinations are blocked")
    return url


class EndpointVerifier:
    def __init__(
        self,
        timeout: float = 5.0,
        max_bytes: int = 256_000,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.client = client

    def verify(self, url: str) -> dict:
        validate_public_url(url)
        started = datetime.now(timezone.utc)
        client = self.client or httpx.Client(timeout=self.timeout, follow_redirects=False)
        current = url
        try:
            for _ in range(5):
                validate_public_url(current)
                response = client.get(current)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        break
                    current = urljoin(current, location)
                    continue

                content = response.content[: self.max_bytes]
                content_type = response.headers.get("content-type", "").lower()
                if response.status_code in {401, 403}:
                    status = "unauthenticated"
                elif 200 <= response.status_code < 400:
                    status = "healthy"
                else:
                    status = "unreachable"

                return {
                    "status": status,
                    "http_status": response.status_code,
                    "response_time_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "content_type": content_type,
                    "response_bytes": len(content),
                    "last_verified": datetime.now(timezone.utc),
                }
            return {
                "status": "degraded",
                "http_status": None,
                "response_time_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                "content_type": "",
                "response_bytes": 0,
                "last_verified": datetime.now(timezone.utc),
            }
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return {
                "status": "unreachable",
                "http_status": None,
                "response_time_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                "content_type": "",
                "response_bytes": 0,
                "last_verified": datetime.now(timezone.utc),
            }
