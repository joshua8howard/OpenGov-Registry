"""SQLite persistence and read-write operations for the registry."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from .canonical import canonical_id
from .models import (
    APIRecord,
    APIRecordCreate,
    DatasetRecordCreate,
    DiscoveryRun,
    VerificationRecord,
)


class RegistryDatabase:
    """Persistence boundary for APIs, sources, datasets, and run history."""

    def __init__(self, path: str | Path = "registry.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict:
        return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS api_records (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    agency TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    country TEXT NOT NULL,
                    category TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    documentation_url TEXT NOT NULL,
                    authentication TEXT NOT NULL,
                    data_format TEXT NOT NULL,
                    license TEXT,
                    last_verified TEXT,
                    status TEXT NOT NULL,
                    openapi_spec_url TEXT,
                    source_url TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT 'manual',
                    source_record_id TEXT,
                    discovered_at TEXT,
                    verification_status TEXT NOT NULL DEFAULT 'unverified',
                    last_seen_at TEXT,
                    record_type TEXT NOT NULL DEFAULT 'api',
                    canonical_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS api_source_references (
                    api_record_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_record_id TEXT,
                    source_url TEXT,
                    discovered_at TEXT,
                    last_seen_at TEXT,
                    PRIMARY KEY(api_record_id, source_id, source_record_id),
                    FOREIGN KEY(api_record_id) REFERENCES api_records(id)
                )
            """)
            connection.execute("""
                DELETE FROM api_source_references
                WHERE rowid NOT IN (
                    SELECT MIN(rowid)
                    FROM api_source_references
                    GROUP BY api_record_id,
                             COALESCE(source_url, ''),
                             COALESCE(source_record_id, '')
                )
            """)
            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_api_source_references
                ON api_source_references (
                    api_record_id,
                    source_id,
                    COALESCE(source_record_id, ''),
                    COALESCE(source_url, '')
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    normalized INTEGER NOT NULL DEFAULT 0,
                    stored INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    error TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS verification_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_record_id TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    response_time_ms INTEGER,
                    content_type TEXT,
                    response_bytes INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(api_record_id) REFERENCES api_records(id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS catalog_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    agency TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    country TEXT NOT NULL,
                    category TEXT NOT NULL,
                    landing_page TEXT NOT NULL,
                    download_url TEXT,
                    formats TEXT NOT NULL,
                    license TEXT,
                    source_id TEXT NOT NULL DEFAULT 'manual',
                    source_record_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            new_columns = {
                "source_id": "TEXT NOT NULL DEFAULT 'manual'",
                "source_record_id": "TEXT",
                "discovered_at": "TEXT",
                "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
                "last_seen_at": "TEXT",
                "record_type": "TEXT NOT NULL DEFAULT 'api'",
                "canonical_id": "TEXT",
            }
            existing = {row[1] for row in connection.execute("PRAGMA table_info(api_records)")}
            for name, declaration in new_columns.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE api_records ADD COLUMN {name} {declaration}")

            migrated = connection.execute("""
                    SELECT *
                    FROM api_records
                    WHERE source_id = 'data-gov'
                      AND (record_type IS NULL OR record_type = 'api')
                      AND lower(base_url) LIKE '%.json%'
            """).fetchall()
            for row in migrated:
                    data = dict(row)
                    connection.execute(
                        "UPDATE api_records SET record_type = 'dataset', updated_at = ? WHERE id = ?",
                        (self._utc_now(), data["id"]),
                    )
                    connection.execute("""
                        INSERT INTO datasets (
                            id, title, description, agency, jurisdiction, country, category,
                            landing_page, download_url, formats, license, source_id,
                            source_record_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            title=excluded.title,
                            description=excluded.description,
                            agency=excluded.agency,
                            jurisdiction=excluded.jurisdiction,
                            country=excluded.country,
                            category=excluded.category,
                            landing_page=excluded.landing_page,
                            download_url=excluded.download_url,
                            formats=excluded.formats,
                            license=excluded.license,
                            source_id=excluded.source_id,
                            source_record_id=excluded.source_record_id,
                            updated_at=excluded.updated_at
                    """, (
                        data["id"],
                        data["name"],
                        None,
                        data["agency"],
                        data["jurisdiction"],
                        data["country"],
                        data["category"],
                        data["documentation_url"] or data["source_url"],
                        data["base_url"],
                        data["data_format"],
                        data["license"],
                        data["source_id"],
                        data["source_record_id"],
                        data["created_at"],
                        data["updated_at"],
                    ))

    # ------------------------------------------------------------------
    # API records
    # ------------------------------------------------------------------

    def upsert(self, record: APIRecordCreate) -> APIRecord:
        now = self._utc_now()
        if record.source_id == "manual":
            record = record.model_copy(update={"source_id": self.infer_source_id(str(record.source_url))})
        values = record.model_dump(mode="json")
        values["data_format"] = json.dumps(values["data_format"])
        generated_canonical_id = record.canonical_id or canonical_id(str(record.base_url))
        values["canonical_id"] = generated_canonical_id

        with self.connect() as connection:
            canonical_match = connection.execute(
                "SELECT id, created_at FROM api_records WHERE canonical_id = ?",
                (generated_canonical_id,),
            ).fetchone()
            source_match = connection.execute(
                "SELECT id, created_at FROM api_records WHERE id = ?", (record.id,),
            ).fetchone()
            existing = canonical_match or source_match
            canonical_record_id = existing["id"] if existing else record.id
            created_at = existing["created_at"] if existing else now
            values["id"] = canonical_record_id

            connection.execute("""
                INSERT INTO api_records (
                    id, name, agency, jurisdiction, country, category, base_url,
                    documentation_url, authentication, data_format, license,
                    last_verified, status, openapi_spec_url, source_url,
                    source_id, source_record_id, discovered_at, record_type, canonical_id,
                    verification_status, last_seen_at, created_at, updated_at
                ) VALUES (
                    :id, :name, :agency, :jurisdiction, :country, :category, :base_url,
                    :documentation_url, :authentication, :data_format, :license,
                    :last_verified, :status, :openapi_spec_url, :source_url,
                    :source_id, :source_record_id, :discovered_at, :record_type, :canonical_id,
                    :verification_status, :last_seen_at, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    agency=excluded.agency,
                    jurisdiction=excluded.jurisdiction,
                    country=excluded.country,
                    category=excluded.category,
                    base_url=excluded.base_url,
                    documentation_url=excluded.documentation_url,
                    authentication=excluded.authentication,
                    data_format=excluded.data_format,
                    license=excluded.license,
                    last_verified=excluded.last_verified,
                    status=excluded.status,
                    openapi_spec_url=excluded.openapi_spec_url,
                    source_url=excluded.source_url,
                    source_id=excluded.source_id,
                    source_record_id=excluded.source_record_id,
                    discovered_at=COALESCE(excluded.discovered_at, api_records.discovered_at),
                    record_type=excluded.record_type,
                    canonical_id=excluded.canonical_id,
                    verification_status=excluded.verification_status,
                    last_seen_at=excluded.last_seen_at,
                    updated_at=excluded.updated_at
            """, {**values, "created_at": created_at, "updated_at": now})

            connection.execute("""
                DELETE FROM api_source_references
                WHERE api_record_id = ?
                  AND COALESCE(source_url, '') = COALESCE(?, '')
                  AND (
                      (? IS NULL AND source_record_id IS NULL)
                      OR source_record_id = ?
                  )
            """, (
                canonical_record_id,
                str(record.source_url),
                record.source_record_id,
                record.source_record_id,
            ))
            connection.execute("""
                INSERT INTO api_source_references (
                    api_record_id, source_id, source_record_id, source_url,
                    discovered_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                canonical_record_id,
                record.source_id,
                record.source_record_id,
                str(record.source_url),
                values["discovered_at"],
                values["last_seen_at"],
            ))

            if record.record_type == "dataset":
                connection.execute("""
                    INSERT INTO datasets (
                        id, title, description, agency, jurisdiction, country, category,
                        landing_page, download_url, formats, license, source_id,
                        source_record_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        description=excluded.description,
                        agency=excluded.agency,
                        jurisdiction=excluded.jurisdiction,
                        country=excluded.country,
                        category=excluded.category,
                        landing_page=excluded.landing_page,
                        download_url=excluded.download_url,
                        formats=excluded.formats,
                        license=excluded.license,
                        source_id=excluded.source_id,
                        source_record_id=excluded.source_record_id,
                        updated_at=excluded.updated_at
                """, (
                    canonical_record_id,
                    record.name,
                    None,
                    record.agency,
                    record.jurisdiction.value,
                    record.country,
                    record.category,
                    str(record.documentation_url),
                    str(record.base_url),
                    values["data_format"],
                    str(record.license) if record.license else None,
                    record.source_id,
                    record.source_record_id,
                    created_at,
                    now,
                ))

        return self.get(canonical_record_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Source identity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def infer_source_id(source_url: str) -> str:
        host = (urlsplit(source_url).hostname or "manual").lower()
        known = {
            "catalog.data.gov": "data-gov",
            "data.gov": "data-gov",
            "dev.socrata.com": "socrata",
            "opendata.cityofnewyork.us": "socrata:nyc",
            "data.cityofchicago.org": "socrata:chicago",
            "data.boston.gov": "ckan:boston",
            "data.ca.gov": "ckan:california",
            "data.texas.gov": "socrata:texas",
        }
        if host in known:
            return known[host]
        return host

    # ------------------------------------------------------------------
    # Discovery runs
    # ------------------------------------------------------------------

    def start_discovery_run(self, source_id: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute("""
                INSERT INTO discovery_runs (source_id, started_at, status)
                VALUES (?, ?, 'running')
            """, (source_id, datetime.now(timezone.utc).isoformat()))
            return int(cursor.lastrowid)

    def finish_discovery_run(
        self,
        run_id: int,
        *,
        discovered: int,
        normalized: int,
        stored: int,
        status: str = "completed",
        error: str | None = None,
    ) -> DiscoveryRun:
        with self.connect() as connection:
            connection.execute("""
                UPDATE discovery_runs SET
                    finished_at = ?, discovered = ?, normalized = ?, stored = ?,
                    status = ?, error = ?
                WHERE id = ?
            """, (
                datetime.now(timezone.utc).isoformat(), discovered, normalized,
                stored, status, error, run_id,
            ))
            row = connection.execute(
                "SELECT * FROM discovery_runs WHERE id = ?", (run_id,)
            ).fetchone()
        data = dict(row)
        return DiscoveryRun.model_validate(data)

    # ------------------------------------------------------------------
    # Provenance and OpenAPI metadata
    # ------------------------------------------------------------------

    def list_source_references(self, api_record_id: str):
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT
                    source_id,
                    source_record_id,
                    source_url,
                    discovered_at,
                    last_seen_at
                FROM api_source_references
                WHERE api_record_id = ?
                  AND rowid IN (
                      SELECT MIN(rowid)
                      FROM api_source_references
                      WHERE api_record_id = ?
                      GROUP BY COALESCE(source_url, ''),
                               COALESCE(source_record_id, '')
                  )
                ORDER BY source_url, source_id, source_record_id
            """, (api_record_id, api_record_id)).fetchall()
        return [dict(row) for row in rows]

    def set_openapi_spec(self, api_record_id: str, spec_url: str) -> None:
        with self.connect() as connection:
            connection.execute("""
                UPDATE api_records SET openapi_spec_url = ?, updated_at = ?
                WHERE id = ?
            """, (spec_url, datetime.now(timezone.utc).isoformat(), api_record_id))

    def list_discovery_runs(self, limit: int = 100) -> list[DiscoveryRun]:
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT * FROM discovery_runs
                ORDER BY started_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [DiscoveryRun.model_validate(dict(row)) for row in rows]

    # ------------------------------------------------------------------
    # Verification history
    # ------------------------------------------------------------------

    def record_verification(self, api_record_id: str, result: dict) -> VerificationRecord:
        checked_at = result["last_verified"]
        checked_at_value = checked_at.isoformat() if isinstance(checked_at, datetime) else str(checked_at)
        with self.connect() as connection:
            cursor = connection.execute("""
                INSERT INTO verification_records (
                    api_record_id, checked_at, status, http_status,
                    response_time_ms, content_type, response_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                api_record_id,
                checked_at_value,
                result["status"],
                result.get("http_status"),
                result.get("response_time_ms"),
                result.get("content_type"),
                result.get("response_bytes", 0),
            ))
            connection.execute("""
                UPDATE api_records SET
                    verification_status = ?, last_verified = ?,
                    status = ?, updated_at = ?
                WHERE id = ?
            """, (
                result["status"], checked_at_value,
                "active" if result["status"] == "healthy" else "degraded"
                if result["status"] == "degraded" else "unknown",
                datetime.now(timezone.utc).isoformat(), api_record_id,
            ))
            row = connection.execute(
                "SELECT * FROM verification_records WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        data = dict(row)
        data["checked_at"] = data.pop("checked_at")
        data["api_record_id"] = data.pop("api_record_id")
        return VerificationRecord.model_validate(data)

    def list_verifications(self, api_record_id: str, limit: int = 100) -> list[VerificationRecord]:
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT * FROM verification_records
                WHERE api_record_id = ?
                ORDER BY checked_at DESC LIMIT ?
            """, (api_record_id, limit)).fetchall()
        return [VerificationRecord.model_validate(dict(row)) for row in rows]

    # ------------------------------------------------------------------
    # API record retrieval and CRUD
    # ------------------------------------------------------------------

    def get(self, record_id: str) -> APIRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM api_records WHERE id = ?", (record_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list(
        self,
        *,
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        agency: str | None = None,
        record_type: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[APIRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if q:
            clauses.append("(name LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
            needle = f"%{q}%"
            params.extend([needle, needle, needle, needle, needle])
        if jurisdiction:
            clauses.append("jurisdiction = ?")
            params.append(jurisdiction)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if agency:
            clauses.append("agency = ?")
            params.append(agency)
        if record_type:
            clauses.append("record_type = ?")
            params.append(record_type)
        else:
            clauses.append("(record_type IS NULL OR record_type = 'api')")
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM api_records {where} ORDER BY name LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [record for row in rows if (record := self._to_record(row))]

    def list_records(
        self,
        *,
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        agency: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        api_clauses: list[str] = ["(record_type IS NULL OR record_type IN ('api', 'catalog'))"]
        api_params: list[object] = []
        dataset_clauses: list[str] = []
        dataset_params: list[object] = []

        for where_clauses, params, name_expression, dataset_mode in (
            (api_clauses, api_params, "(name LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)", False),
            (dataset_clauses, dataset_params, "(title LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)", True),
        ):
            if q:
                where_clauses.append(name_expression)
                params.extend([f"%{q}%"] * 5)
            if jurisdiction:
                where_clauses.append("jurisdiction = ?")
                params.append(jurisdiction)
            if category:
                where_clauses.append("category = ?")
                params.append(category)
            if agency:
                where_clauses.append("agency = ?")
                params.append(agency)
            if source_id:
                where_clauses.append("source_id = ?")
                params.append(source_id)

        api_where = f"WHERE {' AND '.join(api_clauses)}"
        dataset_where = f"WHERE {' AND '.join(dataset_clauses)}" if dataset_clauses else ""
        with self.connect() as connection:
            rows = connection.execute(f"""
                SELECT id, name, agency, jurisdiction, category, base_url,
                       documentation_url, authentication, data_format, license,
                       status, source_url, source_id, verification_status,
                       'api' AS record_type, created_at, updated_at
                FROM api_records
                {api_where}
                UNION ALL
                SELECT id, title AS name, agency, jurisdiction,
                       category, download_url AS base_url, landing_page AS documentation_url,
                       'unknown' AS authentication, formats AS data_format, license,
                       'unknown' AS status, landing_page AS source_url, source_id,
                       'unverified' AS verification_status,
                       'dataset' AS record_type, created_at, updated_at
                FROM datasets
                {dataset_where}
                ORDER BY name
                LIMIT ? OFFSET ?
            """, api_params + dataset_params + [limit, offset]).fetchall()

        results: list[dict] = []
        for row in rows:
            data = dict(row)
            data["data_format"] = json.loads(data["data_format"]) if isinstance(data["data_format"], str) else data["data_format"]
            data["authentication"] = data["authentication"] if data["authentication"] else "unknown"
            results.append(data)
        return results

    def count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM api_records").fetchone()
        return int(row["total"])

    def delete_api(self, record_id: str) -> bool:
        with self.connect() as connection:
            connection.execute("DELETE FROM api_source_references WHERE api_record_id = ?", (record_id,))
            connection.execute("DELETE FROM verification_records WHERE api_record_id = ?", (record_id,))
            cursor = connection.execute("DELETE FROM api_records WHERE id = ?", (record_id,))
            return cursor.rowcount > 0

    def update_api(self, record_id: str, changes: dict) -> APIRecord | None:
        current = self.get(record_id)
        if current is None:
            return None
        merged = current.model_dump()
        merged.pop("created_at", None)
        merged.pop("updated_at", None)
        merged.update({key: value for key, value in changes.items() if value is not None})
        updated = APIRecordCreate.model_validate({**merged, "id": record_id})
        return self.upsert(updated)

    # ------------------------------------------------------------------
    # Catalog source management
    # ------------------------------------------------------------------

    def list_sources_detailed(self):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM catalog_sources ORDER BY name"
            ).fetchall()
        return [
            {**self._row_dict(row), "enabled": bool(row["enabled"])}
            for row in rows
        ]

    def upsert_source(self, source):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("""
                INSERT INTO catalog_sources (id,name,kind,base_url,enabled,created_at,updated_at)
                VALUES (:id,:name,:kind,:base_url,:enabled,:created_at,:updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, kind=excluded.kind, base_url=excluded.base_url,
                    enabled=excluded.enabled, updated_at=excluded.updated_at
            """, {**source, "enabled": int(source.get("enabled", True)), "created_at": now, "updated_at": now})
            row = connection.execute("SELECT * FROM catalog_sources WHERE id=?", (source["id"],)).fetchone()
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def get_source(self, source_id: str):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM catalog_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def delete_source(self, source_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM catalog_sources WHERE id=?", (source_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Dataset management
    # ------------------------------------------------------------------

    def list_datasets(
        self,
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        agency: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        clauses, params = [], []
        if q:
            clauses.append("(title LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
            needle = f"%{q}%"
            params += [needle, needle, needle, needle, needle]
        if jurisdiction:
            clauses.append("jurisdiction = ?")
            params.append(jurisdiction)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if agency:
            clauses.append("agency = ?")
            params.append(agency)
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params += [limit, offset]
        with self.connect() as connection:
            rows = connection.execute(f"SELECT * FROM datasets {where} ORDER BY title LIMIT ? OFFSET ?", params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["formats"] = json.loads(data["formats"])
            result.append(data)
        return result

    def upsert_dataset(self, dataset: DatasetRecordCreate):
        now = datetime.now(timezone.utc).isoformat()
        values = dataset.model_dump(mode="json")
        values["formats"] = json.dumps(values["formats"])
        with self.connect() as connection:
            row = connection.execute("SELECT created_at FROM datasets WHERE id=?", (dataset.id,)).fetchone()
            created_at = row["created_at"] if row else now
            connection.execute("""
                INSERT INTO datasets (id,title,description,agency,jurisdiction,country,category,landing_page,download_url,formats,license,source_id,source_record_id,created_at,updated_at)
                VALUES (:id,:title,:description,:agency,:jurisdiction,:country,:category,:landing_page,:download_url,:formats,:license,:source_id,:source_record_id,:created_at,:updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, description=excluded.description, agency=excluded.agency,
                    jurisdiction=excluded.jurisdiction, country=excluded.country, category=excluded.category,
                    landing_page=excluded.landing_page, download_url=excluded.download_url, formats=excluded.formats,
                    license=excluded.license, source_id=excluded.source_id, source_record_id=excluded.source_record_id,
                    updated_at=excluded.updated_at
            """, {**values, "created_at": created_at, "updated_at": now})
            saved = connection.execute("SELECT * FROM datasets WHERE id=?", (dataset.id,)).fetchone()
        data = dict(saved)
        data["formats"] = json.loads(data["formats"])
        return data

    def get_dataset(self, dataset_id: str):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["formats"] = json.loads(data["formats"])
        return data

    def delete_dataset(self, dataset_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Registry statistics and JSON import/export support
    # ------------------------------------------------------------------

    def statistics(
        self,
        *,
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        agency: str | None = None,
        record_type: str | None = None,
        source_id: str | None = None,
    ):
        clauses: list[str] = []
        params: list[object] = []
        if q:
            clauses.append("(name LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
            needle = f"%{q}%"
            params.extend([needle, needle, needle, needle, needle])
        if jurisdiction:
            clauses.append("jurisdiction = ?")
            params.append(jurisdiction)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if agency:
            clauses.append("agency = ?")
            params.append(agency)
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)

        api_clauses = clauses + (["record_type = ?"] if record_type in ("api", "catalog") else [])
        api_params = params + ([record_type] if record_type in ("api", "catalog") else [])
        if record_type not in ("dataset", "catalog"):
            api_clauses.append("(record_type IS NULL OR record_type = 'api')")
        if record_type == "catalog":
            api_clauses = clauses + ["record_type = 'catalog'"]
            api_params = params

        dataset_clauses: list[str] = []
        dataset_params: list[object] = []
        if q:
            dataset_clauses.append("(title LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
            needle = f"%{q}%"
            dataset_params.extend([needle, needle, needle, needle, needle])
        if jurisdiction:
            dataset_clauses.append("jurisdiction = ?")
            dataset_params.append(jurisdiction)
        if category:
            dataset_clauses.append("category = ?")
            dataset_params.append(category)
        if agency:
            dataset_clauses.append("agency = ?")
            dataset_params.append(agency)
        if source_id:
            dataset_clauses.append("source_id = ?")
            dataset_params.append(source_id)

        with self.connect() as connection:
            api_where = f"WHERE {' AND '.join(api_clauses)}" if api_clauses else ""
            dataset_where = f"WHERE {' AND '.join(dataset_clauses)}" if dataset_clauses else ""
            if record_type == "dataset":
                total = 0
            else:
                total = connection.execute(f"SELECT COUNT(*) FROM api_records {api_where}", api_params).fetchone()[0]
            datasets = 0 if record_type in ("api", "catalog") else connection.execute(
                f"SELECT COUNT(*) FROM datasets {dataset_where}", dataset_params
            ).fetchone()[0]
            if record_type == "dataset":
                sources = connection.execute(
                    f"SELECT COUNT(DISTINCT source_id) FROM datasets {dataset_where}", dataset_params
                ).fetchone()[0]
            else:
                api_sources = connection.execute(
                    f"SELECT COUNT(DISTINCT source_id) FROM api_records {api_where}", api_params
                ).fetchone()[0]
                dataset_sources = 0 if record_type in ("api", "catalog") else connection.execute(
                    f"SELECT COUNT(DISTINCT source_id) FROM datasets {dataset_where}", dataset_params
                ).fetchone()[0]
                sources = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT source_id FROM api_records {api_where}
                        UNION
                        SELECT source_id FROM datasets {dataset_where}
                    )
                    """,
                    api_params + dataset_params,
                ).fetchone()[0] if record_type not in ("api", "catalog") else api_sources
            verified_clauses = api_clauses + ["verification_status = 'healthy'"]
            verified_where = f"WHERE {' AND '.join(verified_clauses)}"
            verified = connection.execute(
                f"SELECT COUNT(*) FROM api_records {verified_where}", api_params
            ).fetchone()[0] if record_type != "dataset" else 0
            if record_type == "dataset":
                jurisdictions = connection.execute(
                    f"SELECT jurisdiction,COUNT(*) FROM datasets {dataset_where} GROUP BY jurisdiction",
                    dataset_params,
                ).fetchall()
                categories = connection.execute(
                    f"SELECT category,COUNT(*) FROM datasets {dataset_where} GROUP BY category ORDER BY COUNT(*) DESC LIMIT 20",
                    dataset_params,
                ).fetchall()
            elif record_type == "catalog":
                jurisdictions = connection.execute(
                    f"SELECT jurisdiction,COUNT(*) FROM api_records {api_where} GROUP BY jurisdiction",
                    api_params,
                ).fetchall()
                categories = connection.execute(
                    f"SELECT category,COUNT(*) FROM api_records {api_where} GROUP BY category ORDER BY COUNT(*) DESC LIMIT 20",
                    api_params,
                ).fetchall()
            elif record_type == "api":
                jurisdictions = connection.execute(
                    f"SELECT jurisdiction,COUNT(*) FROM api_records {api_where} GROUP BY jurisdiction",
                    api_params,
                ).fetchall()
                categories = connection.execute(
                    f"SELECT category,COUNT(*) FROM api_records {api_where} GROUP BY category ORDER BY COUNT(*) DESC LIMIT 20",
                    api_params,
                ).fetchall()
            else:
                jurisdiction_where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                jurisdictions = connection.execute(
                    f"SELECT jurisdiction,COUNT(*) FROM api_records {jurisdiction_where} GROUP BY jurisdiction",
                    params,
                ).fetchall()
                category_where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                categories = connection.execute(
                    f"SELECT category,COUNT(*) FROM api_records {category_where} GROUP BY category ORDER BY COUNT(*) DESC LIMIT 20",
                    params,
                ).fetchall()
        return {
            "apis": total,
            "datasets": datasets,
            "sources": sources,
            "verified": verified,
            "jurisdictions": [
                {"jurisdiction": row[0], "count": row[1]}
                for row in jurisdictions
            ],
            "categories": [
                {"category": row[0], "count": row[1]}
                for row in categories
            ],
        }

    def list_sources(
        self,
        *,
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        agency: str | None = None,
        record_type: str | None = None,
    ):
        clauses: list[str] = []
        params: list[object] = []
        clauses.append("(record_type IS NULL OR record_type != 'catalog')")
        if q:
            clauses.append("(name LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
            needle = f"%{q}%"
            params.extend([needle, needle, needle, needle, needle])
        if jurisdiction:
            clauses.append("jurisdiction = ?")
            params.append(jurisdiction)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if agency:
            clauses.append("agency = ?")
            params.append(agency)
        if record_type:
            if record_type == "catalog":
                clauses.append("record_type = 'catalog'")
            elif record_type == "api":
                clauses.append("(record_type IS NULL OR record_type = 'api')")
        with self.connect() as connection:
            where = f"WHERE {' AND '.join(clauses)}"
            if record_type == "dataset":
                dataset_clauses: list[str] = []
                dataset_params: list[object] = []
                if q:
                    dataset_clauses.append("(title LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
                    needle = f"%{q}%"
                    dataset_params.extend([needle, needle, needle, needle, needle])
                if jurisdiction:
                    dataset_clauses.append("jurisdiction = ?")
                    dataset_params.append(jurisdiction)
                if category:
                    dataset_clauses.append("category = ?")
                    dataset_params.append(category)
                if agency:
                    dataset_clauses.append("agency = ?")
                    dataset_params.append(agency)
                dataset_where = f"WHERE {' AND '.join(dataset_clauses)}" if dataset_clauses else ""
                rows = connection.execute(f"""
                    SELECT source_id, COUNT(*) AS record_count
                    FROM datasets
                    {dataset_where}
                    GROUP BY source_id
                    ORDER BY record_count DESC, source_id
                """, dataset_params).fetchall()
            else:
                rows = connection.execute(f"""
                    SELECT source_id, COUNT(*) AS record_count
                    FROM api_records
                    {where}
                    GROUP BY source_id
                    ORDER BY record_count DESC, source_id
                """, params).fetchall()
        return [dict(row) for row in rows]

    def list_agencies(
        self,
        *,
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        record_type: str | None = None,
        source_id: str | None = None,
    ):
        clauses: list[str] = ["(record_type IS NULL OR record_type != 'catalog')"]
        params: list[object] = []
        if q:
            clauses.append("(name LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
            needle = f"%{q}%"
            params.extend([needle, needle, needle, needle, needle])
        if jurisdiction:
            clauses.append("jurisdiction = ?")
            params.append(jurisdiction)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if record_type:
            if record_type == "catalog":
                clauses.append("record_type = 'catalog'")
            elif record_type == "api":
                clauses.append("(record_type IS NULL OR record_type = 'api')")
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        with self.connect() as connection:
            if record_type == "dataset":
                dataset_clauses: list[str] = []
                dataset_params: list[object] = []
                if q:
                    dataset_clauses.append("(title LIKE ? OR agency LIKE ? OR category LIKE ? OR jurisdiction LIKE ? OR source_id LIKE ?)")
                    needle = f"%{q}%"
                    dataset_params.extend([needle, needle, needle, needle, needle])
                if jurisdiction:
                    dataset_clauses.append("jurisdiction = ?")
                    dataset_params.append(jurisdiction)
                if category:
                    dataset_clauses.append("category = ?")
                    dataset_params.append(category)
                if source_id:
                    dataset_clauses.append("source_id = ?")
                    dataset_params.append(source_id)
                dataset_where = f"WHERE {' AND '.join(dataset_clauses)}" if dataset_clauses else ""
                rows = connection.execute(f"""
                    SELECT agency, COUNT(*) AS record_count
                    FROM datasets
                    {dataset_where}
                    GROUP BY agency
                    ORDER BY agency
                """, dataset_params).fetchall()
            else:
                rows = connection.execute(f"""
                    SELECT agency, COUNT(*) AS record_count
                    FROM api_records
                    WHERE {' AND '.join(clauses)}
                    GROUP BY agency
                    ORDER BY agency
                """, params).fetchall()
        return [dict(row) for row in rows]

    def import_json(self, records: Iterable[dict], *, source_id: str | None = None) -> int:
        imported = 0
        for item in records:
            if source_id:
                item = {**item, "source_id": source_id}
            self.upsert(APIRecordCreate.model_validate(item))
            imported += 1
        return imported

    @staticmethod
    def _to_record(row: sqlite3.Row) -> APIRecord:
        data = dict(row)
        data["data_format"] = json.loads(data["data_format"])
        return APIRecord.model_validate(data)
