import csv
import io
import json

import httpx
from fastapi import FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel

from .database import RegistryDatabase
from .models import APIRecord, APIRecordCreate, CatalogSource, DatasetRecordCreate
from .verification import UnsafeURLError, validate_public_url


class ImportRequest(BaseModel):
    records: list[dict]
    source_id: str | None = None


def create_app(database: RegistryDatabase | None = None) -> FastAPI:
    db = database or RegistryDatabase("registry.db")
    db.initialize()

    app = FastAPI(
        title="GovAPI Registry",
        description="A federated directory of public-sector APIs.",
        version="0.3.0",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/health", tags=["System"])
    def v1_health() -> dict[str, str]:
        return {"status": "ok", "version": "0.4.0"}

    @app.get("/v1/status", tags=["System"])
    def registry_status() -> dict[str, object]:
        stats = db.statistics()
        return {"status": "ok", "version": "0.4.0", "records": stats}

    @app.get("/v1/statistics", tags=["System"])
    def statistics() -> dict:
        return db.statistics()

    @app.get("/v1/statistics/coverage", tags=["System"])
    def coverage() -> dict:
        stats = db.statistics()
        return {"jurisdictions": stats["jurisdictions"], "categories": stats["categories"]}

    @app.get("/v1/source-facets", tags=["Sources"])
    def source_facets() -> list[dict[str, object]]:
        return db.list_sources()

    @app.get("/v1/sources", tags=["Sources"])
    def sources() -> list[dict]:
        return db.list_sources_detailed()

    @app.post("/v1/sources", response_model=CatalogSource, status_code=201, tags=["Sources"])
    def create_source(source: CatalogSource):
        if db.get_source(source.id):
            raise HTTPException(status_code=409, detail="Source already exists")
        return db.upsert_source(source.model_dump(mode="json"))

    @app.get("/v1/sources/{source_id}", tags=["Sources"])
    def get_source(source_id: str):
        source = db.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return source

    @app.get("/v1/sources/{source_id}/apis", tags=["Sources"])
    def source_apis(source_id: str, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
        return db.list(source_id=source_id, limit=limit, offset=offset)

    @app.get("/v1/sources/{source_id}/datasets", tags=["Sources"])
    def source_datasets(source_id: str, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
        return db.list_datasets(source_id=source_id, limit=limit, offset=offset)

    @app.patch("/v1/sources/{source_id}", tags=["Sources"])
    def update_source(source_id: str, source: CatalogSource):
        if db.get_source(source_id) is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return db.upsert_source(source.model_copy(update={"id": source_id}).model_dump(mode="json"))

    @app.delete("/v1/sources/{source_id}", status_code=204, tags=["Sources"])
    def remove_source(source_id: str):
        if not db.delete_source(source_id):
            raise HTTPException(status_code=404, detail="Source not found")
        return Response(status_code=204)

    @app.post("/v1/import")
    def import_records(payload: ImportRequest) -> dict[str, int | str]:
        imported = db.import_json(payload.records, source_id=payload.source_id)
        return {"imported": imported, "source_id": payload.source_id or "inferred"}

    @app.get("/v1/discovery-runs")
    def discovery_runs(limit: int = Query(default=100, ge=1, le=500)):
        return db.list_discovery_runs(limit=limit)

    @app.get("/v1/discovery/runs", tags=["Discovery"])
    def discovery_run_collection(limit: int = Query(default=100, ge=1, le=500)):
        return db.list_discovery_runs(limit=limit)

    @app.get("/v1/export/json", tags=["System"])
    def export_json():
        records = db.list(limit=5000)
        datasets = db.list_datasets(limit=5000)
        return {
            "version": "1.0",
            "exported_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "apis": [record.model_dump(mode="json") for record in records],
            "datasets": datasets,
            "sources": db.list_sources(),
        }

    @app.get("/v1/apis", response_model=list[APIRecord])
    def list_apis(
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        record_type: str | None = None,
        source_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[APIRecord]:
        return db.list(
            q=q,
            jurisdiction=jurisdiction,
            category=category,
            record_type=record_type,
            source_id=source_id,
            limit=limit,
            offset=offset,
        )

    @app.post("/v1/apis", response_model=APIRecord, status_code=201, tags=["APIs"])
    def create_api(payload: APIRecordCreate):
        if db.get(payload.id):
            raise HTTPException(status_code=409, detail="API already exists")
        return db.upsert(payload)

    @app.patch("/v1/apis/{record_id}", response_model=APIRecord, tags=["APIs"])
    def update_api(record_id: str, changes: dict):
        updated = db.update_api(record_id, changes)
        if updated is None:
            raise HTTPException(status_code=404, detail="API record not found")
        return updated

    @app.delete("/v1/apis/{record_id}", status_code=204, tags=["APIs"])
    def delete_api(record_id: str):
        if not db.delete_api(record_id):
            raise HTTPException(status_code=404, detail="API record not found")
        return Response(status_code=204)

    @app.get("/v1/apis/{record_id}/sources")
    def get_sources(record_id: str):
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="API record not found")
        return {
            "canonical_id": record.canonical_id,
            "sources": db.list_source_references(record_id),
        }

    @app.get("/v1/apis/{record_id}/verifications")
    def get_verifications(record_id: str, limit: int = Query(default=100, ge=1, le=500)):
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="API record not found")
        return db.list_verifications(record_id, limit=limit)

    @app.get("/v1/apis/{record_id}/preview")
    def preview_record(record_id: str, limit: int = Query(default=50, ge=1, le=500)):
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="API record not found")

        url = str(record.base_url)
        try:
            validate_public_url(url)
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                upstream = client.get(url)
        except UnsafeURLError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Source endpoint could not be reached") from exc

        if upstream.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Source endpoint returned HTTP {upstream.status_code}",
            )

        content_type = upstream.headers.get("content-type", "").lower()
        text = upstream.text
        rows: list[dict[str, object]] = []
        detected_format = "json"

        if "csv" in content_type or url.lower().endswith(".csv"):
            detected_format = "csv"
            reader = csv.DictReader(io.StringIO(text))
            rows = [{key: value for key, value in row.items()} for row in reader]
        else:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=502, detail="Source endpoint did not return JSON or CSV") from exc

            if isinstance(payload, list):
                candidate_rows = payload
            elif isinstance(payload, dict):
                candidate_rows = next(
                    (value for value in payload.values() if isinstance(value, list)),
                    [payload],
                )
            else:
                candidate_rows = [{"value": payload}]

            for item in candidate_rows:
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    rows.append({"value": item})

        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)

        truncated = len(rows) > limit
        preview_rows = rows[:limit]
        return {
            "record_id": record_id,
            "source_url": url,
            "format": detected_format,
            "content_type": content_type or "text/plain",
            "row_count": len(rows),
            "columns": columns,
            "truncated": truncated,
            "rows": preview_rows,
        }
    @app.get("/v1/apis/{record_id}", response_model=APIRecord)
    def get_api(record_id: str) -> APIRecord:
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="API record not found")
        return record

    @app.get("/v1/datasets", tags=["Datasets"])
    def list_datasets(
        q: str | None = None,
        jurisdiction: str | None = None,
        category: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        return db.list_datasets(q=q, jurisdiction=jurisdiction, category=category, limit=limit, offset=offset)

    @app.post("/v1/datasets", status_code=201, tags=["Datasets"])
    def create_dataset(payload: DatasetRecordCreate):
        if db.get_dataset(payload.id):
            raise HTTPException(status_code=409, detail="Dataset already exists")
        return db.upsert_dataset(payload)

    @app.get("/v1/datasets/{dataset_id}", tags=["Datasets"])
    def get_dataset(dataset_id: str):
        dataset = db.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return dataset

    @app.patch("/v1/datasets/{dataset_id}", tags=["Datasets"])
    def update_dataset(dataset_id: str, changes: dict):
        current = db.get_dataset(dataset_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        merged = {**current, **{key: value for key, value in changes.items() if value is not None}}
        merged["id"] = dataset_id
        return db.upsert_dataset(DatasetRecordCreate.model_validate(merged))

    @app.delete("/v1/datasets/{dataset_id}", status_code=204, tags=["Datasets"])
    def remove_dataset(dataset_id: str):
        if not db.delete_dataset(dataset_id):
            raise HTTPException(status_code=404, detail="Dataset not found")
        return Response(status_code=204)

    @app.get("/v1/jurisdictions", tags=["Reference Data"])
    def jurisdictions() -> list[str]:
        return ["federal", "state", "county", "municipal", "international", "tribal"]

    @app.get("/v1/countries", tags=["Reference Data"])
    def countries() -> list[str]:
        return ["US", "International"]

    @app.get("/v1/agencies", tags=["Reference Data"])
    def agencies() -> list[str]:
        return sorted({row.agency for row in db.list(limit=5000)})

    @app.get("/v1/categories", tags=["Reference Data"])
    def categories() -> list[str]:
        stats = db.statistics()
        return [row["category"] for row in stats["categories"]]

    @app.get("/v1/formats", tags=["Reference Data"])
    def formats() -> list[str]:
        return ["JSON", "XML", "CSV", "GeoJSON"]

    @app.get("/v1/authentication-methods", tags=["Reference Data"])
    def authentication_methods() -> list[str]:
        return ["none", "api_key", "oauth2", "basic", "unknown"]

    return app


app = create_app()
