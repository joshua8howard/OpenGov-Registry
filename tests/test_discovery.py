import re
from unittest.mock import Mock

import httpx

from govapi_registry.connectors.congress import CongressGovConnector
from govapi_registry.connectors.fec import FECConnector
from govapi_registry.connectors.base import ConnectorAuthenticationError, ConnectorOperationError
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
    assert normalized[0].record_type.value == "api"


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


def test_same_source_url_is_stored_once_across_source_ids(tmp_path):
    db = RegistryDatabase(tmp_path / "single-source.db")
    db.initialize()
    base = {
        "id": "congress-gov",
        "name": "Congress.gov API",
        "agency": "Library of Congress",
        "jurisdiction": "federal",
        "country": "US",
        "category": "legislation",
        "base_url": "https://api.congress.gov/v3/",
        "documentation_url": "https://api.congress.gov/",
        "source_url": "https://www.congress.gov/",
        "source_record_id": None,
    }

    db.upsert(APIRecordCreate.model_validate({**base, "source_id": "manual"}))
    db.upsert(APIRecordCreate.model_validate({**base, "source_id": "www.congress.gov"}))

    assert len(db.list_source_references("congress-gov")) == 1


def test_null_source_record_id_is_stored_once(tmp_path):
    db = RegistryDatabase(tmp_path / "single-source.db")
    db.initialize()
    record = APIRecordCreate.model_validate({
        "id": "congress-gov",
        "name": "Congress.gov API",
        "agency": "Library of Congress",
        "jurisdiction": "federal",
        "country": "US",
        "category": "legislation",
        "base_url": "https://api.congress.gov/v3/",
        "documentation_url": "https://api.congress.gov/",
        "source_url": "https://www.congress.gov/",
        "source_id": "manual",
        "source_record_id": None,
    })

    db.upsert(record)
    db.upsert(record)

    assert len(db.list_source_references(record.id)) == 1


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


def test_datagov_json_download_is_dataset():
    raw = {
        "id": "tariff-data",
        "title": "HTS JSON Edition",
        "organization": {"title": "US International Trade Commission"},
        "url": "https://catalog.data.gov/dataset/hts",
        "resources": [{
            "id": "json-edition",
            "name": "2026 HTS Edition",
            "url": "https://www.usitc.gov/files/hts_2026.json",
            "format": "JSON",
        }],
    }

    normalized = DataGovConnector(http_client=Mock(spec=httpx.Client)).normalize(raw)

    assert len(normalized) == 1
    assert normalized[0].record_type.value == "dataset"


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


def test_congress_connector_exposes_documented_endpoint_families():
    connector = CongressGovConnector(api_key="test-key")

    assert len(connector.operations) >= 100
    assert "/bill/{congress}/{billType}/{billNumber}/text" in connector.operations
    assert "/committee-meeting/{congress}/{chamber}/{eventId}" in connector.operations
    assert "/treaty/{congress}/{treatyNumber}/{treatySuffix}/actions" in connector.operations


def test_fec_connector_loads_every_swagger_get_path():
    spec_response = Mock(spec=httpx.Response)
    spec_response.raise_for_status.return_value = None
    spec_response.json.return_value = {
        "paths": {
            "/v1/candidates/": {"get": {}},
            "/v1/candidate/{candidate_id}/": {"get": {}},
            "/v1/schedules/schedule_a/{sub_id}/": {"get": {}},
        }
    }
    spec_client = Mock(spec=httpx.Client)
    spec_client.get.return_value = spec_response

    connector = FECConnector(
        api_key="test-key",
        http_client=Mock(spec=httpx.Client),
        spec_http_client=spec_client,
    )
    connector.discover_operations()

    assert len(connector.operations) >= 6
    assert "/v1/candidate/{candidate_id}/" in connector.operations
    assert "/v1/schedules/schedule_a/{sub_id}/" in connector.operations


def test_fec_static_inventory_matches_documented_routes():
    connector = FECConnector(api_key="test-key")

    assert len(set(connector._static_paths)) == 101

    connector.discover_operations = lambda: None
    connector.operations = {
        path: path.lstrip("/").removeprefix("v1/")
        for path in connector._static_paths
    }
    assert "/v1/schedules/schedule_a/{sub_id}/" in connector.operations
    assert "/v1/candidate/{candidate_id}/totals/" in connector.operations
    assert "/v1/audit-case/" in connector.operations
    assert "/v1/legal/docs/{doc_type}/{no}" in connector.operations


