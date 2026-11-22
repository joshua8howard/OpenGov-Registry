from abc import ABC, abstractmethod
from collections.abc import Iterable
import re
from urllib.parse import quote
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..verification import validate_public_url, UnsafeURLError


class ConnectorError(RuntimeError):
    """Base error raised by connector execution."""


class ConnectorAuthenticationError(ConnectorError):
    """Raised when a required API key is unavailable."""


class ConnectorOperationError(ConnectorError):
    """Raised when an operation or path is invalid."""


class ConnectorUpstreamError(ConnectorError):
    """Raised when an upstream API request fails."""


class ExecutionConnector(ABC):
    """Execute a known government API operation."""

    connector_id: str
    base_url: str
    operations: dict[str, str]

    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self.http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    @abstractmethod
    def authenticate(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Add API authentication to request parameters."""

    def discover_operations(self) -> None:
        """Load or refresh operation metadata. Static connectors need no refresh."""

    def execute(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.discover_operations()
        params = dict(parameters or {})
        params.update({key: value for key, value in kwargs.items() if value is not None})
        path = self.resolve_operation(operation, params)
        url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

        try:
            validate_public_url(url)
        except UnsafeURLError as exc:
            raise ConnectorOperationError(str(exc)) from exc

        parsed = urlsplit(url)
        allowed_host = urlsplit(self.base_url).hostname
        if parsed.hostname != allowed_host:
            raise ConnectorOperationError("Connector operations must stay on the registered API host")

        params = self.authenticate(params)
        try:
            response = self.http.get(url, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ConnectorUpstreamError("The upstream API timed out") from exc
        except httpx.NetworkError as exc:
            raise ConnectorUpstreamError("The upstream API could not be reached") from exc
        except httpx.HTTPStatusError as exc:
            raise ConnectorUpstreamError(
                f"The upstream API returned HTTP {response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectorUpstreamError("The upstream API request failed") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorUpstreamError("The upstream API did not return JSON") from exc
        if not isinstance(payload, dict):
            raise ConnectorUpstreamError("The upstream API returned an unexpected JSON shape")
        return payload

    def resolve_operation(self, operation: str, parameters: dict[str, Any]) -> str:
        if operation.startswith("/"):
            template = operation
        else:
            template = self.operations.get(operation)
        if template is None:
            template = self.operations.get(operation.rstrip("/"))
        if template is None and operation.startswith("v1/"):
            template = operation
        if template is None:
            raise ConnectorOperationError(
                f"Unknown operation '{operation}'. Available operations: {', '.join(sorted(self.operations))}"
            )
        resolved_parameters = dict(parameters)
        placeholders = re.findall(r"\{([^{}]+)\}", template)
        for placeholder in placeholders:
            if placeholder in resolved_parameters:
                continue
            placeholder_key = re.sub(r"[^a-z0-9]", "", placeholder.lower())
            matching_key = next(
                (
                    key
                    for key in parameters
                    if re.sub(r"[^a-z0-9]", "", str(key).lower()) == placeholder_key
                ),
                None,
            )
            if matching_key is not None:
                resolved_parameters[placeholder] = parameters[matching_key]
        try:
            path = template.format(
                **{
                    key: quote(str(value), safe="")
                    for key, value in resolved_parameters.items()
                }
            )
        except KeyError as exc:
            raise ConnectorOperationError(f"Missing required parameter: {exc.args[0]}") from exc
        for placeholder in re.findall(r"\{([^{}]+)\}", template):
            parameters.pop(placeholder, None)
            placeholder_key = re.sub(r"[^a-z0-9]", "", placeholder.lower())
            for key in list(parameters):
                if re.sub(r"[^a-z0-9]", "", str(key).lower()) == placeholder_key:
                    parameters.pop(key, None)
        if "{" in path or "}" in path:
            raise ConnectorOperationError("Operation path contains unresolved parameters")
        return path

    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("results")
        if data is None:
            data = payload.get("bills") or payload.get("candidates") or payload.get("committees")
        if data is None:
            data = payload.get("amendments")
        if data is None:
            data = payload
        pagination = payload.get("pagination")
        if not isinstance(pagination, dict):
            pagination = {}
        pagination_info = dict(pagination)
        count = pagination_info.get("count")
        if count is not None:
            pagination_info["count"] = count
        return {
            "data": data,
            "pagination": pagination_info or None,
            "meta": payload.get("meta") or payload.get("page"),
        }


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
