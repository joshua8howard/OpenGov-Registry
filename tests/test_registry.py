import json
from pathlib import Path

from fastapi.testclient import TestClient

from govapi_registry.api import create_app
from govapi_registry.database import RegistryDatabase


def test_seed_import_search_and_detail(tmp_path: Path) -> None:
    db = RegistryDatabase(tmp_path / "test.db")
    db.initialize()
    records = json.loads(Path("data/seed.json").read_text(encoding="utf-8"))

    assert db.import_json(records) == len(records)
    assert db.count() == len(records)

    client = TestClient(create_app(db))
    response = client.get("/v1/apis", params={"q": "NYC"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["nyc-open-data"]

    agency_response = client.get("/v1/apis", params={"agency": "City of New York"})
    assert agency_response.status_code == 200
    assert [item["id"] for item in agency_response.json()] == ["nyc-open-data"]

    filtered_stats = client.get(
        "/v1/statistics",
        params={"jurisdiction": "state", "agency": "State of New York"},
    )
    assert filtered_stats.status_code == 200
    assert filtered_stats.json()["apis"] > 0
    assert filtered_stats.json()["sources"] == 1

    detail = client.get("/v1/apis/nyc-open-data")
    assert detail.status_code == 200
    assert detail.json()["agency"] == "City of New York"

    api = client.get("/v1/apis/datagov-catalog")
    assert api.status_code == 200
    assert api.json()["source_id"] == "data-gov"

    catalogs = client.get("/v1/apis", params={"record_type": "catalog"})
    assert catalogs.status_code == 200
    assert catalogs.json() == []

    default_list = client.get("/v1/apis")
    assert "datagov-catalog-source" not in [item["id"] for item in default_list.json()]
    datagov_list = client.get("/v1/apis", params={"source_id": "data-gov"})
    assert datagov_list.status_code == 200

    all_records = client.get("/v1/records", params={"limit": 500})
    assert all_records.status_code == 200
    assert isinstance(all_records.json(), list)
    record_types = {item["record_type"] for item in all_records.json()}
    assert "api" in record_types
    sources = client.get("/v1/source-facets")
    assert sources.status_code == 200
    assert any(item["source_id"] == "data-gov" for item in sources.json())


def test_missing_record_returns_404(tmp_path: Path) -> None:
    db = RegistryDatabase(tmp_path / "test.db")
    db.initialize()
    client = TestClient(create_app(db))

    response = client.get("/v1/apis/not-found")

    assert response.status_code == 404


def test_import_infers_source_from_url(tmp_path: Path) -> None:
    db = RegistryDatabase(tmp_path / "test.db")
    db.initialize()
    record = {
        "id": "example-api",
        "name": "Example API",
        "agency": "Example Agency",
        "jurisdiction": "federal",
        "category": "open-data",
        "base_url": "https://api.example.gov/data/",
        "documentation_url": "https://example.gov/docs",
        "source_url": "https://catalog.example.gov/dataset/1",
    }

    assert db.import_json([record]) == 1
    imported = db.get("example-api")
    assert imported is not None
    assert imported.source_id == "catalog.example.gov"


def test_api_source_dataset_and_statistics_crud(tmp_path: Path) -> None:
    db = RegistryDatabase(tmp_path / "test.db")
    db.initialize()
    client = TestClient(create_app(db))

    source = {
        "id": "example-catalog",
        "name": "Example Catalog",
        "kind": "ckan",
        "base_url": "https://catalog.example.gov/",
        "enabled": True,
    }
    created_source = client.post("/v1/sources", json=source)
    assert created_source.status_code == 201

    api = {
        "id": "example-api",
        "name": "Example API",
        "agency": "Example Agency",
        "jurisdiction": "federal",
        "category": "open-data",
        "base_url": "https://api.example.gov/",
        "documentation_url": "https://example.gov/docs",
        "source_url": "https://catalog.example.gov/",
        "source_id": "example-catalog",
    }
    created_api = client.post("/v1/apis", json=api)
    assert created_api.status_code == 201

    updated_api = client.patch("/v1/apis/example-api", json={"name": "Updated API"})
    assert updated_api.status_code == 200
    assert updated_api.json()["name"] == "Updated API"

    dataset = {
        "id": "example-dataset",
        "title": "Example Dataset",
        "agency": "Example Agency",
        "jurisdiction": "federal",
        "category": "open-data",
        "landing_page": "https://catalog.example.gov/dataset/example",
        "download_url": "https://catalog.example.gov/dataset/example.csv",
        "formats": ["CSV"],
        "source_id": "example-catalog",
    }
    created_dataset = client.post("/v1/datasets", json=dataset)
    assert created_dataset.status_code == 201

    assert client.get("/v1/statistics").status_code == 200
    assert client.get("/v1/jurisdictions").status_code == 200
    assert client.get("/v1/datasets/example-dataset").status_code == 200
    assert client.delete("/v1/datasets/example-dataset").status_code == 204
    assert client.delete("/v1/apis/example-api").status_code == 204


def test_preview_normalizes_json_rows(tmp_path: Path, monkeypatch) -> None:
    db = RegistryDatabase(tmp_path / "test.db")
    db.initialize()
    record = {
        "id": "sample-data",
        "name": "Sample Data",
        "agency": "Sample Agency",
        "jurisdiction": "federal",
        "category": "public-data",
        "base_url": "https://example.gov/data.json",
        "documentation_url": "https://example.gov/docs",
        "source_url": "https://example.gov/catalog",
    }
    db.import_json([record])

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"results":[{"state":"NY","count":2},{"state":"CA","count":4}]}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("govapi_registry.api.validate_public_url", lambda url: url)
    monkeypatch.setattr("govapi_registry.api.httpx.Client", FakeClient)

    client = TestClient(create_app(db))
    response = client.get("/v1/apis/sample-data/preview", params={"limit": 1})

    assert response.status_code == 200
    assert response.json()["format"] == "json"
    assert response.json()["columns"] == ["state", "count"]
    assert response.json()["row_count"] == 2
    assert response.json()["truncated"] is True
    assert response.json()["rows"] == [{"state": "NY", "count": 2}]
