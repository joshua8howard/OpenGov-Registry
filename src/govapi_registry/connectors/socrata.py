from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import CatalogConnector
from ..models import APIRecordCreate


class SocrataConnector(CatalogConnector):
    source_id = "socrata"

    def __init__(
        self,
        domain: str = "data.cityofnewyork.us",
        http_client: httpx.Client | None = None,
        jurisdiction: str = "municipal",
    ) -> None:
        self.domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        self.http = http_client or httpx.Client(timeout=30.0)
        self.jurisdiction = jurisdiction

    def discover(self, limit: int = 100) -> Iterable[dict[str, Any]]:
        offset = 0
        while offset < limit:
            page_limit = min(100, limit - offset)
            response = self.http.get(
                f"https://api.us.socrata.com/api/catalog/v1",
                params={"limit": page_limit, "offset": offset, "domains": self.domain},
            )
            response.raise_for_status()
            records = response.json().get("results", [])
            if not records:
                return
            for record in records:
                if self.validate(record):
                    yield record
            offset += len(records)

    def fetch(self, record_id: str) -> dict[str, Any]:
        response = self.http.get(
            f"https://api.us.socrata.com/api/catalog/v1",
            params={"limit": 1, "search_context": self.domain, "q": record_id},
        )
        response.raise_for_status()
        for result in response.json().get("results", []):
            resource = result.get("resource", {})
            if resource.get("id") == record_id:
                return result
        raise LookupError(f"Socrata record {record_id} not found")

    def validate(self, record: dict[str, Any]) -> bool:
        resource = record.get("resource")
        return isinstance(resource, dict) and bool(resource.get("id") and resource.get("name"))

    def normalize(self, record: dict[str, Any]) -> list[APIRecordCreate]:
        if not self.validate(record):
            return []
        resource = record["resource"]
        metadata = record.get("metadata", {})
        domain_metadata = record.get("classification", {})
        record_id = str(resource["id"])
        base_url = f"https://{self.domain}/resource/{record_id}.json"
        name = str(resource["name"])
        agency = str(
            metadata.get("domain")
            or metadata.get("name")
            or domain_metadata.get("domain_category")
            or self.domain
        )
        categories = domain_metadata.get("domain_category") or resource.get("category")
        category = str(categories).lower().replace(" ", "-") if categories else "open-data"

        return [APIRecordCreate.model_validate({
            "id": f"socrata-{self.domain}-{record_id}",
            "name": name,
            "agency": agency,
            "jurisdiction": self.jurisdiction,
            "country": "US",
            "category": category,
            "base_url": base_url,
            "documentation_url": f"https://{self.domain}/d/{record_id}",
            "authentication": "api_key" if resource.get("id") else "none",
            "data_format": ["JSON", "CSV", "GeoJSON"],
            "license": metadata.get("license"),
            "status": "unverified",
            "source_url": f"https://{self.domain}/d/{record_id}",
            "source_id": f"socrata:{self.domain}",
            "source_record_id": record_id,
            "discovered_at": datetime.now(timezone.utc),
            "verification_status": "unverified",
            "last_seen_at": datetime.now(timezone.utc),
        })]
