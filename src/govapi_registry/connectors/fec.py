import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

from .base import ConnectorAuthenticationError, ExecutionConnector


class FECConnector(ExecutionConnector):
    """Execution connector for the openFEC API."""

    connector_id = "fec"
    base_url = "https://api.open.fec.gov/v1/"
    spec_url = "https://api.open.fec.gov/swagger/"
    _static_paths = (
        "/v1/audit-case/",
        "/v1/audit-category/",
        "/v1/audit-primary-category/",
        "/v1/calendar-dates/",
        "/v1/calendar-dates/export/",
        "/v1/candidate/{candidate_id}/",
        "/v1/candidate/{candidate_id}/committees/",
        "/v1/candidate/{candidate_id}/committees/history/",
        "/v1/candidate/{candidate_id}/committees/history/{cycle}/",
        "/v1/candidate/{candidate_id}/filings/",
        "/v1/candidate/{candidate_id}/history/",
        "/v1/candidate/{candidate_id}/history/{cycle}/",
        "/v1/candidate/{candidate_id}/totals/",
        "/v1/candidates/",
        "/v1/candidates/search/",
        "/v1/candidates/totals/",
        "/v1/candidates/totals/aggregates/",
        "/v1/committee/{committee_id}/",
        "/v1/committee/{committee_id}/candidates/",
        "/v1/committee/{committee_id}/candidates/history/",
        "/v1/committee/{committee_id}/candidates/history/{cycle}/",
        "/v1/committee/{committee_id}/filings/",
        "/v1/committee/{committee_id}/history/",
        "/v1/committee/{committee_id}/history/{cycle}/",
        "/v1/committee/{committee_id}/reports/",
        "/v1/committee/{committee_id}/totals/",
        "/v1/committees/",
        "/v1/communication_costs/",
        "/v1/communication_costs/aggregates/",
        "/v1/communication_costs/by_candidate/",
        "/v1/communication_costs/totals/by_candidate/",
        "/v1/efile/filings/",
        "/v1/efile/form1/",
        "/v1/efile/form2/",
        "/v1/efile/reports/house-senate/",
        "/v1/efile/reports/pac-party/",
        "/v1/efile/reports/presidential/",
        "/v1/election-dates/",
        "/v1/electioneering/",
        "/v1/electioneering/aggregates/",
        "/v1/electioneering/by_candidate/",
        "/v1/electioneering/totals/by_candidate/",
        "/v1/elections/",
        "/v1/elections/search/",
        "/v1/elections/summary/",
        "/v1/filings/",
        "/v1/legal/docs/{doc_type}/{no}",
        "/v1/legal/search/",
        "/v1/names/audit_candidates/",
        "/v1/names/audit_committees/",
        "/v1/names/candidates/",
        "/v1/names/committees/",
        "/v1/national_party/schedule_a/",
        "/v1/national_party/schedule_b/",
        "/v1/national_party/totals/",
        "/v1/operations-log/",
        "/v1/presidential/contributions/by_candidate/",
        "/v1/presidential/contributions/by_size/",
        "/v1/presidential/contributions/by_state/",
        "/v1/presidential/coverage_end_date/",
        "/v1/presidential/financial_summary/",
        "/v1/rad-analyst/",
        "/v1/reporting-dates/",
        "/v1/reports/{entity_type}/",
        "/v1/rulemaking/search/",
        "/v1/schedules/schedule_a/",
        "/v1/schedules/schedule_a/by_employer/",
        "/v1/schedules/schedule_a/by_occupation/",
        "/v1/schedules/schedule_a/by_size/",
        "/v1/schedules/schedule_a/by_size/by_candidate/",
        "/v1/schedules/schedule_a/by_state/",
        "/v1/schedules/schedule_a/by_state/by_candidate/",
        "/v1/schedules/schedule_a/by_state/by_candidate/totals/",
        "/v1/schedules/schedule_a/by_state/totals/",
        "/v1/schedules/schedule_a/by_zip/",
        "/v1/schedules/schedule_a/efile/",
        "/v1/schedules/schedule_a/{sub_id}/",
        "/v1/schedules/schedule_a_form5/",
        "/v1/schedules/schedule_b/",
        "/v1/schedules/schedule_b/by_purpose/",
        "/v1/schedules/schedule_b/by_recipient/",
        "/v1/schedules/schedule_b/by_recipient_id/",
        "/v1/schedules/schedule_b/efile/",
        "/v1/schedules/schedule_b/{sub_id}/",
        "/v1/schedules/schedule_h4/",
        "/v1/schedules/schedule_h4/efile/",
        "/v1/schedules/schedule_c/",
        "/v1/schedules/schedule_c/{sub_id}/",
        "/v1/schedules/schedule_d/",
        "/v1/schedules/schedule_d/{sub_id}/",
        "/v1/schedules/schedule_e/",
        "/v1/schedules/schedule_e/all_candidates/support_oppose_totals/",
        "/v1/schedules/schedule_e/by_candidate/",
        "/v1/schedules/schedule_e/efile/",
        "/v1/schedules/schedule_e/totals/by_candidate/",
        "/v1/schedules/schedule_f/",
        "/v1/schedules/schedule_f/{sub_id}/",
        "/v1/schedules/schedule_h4/",
        "/v1/schedules/schedule_h4/efile/",
        "/v1/state-election-office/",
        "/v1/totals/by_entity/",
        "/v1/totals/inaugural_committees/by_contributor/",
        "/v1/totals/{entity_type}/",
    )

    operations: dict[str, str] = {}

    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        spec_http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(http_client=http_client, timeout=timeout)
        self.api_key = api_key or os.getenv("FEC_API_KEY") or os.getenv("OPENFEC_API_KEY")
        self.spec_http = spec_http_client or http_client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._operations_loaded = False

    def discover_operations(self) -> None:
        if self._operations_loaded:
            return
        if not self.operations:
            for path in self._static_paths:
                template = path.lstrip("/")
                if template.startswith("v1/"):
                    template = template[3:]
                self.operations[path] = template
                operation_name = re.sub(r"\{([^}]+)\}", r"\1", path)
                operation_name = re.sub(r"[^a-zA-Z0-9]+", "-", operation_name.strip("/"))
                operation_name = re.sub(r"-+", "-", operation_name).strip("-").lower()
                if operation_name:
                    self.operations.setdefault(operation_name, template)
            self.operations.update({
                "candidate": "candidate/{candidate_id}/",
                    "candidate_list": "candidates",
                    "candidates": "candidates",
                "committee": "committee/{committee_id}/",
                "committee_list": "committees",
                "committees": "committees",
                "filing": "committee/{committee_id}/filings/",
                "filings": "committee/{committee_id}/filings/",
                "financial": "committee/{committee_id}/totals/",
                "totals": "committee/{committee_id}/totals/",
                "candidate_totals": "candidate/{candidate_id}/totals/",
            })
        try:
            response = self.spec_http.get(self.spec_url)
            response.raise_for_status()
            spec = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._operations_loaded = True
            return

        paths = spec.get("paths")
        if not isinstance(paths, dict):
            self._operations_loaded = True
            return

        for path, methods in paths.items():
            if not isinstance(methods, dict) or "get" not in methods:
                continue
            template = path.lstrip("/")
            if template.startswith("v1/"):
                template = template[3:]
            self.operations[path] = template
            operation_name = re.sub(r"\{([^}]+)\}", r"\1", path)
            operation_name = re.sub(r"[^a-zA-Z0-9]+", "-", operation_name.strip("/"))
            operation_name = re.sub(r"-+", "-", operation_name).strip("-").lower()
            if operation_name:
                self.operations.setdefault(operation_name, template)

        self._operations_loaded = True

    def authenticate(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ConnectorAuthenticationError(
                "The FEC API requires an API key. Set FEC_API_KEY or pass api_key."
            )
        return {**parameters, "api_key": self.api_key}

    def resolve_operation(self, operation: str, parameters: dict[str, Any]) -> str:
        if operation.startswith("/"):
            parameter_aliases = {
                "candidateId": "candidate_id",
                "committeeId": "committee_id",
                "cycle": "cycle",
                "subId": "sub_id",
                "sub_id": "sub_id",
                "docType": "doc_type",
                "doc_type": "doc_type",
                "entityType": "entity_type",
                "entity_type": "entity_type",
                "reportType": "report_type",
            }
            for source, target in parameter_aliases.items():
                if source in parameters:
                    parameters.setdefault(target, parameters[source])
                    if source != target:
                        parameters.pop(source, None)
            if operation.startswith("/v1/"):
                operation = operation[len("/v1"):]
            return super().resolve_operation(operation, parameters)
        normalized = re.sub(r"[^a-z0-9]+", "_", operation.lower()).strip("_")
        aliases = {
            "get_candidates": "candidate_list",
            "get_candidate": "candidate",
            "get_committees": "committee_list",
            "get_committee": "committee",
            "get_filings": "filings",
            "get_totals": "totals",
        }
        normalized = aliases.get(normalized, normalized)
        normalized_parameters = {
            "candidate_id": parameters.pop("candidateId", parameters.pop("candidate_id", None)),
            "committee_id": parameters.pop("committeeId", parameters.pop("committee_id", None)),
        }
        parameters.update({key: value for key, value in normalized_parameters.items() if value is not None})
        path = super().resolve_operation(normalized, parameters)
        for key in normalized_parameters:
            parameters.pop(key, None)
        return path

    def get_candidates(self, **parameters: Any) -> dict[str, Any]:
        return self.execute("candidate_list", **parameters)

    def get_candidate(self, candidate_id: str, **parameters: Any) -> dict[str, Any]:
        return self.execute("candidate", candidate_id=candidate_id, **parameters)

    def get_committees(self, **parameters: Any) -> dict[str, Any]:
        return self.execute("committee_list", **parameters)

    def get_committee(self, committee_id: str, **parameters: Any) -> dict[str, Any]:
        return self.execute("committee", committee_id=committee_id, **parameters)


# Compatibility name for integrations that refer to the service.
OpenFECConnector = FECConnector
