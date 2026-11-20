from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any


class CatalogConnector(ABC):
    source_id: str

    @abstractmethod
    def discover(self, limit: int = 100) -> Iterable[dict[str, Any]]:
        """Yield raw records discovered in the source catalog."""

    @abstractmethod
    def fetch(self, record_id: str) -> dict[str, Any]:
        """Retrieve source metadata for one record."""

    @abstractmethod
    def normalize(self, record: dict[str, Any]) -> list[Any]:
        """Convert one source record into normalized registry records."""

    @abstractmethod
    def validate(self, record: dict[str, Any]) -> bool:
        """Validate source metadata before normalization."""
