from collections.abc import Iterable

from .connectors.base import CatalogConnector
from .database import RegistryDatabase


def run_discovery(
    connector: CatalogConnector,
    database: RegistryDatabase,
    limit: int = 100,
) -> dict[str, int]:
    discovered = 0
    normalized = 0
    stored = 0
    run_id = database.start_discovery_run(connector.source_id)
    try:
        for raw in connector.discover(limit=limit):
            discovered += 1
            for record in connector.normalize(raw):
                database.upsert(record)
                normalized += 1
                stored += 1
        database.finish_discovery_run(
            run_id,
            discovered=discovered,
            normalized=normalized,
            stored=stored,
            status="completed",
        )
    except Exception as exc:
        database.finish_discovery_run(
            run_id,
            discovered=discovered,
            normalized=normalized,
            stored=stored,
            status="failed",
            error=str(exc),
        )
        raise
    return {"discovered": discovered, "normalized": normalized, "stored": stored}
