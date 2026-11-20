import re
from unittest.mock import Mock

import httpx

from govapi_registry.connectors.datagov import DataGovConnector
from govapi_registry.connectors.socrata import SocrataConnector
from govapi_registry.connectors.ckan import CKANConnector
from govapi_registry.database import RegistryDatabase
from govapi_registry.discovery import run_discovery
from govapi_registry.models import APIRecordCreate


def test_datagov_distinguishes_api_resources_from_downloads():
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [{
            "id": "spending-data",
            "title": "Federal Spending",
            "landing_page": "https://catalog.example/dataset/spending",
            "url": "https://catalog.example/dataset/spending",
            "organization": {"title": "U.S. Treasury"},
            "resources": [
                {"id": "rest", "name": "Spending REST API", "url": "https://api.example.gov/spending", "format": "API", "description": "JSON REST API"},
                {"id": "csv", "name": "Monthly CSV", "url": "https://example.gov/spending.csv", "format": "CSV"},
            ],
        }]
    }

    client = Mock(spec=httpx.Client)
    client.get.return_value = response

    connector = DataGovConnector(http_client=client)
    records = list(connector.discover(limit=1))
    normalized = connector.normalize(records[0])

    assert len(normalized) == 1
    assert normalized[0].name == "Spending REST API"
    assert normalized[0].agency == "U.S. Treasury"
    assert normalized[0].source_record_id == "spending-data"


def test_socrata_normalization():
    raw = {
        "resource": {"id": "abcd-1234", "name": "City Contracts"},
        "metadata": {"domain": "NYC Open Data"},
        "classification": {"domain_category": "Finance"},
    }
    connector = SocrataConnector()

    records = connector.normalize(raw)

    assert len(records) == 1
    assert str(records[0].base_url) == "https://data.cityofnewyork.us/resource/abcd-1234.json"
    assert records[0].source_id == "socrata:data.cityofnewyork.us"


def test_ckan_normalization():
    raw = {
        "id": "roads",
        "title": "Road Inventory",
        "organization": {"title": "State DOT"},
        "groups": [{"title": "Transportation"}],
        "resources": [{"name": "Road API", "url": "https://data.example.gov/api/roads", "format": "JSON"}],
    }
    connector = CKANConnector("https://catalog.example.gov")

    records = connector.normalize(raw)

    assert len(records) == 1
    assert records[0].agency == "State DOT"
    assert records[0].source_record_id == "roads"
    assert records[0].source_id == "ckan:catalog.example.gov"


def test_discovery_run_is_persisted(tmp_path):
    db = RegistryDatabase(tmp_path / "discovery.db")
    db.initialize()
    raw = {
        "resource": {"id": "abcd-1234", "name": "City Contracts"},
        "metadata": {"domain": "NYC Open Data"},
    }
    client = Mock(spec=httpx.Client)
    connector = SocrataConnector(http_client=client)
    connector.discover = lambda limit=100: iter([raw])

    result = run_discovery(connector, db, limit=1)

    assert result["stored"] == 1
    runs = db.list_discovery_runs()
    assert len(runs) == 1
    assert runs[0].status == "completed"


def test_duplicate_urls_preserve_source_references(tmp_path):
    db = RegistryDatabase(tmp_path / "duplicates.db")
    db.initialize()
    base = {
        "agency": "Example Agency",
        "jurisdiction": "federal",
        "country": "US",
        "category": "transportation",
        "base_url": "https://api.example.gov/v1/roads",
        "documentation_url": "https://example.gov/docs/roads",
        "source_url": "https://catalog.example.gov/roads",
    }
    first = APIRecordCreate.model_validate({**base, "id": "source-a", "name": "Roads A", "source_id": "source-a", "source_record_id": "1"})
    second = APIRecordCreate.model_validate({**base, "id": "source-b", "name": "Roads B", "source_id": "source-b", "source_record_id": "2"})

    first_record = db.upsert(first)
    second_record = db.upsert(second)

    assert first_record.id == second_record.id
    assert db.count() == 1
    assert len(db.list_source_references(first_record.id)) == 2


def test_datagov_normalizes_dcat_v4_distribution():
    raw = {
        "identifier": "https://data.example.gov/api/views/abc123",
        "title": "Example Dataset",
        "dcat": {
            "title": "Example Dataset",
            "landingPage": "https://data.example.gov/d/abc123",
            "publisher": {"name": "Example State Agency"},
            "license": "https://example.gov/license",
            "theme": ["Health"],
            "distribution": [
                {"downloadURL": "https://data.example.gov/api/views/abc123/query.json", "mediaType": "application/json"},
                {"downloadURL": "https://data.example.gov/api/views/abc123/export.csv", "mediaType": "text/csv"},
            ],
        },
    }
    connector = DataGovConnector(http_client=Mock(spec=httpx.Client))

    normalized = connector.normalize(raw)

    assert len(normalized) == 1
    assert normalized[0].agency == "Example State Agency"
    assert normalized[0].category == "health"
    assert normalized[0].data_format == ["JSON"]


def test_datagov_normalization_is_repeatable():
    raw = {
        "id": "weather",
        "title": "Weather API",
        "organization": {"title": "NOAA"},
        "url": "https://catalog.example/dataset/weather",
        "resources": [{"id": "json", "name": "Forecast API", "url": "https://api.example.gov/weather", "format": "JSON"}],
    }
    connector = DataGovConnector(http_client=Mock(spec=httpx.Client))

    first = connector.normalize(raw)
    second = connector.normalize(raw)

    assert [record.id for record in first] == [record.id for record in second]


def test_datagov_normalized_ids_are_url_safe():
    raw = {
        "id": "https://example.gov/datasets/records/1",
        "title": "Example API",
        "organization": {"title": "Example Agency"},
        "url": "https://catalog.example.gov/dataset/example",
        "resources": [{
            "id": "https://api.example.gov/v1/results.json",
            "name": "Example JSON API",
            "url": "https://api.example.gov/v1/results.json",
            "format": "JSON",
        }],
    }

    normalized = DataGovConnector(http_client=Mock(spec=httpx.Client)).normalize(raw)

    assert len(normalized) == 1
    assert re.fullmatch(r"[a-z0-9-]+", normalized[0].id)
