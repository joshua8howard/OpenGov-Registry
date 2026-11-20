from urllib.parse import urljoin, urlsplit

import httpx

from .verification import validate_public_url, UnsafeURLError


class OpenAPIDiscovery:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 5.0) -> None:
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def discover(self, documentation_url: str) -> dict | None:
        parsed = urlsplit(documentation_url)
        if not parsed.scheme or not parsed.netloc:
            return None

        base = documentation_url.rstrip("/")
        candidates = [
            base,
            urljoin(base + "/", "openapi.json"),
            urljoin(base + "/", "swagger.json"),
            urljoin(base + "/", "openapi.yaml"),
        ]
        for candidate in candidates:
            try:
                validate_public_url(candidate)
                response = self.client.get(candidate)
            except (UnsafeURLError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
                continue
            if not 200 <= response.status_code < 300:
                continue
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type and not candidate.endswith(".json"):
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            if "openapi" not in payload and "swagger" not in payload:
                continue
            return {
                "openapi_spec_url": candidate,
                "title": payload.get("info", {}).get("title") if isinstance(payload.get("info"), dict) else None,
                "version": payload.get("info", {}).get("version") if isinstance(payload.get("info"), dict) else None,
                "path_count": len(payload.get("paths", {})) if isinstance(payload.get("paths"), dict) else 0,
            }
        return None