def test_fec_connector_builds_raw_schedule_a_path():
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {"results": []}
    client = Mock(spec=httpx.Client)
    client.get.return_value = response
    connector = FECConnector(api_key="test-key", http_client=client)
    connector.discover_operations = lambda: None
    connector.operations = {
        "/v1/schedules/schedule_a/{sub_id}/":
        "schedules/schedule_a/{sub_id}/"
    }

    connector.execute(
        "/v1/schedules/schedule_a/{sub_id}/",
        {"sub_id": "ABC123", "per_page": 10},
    )

    client.get.assert_called_once_with(
        "https://api.open.fec.gov/v1/schedules/schedule_a/ABC123/",
        params={"per_page": 10, "api_key": "test-key"},
    )


def test_congress_connector_builds_authenticated_bill_request():
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "bills": [{"number": "1", "type": "HR"}],
        "pagination": {"count": 1},
    }
    client = Mock(spec=httpx.Client)
    client.get.return_value = response

    connector = CongressGovConnector(api_key="test-congress-key", http_client=client)
    payload = connector.execute("bills", {"limit": 25})

    assert payload["bills"][0]["number"] == "1"
    client.get.assert_called_once_with(
        "https://api.congress.gov/v3/bill",
        params={"limit": 25, "api_key": "test-congress-key"},
    )


def test_normalized_pagination_is_preserved():
    connector = CongressGovConnector(api_key="test-key")
    normalized = connector.normalize_response({
        "amendments": [{"number": "1"}],
        "pagination": {
            "count": 129041,
            "next": "https://api.congress.gov/v3/amendment?offset=20",
        },
    })

    assert normalized["data"] == [{"number": "1"}]
    assert normalized["pagination"]["count"] == 129041
    assert normalized["pagination"]["next"].endswith("offset=20")


def test_congress_connector_builds_bill_detail_path():
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {"bill": {"number": "1"}}
    client = Mock(spec=httpx.Client)
    client.get.return_value = response

    connector = CongressGovConnector(api_key="test-key", http_client=client)
    connector.execute("bill", congress=118, bill_type="hr", bill_number=1)

    client.get.assert_called_once_with(
        "https://api.congress.gov/v3/bill/118/hr/1",
        params={"api_key": "test-key"},
    )


def test_congress_list_endpoint_names_do_not_resolve_as_details():
    connector = CongressGovConnector(api_key="test-key", http_client=Mock(spec=httpx.Client))

    assert connector.resolve_operation("amendment", {}) == "/amendment"
    assert connector.resolve_operation("bill", {}) == "/bill"
    assert connector.resolve_operation("member", {}) == "/member"


def test_congress_raw_paths_accept_camel_and_snake_placeholder_parameters():
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {"actions": []}
    client = Mock(spec=httpx.Client)
    client.get.return_value = response
    connector = CongressGovConnector(api_key="test-key", http_client=client)

    connector.execute(
        "/bill/{congress}/{billType}/{billNumber}/actions",
        {"congress": 118, "billType": "hr", "billNumber": 1, "limit": 20},
    )

    client.get.assert_called_once_with(
        "https://api.congress.gov/v3/bill/118/hr/1/actions",
        params={"limit": 20, "api_key": "test-key"},
    )


def test_fec_connector_builds_candidate_request_and_normalizes_results():
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [{"candidate_id": "H0TEST"}],
        "pagination": {"count": 1},
    }
    client = Mock(spec=httpx.Client)
    client.get.return_value = response

    connector = FECConnector(api_key="test-fec-key", http_client=client)
    raw = connector.execute("candidates", {"office": "H"})
    normalized = connector.normalize_response(raw)

    assert normalized["data"] == [{"candidate_id": "H0TEST"}]
    assert normalized["pagination"] == {"count": 1}
    client.get.assert_any_call(
        "https://api.open.fec.gov/v1/candidates",
        params={"office": "H", "api_key": "test-fec-key"},
    )


def test_execution_connectors_require_keys_and_known_operations(monkeypatch):
    monkeypatch.delenv("CONGRESS_API_KEY", raising=False)
    monkeypatch.delenv("CONGRESS_GOV_API_KEY", raising=False)
    monkeypatch.delenv("FEC_API_KEY", raising=False)
    monkeypatch.delenv("OPENFEC_API_KEY", raising=False)
    congress = CongressGovConnector(api_key=None, http_client=Mock(spec=httpx.Client))
    fec = FECConnector(api_key=None, http_client=Mock(spec=httpx.Client))

    try:
        congress.execute("bills")
        assert False, "Congress connector should require an API key"
    except ConnectorAuthenticationError:
        pass

    try:
        fec.execute("unknown")
        assert False, "FEC connector should reject an unknown operation"
    except ConnectorAuthenticationError:
        pass
    except ConnectorOperationError:
        pass
