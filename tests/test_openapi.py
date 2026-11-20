import httpx

from govapi_registry.openapi import OpenAPIDiscovery


def test_openapi_discovery_finds_json_spec(monkeypatch):
    monkeypatch.setattr("govapi_registry.openapi.validate_public_url", lambda url: url)
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openapi.json"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"openapi": "3.1.0", "info": {"title": "Roads API", "version": "1.0"}, "paths": {"/roads": {}}},
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    discovery = OpenAPIDiscovery(client=client)

    result = discovery.discover("https://example.gov/docs")

    assert result is not None
    assert result["openapi_spec_url"] == "https://example.gov/docs/openapi.json"
    assert result["path_count"] == 1


def test_openapi_discovery_rejects_non_spec_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"hello": "world"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    discovery = OpenAPIDiscovery(client=client)

    assert discovery.discover("https://example.gov/docs") is None
