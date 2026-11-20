from collections.abc import Iterable, Mapping
from typing import Any
from datetime import datetime, timezone
from urllib.parse import quote
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

from .base import CatalogConnector
from ..models import APIRecordCreate


class DataGovConnector(CatalogConnector):
    source_id = "data-gov"

    def __init__(
        self,
        base_url: str = "https://api.gsa.gov/technology/datagov/v4",
        http_client: httpx.Client | None = None,
        page_size: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http_client or httpx.Client(timeout=30.0)
        self.page_size = page_size
        self.api_key = os.getenv("DATAGOV_API_KEY")

    def _request_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.api_key:
            return {**params, "api_key": self.api_key}
        return params

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def discover(self, limit: int = 100) -> Iterable[dict[str, Any]]:
        yielded = 0
        start = 0
        while yielded < limit:
            rows = min(self.page_size, limit - yielded)
            response = self.http.get(
                f"{self.base_url}/search",
                params=self._request_params({"start": start, "rows": rows}),
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
            records = payload.get("results")
            if records is None:
                result = payload.get("result", {})
                records = result.get("results", []) if isinstance(result, Mapping) else []
            if not records:
                return
            for record in records:
                if yielded >= limit:
                    return
                if self.validate(record):
                    yield record
                yielded += 1
            start += len(records)

    def fetch(self, record_id: str) -> dict[str, Any]:
        response = self.http.get(
            f"{self.base_url}/search?q=id:{quote(record_id)}",
            headers=self._headers(),
            params=self._request_params({}),
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("results")
        if not records:
            result = payload.get("result", {})
            records = result.get("results", []) if isinstance(result, Mapping) else []
        for record in records:
            if record.get("id") == record_id:
                return record
        raise LookupError(f"Data.gov record {record_id} not found")

    def validate(self, record: dict[str, Any]) -> bool:
        dcat = record.get("dcat") if isinstance(record.get("dcat"), Mapping) else {}
        title = record.get("title") or dcat.get("title")
        distributions = record.get("resources") or dcat.get("distribution") or []
        return bool((record.get("id") or record.get("identifier")) and title and distributions)

    def normalize(self, record: dict[str, Any]) -> list[APIRecordCreate]:
        normalized: list[APIRecordCreate] = []
        if not self.validate(record):
            return normalized

        dcat = record.get("dcat") if isinstance(record.get("dcat"), Mapping) else {}
        resources = record.get("resources") or dcat.get("distribution") or []
        for resource in resources:
            url = resource.get("url") or resource.get("downloadURL") or resource.get("describedBy")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue

            resource_format = str(resource.get("format") or resource.get("mediaType") or "").upper().strip()
            description = f"{resource.get('description', '')} {resource.get('name', '')} {resource.get('title', '')}".lower()
            api_kind = self._api_kind(url, resource_format, description)
            if api_kind is None:
                continue

            record_id = str(record.get("id") or record.get("identifier") or "unknown")
            base_url = url.rstrip("/")
            title = str(record.get("title") or dcat.get("title") or "Government API")
            name = str(resource.get("name") or resource.get("title") or title).strip()
            organization = record.get("organization") or dcat.get("publisher") or {}
            if isinstance(record.get("publisher"), Mapping):
                organization = record["publisher"]
            agency = str(
                organization.get("title")
                or organization.get("name")
                or record.get("publisher")
                or "U.S. government"
            )
            id_source = str(resource.get("id") or base_url)
            id_suffix = re.sub(r"[^a-z0-9]+", "-", str(id_source).lower()).strip("-")[-80:] or "resource"
            record_slug = re.sub(r"[^a-z0-9]+", "-", record_id.lower()).strip("-")[-60:] or "record"
            normalized_id = f"datagov-{record_slug}-{id_suffix}"

            documentation_url = self._extract_url(
                record.get("landing_page")
                or dcat.get("landingPage")
                or record.get("url")
                or dcat.get("landing_page")
            ) or f"https://catalog.data.gov/dataset/{record_id}"
            source_url = self._extract_url(record.get("url") or dcat.get("landingPage") or dcat.get("landing_page")) \
                or f"https://catalog.data.gov/dataset/{record_id}"

            normalized.append(APIRecordCreate.model_validate({
                "id": normalized_id,
                "name": name,
                "agency": agency,
                "jurisdiction": "federal",
                "country": "US",
                "category": self._category(record),
                "base_url": base_url,
                "documentation_url": documentation_url,
                "authentication": "unknown",
                "data_format": [api_kind],
                "license": record.get("license_title") or dcat.get("license"),
                "status": "unverified",
                "source_url": source_url,
                "source_id": self.source_id,
                "source_record_id": record_id,
                "discovered_at": datetime.now(timezone.utc),
                "verification_status": "unverified",
                "last_seen_at": datetime.now(timezone.utc),
            }))
        return normalized

    @staticmethod
    def _extract_url(value: Any) -> str | None:
        if isinstance(value, str):
            return value if value.startswith(("http://", "https://")) else None
        if isinstance(value, Mapping):
            for key in ("url", "@id", "identifier", "href"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
        return None

    @staticmethod
    def _api_kind(url: str, resource_format: str, description: str) -> str | None:
        text = f"{url} {description}".lower()
        format_lower = resource_format.lower()
        if any(marker in format_lower for marker in ("text/csv", "csv", "excel", "pdf", "zip", "text/plain")):
            return None
        if "graphql" in text:
            return "JSON"
        if "sparql" in text:
            return "JSON"
        if "odata" in text:
            return "JSON"
        if "geo+json" in format_lower or "geojson" in text:
            return "GeoJSON"
        if "application/json" in format_lower or ".json" in text or "/api/" in text:
            return "JSON"
        if "application/xml" in format_lower or ".xml" in text:
            return "XML"
        if resource_format in {"API", "JSON", "XML", "GEOJSON", "WMS", "WFS", "KML"}:
            if resource_format == "GEOJSON":
                return "GeoJSON"
            if resource_format in {"XML", "JSON"}:
                return resource_format
            return "GeoJSON" if resource_format in {"WMS", "WFS", "KML"} else "JSON"
        if "/api/" in text or "api.json" in text or "swagger" in text or "openapi" in text:
            return "JSON"
        return None

    @staticmethod
    def _category(record: dict[str, Any]) -> str:
        groups = record.get("groups") or []
        if groups:
            title = groups[0].get("title") if isinstance(groups[0], Mapping) else None
            if title:
                return str(title).lower().replace(" ", "-")
        dcat = record.get("dcat") if isinstance(record.get("dcat"), Mapping) else {}
        themes = dcat.get("theme") or []
        if themes:
            return str(themes[0]).lower().replace(" ", "-")
        tags = record.get("tags") or record.get("keyword") or []
        for tag in tags:
            name = tag.get("name") if isinstance(tag, Mapping) else str(tag)
            if name:
                return str(name).lower().replace(" ", "-")
        return "open-data"
