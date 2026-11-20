import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.port and parsed.port not in {80, 443}:
        host = f"{host}:{parsed.port}"
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    path = re.sub(r"\.(json|xml|csv|geojson)$", "", path, flags=re.I)
    canonical = urlunsplit(("https" if parsed.scheme in {"http", "https"} else parsed.scheme, host, path.lower(), "", ""))
    return canonical


def canonical_id(url: str) -> str:
    canonical = canonicalize_url(url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"govapi-{digest}"
