import ipaddress

import httpx

from govapi_registry.verification import EndpointVerifier, UnsafeURLError, validate_public_url


def test_blocks_private_addresses(monkeypatch):
    monkeypatch.setattr("govapi_registry.verification.socket.getaddrinfo", lambda *_args: [(2, 1, 6, "", ("127.0.0.1", 80))])

    try:
        validate_public_url("http://internal.example.test/api")
    except UnsafeURLError:
        pass
    else:
        raise AssertionError("Private address should be blocked")


def test_verifier_classifies_unauthenticated_response(monkeypatch):
    monkeypatch.setattr("govapi_registry.verification.validate_public_url", lambda url: url)
    response = httpx.Response(403, headers={"content-type": "application/json"}, content=b'{}')
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: response))

    result = EndpointVerifier(client=client).verify("https://api.example.gov/data")

    assert result["status"] == "unauthenticated"
    assert result["http_status"] == 403


def test_verification_history_is_persisted(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from pathlib import Path

    from govapi_registry.database import RegistryDatabase
    from govapi_registry.models import APIRecordCreate

    db = RegistryDatabase(tmp_path / "verification.db")
    db.initialize()
    record = APIRecordCreate.model_validate({
        "id": "verify-example",
        "name": "Verification Example",
        "agency": "Example Agency",
        "jurisdiction": "federal",
        "country": "US",
        "category": "open-data",
        "base_url": "https://api.example.gov/data",
        "documentation_url": "https://example.gov/docs",
        "source_url": "https://example.gov/catalog",
    })
    db.upsert(record)

    result = {
        "status": "healthy",
        "http_status": 200,
        "response_time_ms": 42,
        "content_type": "application/json",
        "response_bytes": 128,
        "last_verified": datetime.now(timezone.utc),
    }
    first = db.record_verification(record.id, result)
    db.record_verification(record.id, result)

    assert first.api_record_id == "verify-example"
    assert len(db.list_verifications("verify-example")) == 2
    assert db.get("verify-example").verification_status == "healthy"


def test_verifier_handles_timeout(monkeypatch):
    monkeypatch.setattr("govapi_registry.verification.validate_public_url", lambda url: url)

    def timeout(request):
        raise httpx.TimeoutException("timeout", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout))
    result = EndpointVerifier(client=client).verify("https://api.example.gov/data")

    assert result["status"] == "unreachable"
