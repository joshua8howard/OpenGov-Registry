# Contributing

Contributions should improve registry coverage, source accuracy, or verification.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
```

## Adding records

Add one or more records to `data/seed.json` or submit a JSON file following `APIRecordCreate` in `src/govapi_registry/models.py`. Each record must include:

- Stable identifier
- Publishing agency
- Jurisdiction and country
- Base URL and documentation URL
- Source or catalog provenance
- Authentication, format, status, and license when known

Do not mark an unknown field as available or public domain. Preserve the exact source URL and use `unknown` for uncertain values.

## Pull requests

Keep changes focused, include tests for behavior changes, and do not commit `registry.db` or environment secrets.
