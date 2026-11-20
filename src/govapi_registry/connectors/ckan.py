from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
import re

import httpx

from .base import CatalogConnector
from ..models import APIRecordCreate


class CKANConnector(CatalogConnector):
    source_id = "ckan"

    def __init__(
        self,
        base_url: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http_client or httpx.Client(timeout=30.0)
        host = urlsplit(base_url).hostname or base_url
        self.source_id = f"ckan:{host}"

    def discover(self, limit: int = 100) -> Iterable[dict[str, Any]]:
        start = 0
        while start < limit:
            rows = min(100, limit - start)
            response = self.http.get(
                f"{self.base_url}/api/3/action/package_search",
                params={"start": start, "rows": rows},
            )
            response.raise_for_status()
            result = response.json().get("result", {})
            records = result.get("results", [])
            if not records:
                return
            for record in records:
                if self.validate(record):
                    yield record
            start += len(records)

    def fetch(self, record_id: str) -> dict[str, Any]:
        response = self.http.get(
            f"{self.base_url}/api/3/action/package_show",
            params={"id": record_id},
        )
        response.raise_for_status()
        return response.json()["result"]

    def validate(self, record: dict[str, Any]) -> bool:
        return bool(record.get("id") and record.get("title") and record.get("resources"))

    def normalize(self, record: dict[str, Any]) -> list[APIRecordCreate]:
        normalized: list[APIRecordCreate] = []
        if not self.validate(record):
            return normalized

        record_id = str(record["id"])
        organization = record.get("organization") or {}
        agency = str(organization.get("title") or organization.get("name") or "Government publisher")
        groups = record.get("groups") or []
        category = "open-data"
        if groups and isinstance(groups[0], dict):
            category = str(groups[0].get("title", "open-data")).lower().replace(" ", "-")

        for index, resource in enumerate(record["resources"]):
            url = resource.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            resource_format = str(resource.get("format") or "").upper()
            if resource_format in {"CSV", "PDF", "ZIP", "XLS", "XLSX", "TXT"}:
                continue
            text = f"{url} {resource.get('description', '')} {resource_format}".lower()
            if "/api/" not in text and "api" not in resource_format.lower() and "json" not in text:
                continue

            slug = re.sub(r"[^a-z0-9]+", "-", record_id.lower()).strip("-") or str(index)
            normalized.append(APIRecordCreate.model_validate({
                "id": f"ckan-{slug}-{index}",
                "name": str(resource.get("name") or record["title"]),
                "agency": agency,
                "jurisdiction": "state",
                "country": "US",
                "category": category,
                "base_url": url,
                "documentation_url": f"{self.base_url}/dataset/{record_id}",
                "authentication": "unknown",
                "data_format": ["JSON"] if "json" in text else ["XML"],
                "license": record.get("license_title") or record.get("license_url"),
                "status": "unverified",
                "source_url": f"{self.base_url}/dataset/{record_id}",
                "source_id": self.source_id,
                "source_record_id": record_id,
                "discovered_at": datetime.now(timezone.utc),
                "verification_status": "unverified",
                "last_seen_at": datetime.now(timezone.utc),
            }))
        return normalized
