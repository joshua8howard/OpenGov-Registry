from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator


class Jurisdiction(str, Enum):
    FEDERAL = "federal"
    STATE = "state"
    COUNTY = "county"
    MUNICIPAL = "municipal"
    INTERNATIONAL = "international"
    TRIBAL = "tribal"


class Status(str, Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    DEPRECATED = "deprecated"
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAUTHENTICATED = "unauthenticated"
    UNREACHABLE = "unreachable"


class RecordType(str, Enum):
    API = "api"
    DATASET = "dataset"
    CATALOG = "catalog"


class Authentication(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BASIC = "basic"
    UNKNOWN = "unknown"


class APIRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    agency: str
    jurisdiction: Jurisdiction
    country: str = "US"
    category: str
    base_url: HttpUrl
    documentation_url: HttpUrl
    authentication: Authentication = Authentication.UNKNOWN
    data_format: list[Literal["JSON", "XML", "CSV", "GeoJSON"]] = ["JSON"]
    record_type: RecordType = RecordType.API
    canonical_id: str | None = None
    license: str | None = None
    last_verified: datetime | None = None
    status: Status = Status.UNVERIFIED
    openapi_spec_url: HttpUrl | None = None
    source_url: HttpUrl
    source_id: str = "manual"
    source_record_id: str | None = None
    discovered_at: datetime | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    last_seen_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not normalized:
            raise ValueError("id cannot be empty")
        return normalized


class APIRecord(APIRecordCreate):
    created_at: datetime
    updated_at: datetime


class CatalogSource(BaseModel):
    id: str
    name: str
    kind: str
    base_url: HttpUrl
    enabled: bool = True


class VerificationRecord(BaseModel):
    id: int | None = None
    api_record_id: str
    checked_at: datetime
    status: VerificationStatus
    http_status: int | None = None
    response_time_ms: int | None = None
    content_type: str | None = None
    response_bytes: int = 0


class DiscoveryRun(BaseModel):
    id: int | None = None
    source_id: str
    started_at: datetime
    finished_at: datetime | None = None
    discovered: int = 0
    normalized: int = 0
    stored: int = 0
    status: Literal["running", "completed", "failed"] = "running"
    error: str | None = None


class DatasetRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str | None = None
    agency: str
    jurisdiction: Jurisdiction
    country: str = "US"
    category: str
    landing_page: HttpUrl
    download_url: HttpUrl | None = None
    formats: list[Literal["JSON", "XML", "CSV", "GeoJSON"]] = ["CSV"]
    license: str | None = None
    source_id: str = "manual"
    source_record_id: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not normalized:
            raise ValueError("id cannot be empty")
        return normalized


class DatasetRecord(DatasetRecordCreate):
    created_at: datetime
    updated_at: datetime
