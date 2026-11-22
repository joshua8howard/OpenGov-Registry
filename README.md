# GovAPI Registry

GovAPI Registry is an open-source, machine-readable directory of public-sector APIs. It preserves source attribution and normalizes federal, state, county, municipal, tribal, and international records for discovery and reuse.

## Status

This is the 0.3.0 multi-source discovery prototype. It provides:

- A normalized Pydantic API record model
- SQLite storage and JSON import
- A searchable FastAPI public API
- Data.gov, Socrata, and CKAN catalog connectors
- Execution connectors for Congress.gov and the Federal Election Commission openFEC API
- Complete documented Congress.gov route families and openFEC Swagger GET endpoints
- Canonical duplicate resolution with source-attribution references
- OpenAPI specification discovery
- Discovery-run and verification-history persistence
- SSRF-protected endpoint verification
- Seed records for Data.gov, USAspending, NYC Open Data, and Congress.gov
- A CLI for imports and local serving

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m govapi_registry.cli import data/seed.json
python -m govapi_registry.cli serve
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation.

After installation, start the API with the shorter command:

```powershell
govapi
```

You can also keep the explicit form:

## API examples

```text
GET /health
GET /v1/apis
GET /v1/apis?q=spending
GET /v1/apis?jurisdiction=federal
GET /v1/apis?category=procurement
GET /v1/apis/usa-spending
GET /v1/connectors
GET /v1/connectors/congress-gov/operations
POST /v1/connectors/congress-gov/execute
```

## CLI

```powershell
govapi import data/seed.json
govapi serve --host 127.0.0.1 --port 8000
```

Discover Data.gov records. For a persistent local configuration, copy `.env.example` to `.env` and set the key:

```dotenv
DATAGOV_API_KEY=your-key
```

You can also set it for only the current PowerShell session:

```powershell
$env:DATAGOV_API_KEY = "your-key"
govapi discover --source datagov --limit 100
govapi discover --source socrata --limit 100
govapi discover --source ckan --limit 100 --ckan-url https://demo.ckan.org

# Execute built-in API connectors
$env:CONGRESS_API_KEY="your-key"
govapi execute congress bills --params '{"limit":20}'

$env:FEC_API_KEY="your-key"
govapi execute fec candidates --params '{"state":"NY","office":"H","per_page":20}'

govapi verify usa-spending
govapi openapi usa-spending
```

## Record principles

- Every record points to the original source and documentation.
- Government portals are discoverability sources, not implied data hosts.
- Verification, status, authentication, and licensing are distinct fields.
- Community submissions should include provenance and maintainable source URLs.

## Development

```powershell
pytest
python -m compileall -q src tests
```

## Project roadmap

1. Add scheduled discovery and verification runs.
2. Normalize Socrata, ArcGIS, and agency-specific metadata.
3. Verify endpoints and documentation on a schedule.
4. Publish machine-readable exports and OpenAPI specifications.
5. Add community contributions, review, and source-health signals.

## License

MIT
