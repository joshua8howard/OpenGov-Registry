import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

from .base import (
    ConnectorAuthenticationError,
    ConnectorOperationError,
    ExecutionConnector,
)


class CongressGovConnector(ExecutionConnector):
    """Execution connector for the Congress.gov API."""

    connector_id = "congress-gov"
    base_url = "https://api.congress.gov/v3/"
    operations = {
        "/bill": "bill",
        "/bill/{congress}": "bill/{congress}",
        "/bill/{congress}/{billType}": "bill/{congress}/{billType}",
        "/bill/{congress}/{billType}/{billNumber}": "bill/{congress}/{billType}/{billNumber}",
        "/bill/{congress}/{billType}/{billNumber}/actions": "bill/{congress}/{billType}/{billNumber}/actions",
        "/bill/{congress}/{billType}/{billNumber}/amendments": "bill/{congress}/{billType}/{billNumber}/amendments",
        "/bill/{congress}/{billType}/{billNumber}/committees": "bill/{congress}/{billType}/{billNumber}/committees",
        "/bill/{congress}/{billType}/{billNumber}/cosponsors": "bill/{congress}/{billType}/{billNumber}/cosponsors",
        "/bill/{congress}/{billType}/{billNumber}/relatedbills": "bill/{congress}/{billType}/{billNumber}/relatedbills",
        "/bill/{congress}/{billType}/{billNumber}/subjects": "bill/{congress}/{billType}/{billNumber}/subjects",
        "/bill/{congress}/{billType}/{billNumber}/summaries": "bill/{congress}/{billType}/{billNumber}/summaries",
        "/bill/{congress}/{billType}/{billNumber}/text": "bill/{congress}/{billType}/{billNumber}/text",
        "/bill/{congress}/{billType}/{billNumber}/titles": "bill/{congress}/{billType}/{billNumber}/titles",
        "/law/{congress}": "law/{congress}",
        "/law/{congress}/{lawType}": "law/{congress}/{lawType}",
        "/law/{congress}/{lawType}/{lawNumber}": "law/{congress}/{lawType}/{lawNumber}",
        "/amendment": "amendment",
        "/amendment/{congress}": "amendment/{congress}",
        "/amendment/{congress}/{amendmentType}": "amendment/{congress}/{amendmentType}",
        "/amendment/{congress}/{amendmentType}/{amendmentNumber}": "amendment/{congress}/{amendmentType}/{amendmentNumber}",
        "/amendment/{congress}/{amendmentType}/{amendmentNumber}/actions": "amendment/{congress}/{amendmentType}/{amendmentNumber}/actions",
        "/amendment/{congress}/{amendmentType}/{amendmentNumber}/cosponsors": "amendment/{congress}/{amendmentType}/{amendmentNumber}/cosponsors",
        "/amendment/{congress}/{amendmentType}/{amendmentNumber}/amendments": "amendment/{congress}/{amendmentType}/{amendmentNumber}/amendments",
        "/amendment/{congress}/{amendmentType}/{amendmentNumber}/text": "amendment/{congress}/{amendmentType}/{amendmentNumber}/text",
        "/summaries": "summaries",
        "/summaries/{congress}": "summaries/{congress}",
        "/summaries/{congress}/{billType}": "summaries/{congress}/{billType}",
        "/congress": "congress",
        "/congress/{congress}": "congress/{congress}",
        "/congress/current": "congress/current",
        "/member": "member",
        "/member/{bioguideId}": "member/{bioguideId}",
        "/member/{bioguideId}/sponsored-legislation": "member/{bioguideId}/sponsored-legislation",
        "/member/{bioguideId}/cosponsored-legislation": "member/{bioguideId}/cosponsored-legislation",
        "/member/congress/{congress}": "member/congress/{congress}",
        "/member/{stateCode}": "member/{stateCode}",
        "/member/{stateCode}/{district}": "member/{stateCode}/{district}",
        "/member/congress/{congress}/{stateCode}/{district}": "member/congress/{congress}/{stateCode}/{district}",
        "/house-vote": "house-vote",
        "/house-vote/{congress}": "house-vote/{congress}",
        "/house-vote/{congress}/{session}": "house-vote/{congress}/{session}",
        "/house-vote/{congress}/{session}/{voteNumber}": "house-vote/{congress}/{session}/{voteNumber}",
        "/house-vote/{congress}/{session}/{voteNumber}/members": "house-vote/{congress}/{session}/{voteNumber}/members",
        "/committee": "committee",
        "/committee/{chamber}": "committee/{chamber}",
        "/committee/{congress}": "committee/{congress}",
        "/committee/{congress}/{chamber}": "committee/{congress}/{chamber}",
        "/committee/{chamber}/{committeeCode}": "committee/{chamber}/{committeeCode}",
        "/committee/{congress}/{chamber}/{committeeCode}": "committee/{congress}/{chamber}/{committeeCode}",
        "/committee/{chamber}/{committeeCode}/bills": "committee/{chamber}/{committeeCode}/bills",
        "/committee/{chamber}/{committeeCode}/reports": "committee/{chamber}/{committeeCode}/reports",
        "/committee/{chamber}/{committeeCode}/nominations": "committee/{chamber}/{committeeCode}/nominations",
        "/committee/{chamber}/{committeeCode}/house-communication": "committee/{chamber}/{committeeCode}/house-communication",
        "/committee/{chamber}/{committeeCode}/senate-communication": "committee/{chamber}/{committeeCode}/senate-communication",
        "/committee-report": "committee-report",
        "/committee-report/{congress}": "committee-report/{congress}",
        "/committee-report/{congress}/{reportType}": "committee-report/{congress}/{reportType}",
        "/committee-report/{congress}/{reportType}/{reportNumber}": "committee-report/{congress}/{reportType}/{reportNumber}",
        "/committee-report/{congress}/{reportType}/{reportNumber}/text": "committee-report/{congress}/{reportType}/{reportNumber}/text",
        "/committee-print": "committee-print",
        "/committee-print/{congress}": "committee-print/{congress}",
        "/committee-print/{congress}/{chamber}": "committee-print/{congress}/{chamber}",
        "/committee-print/{congress}/{chamber}/{jacketNumber}": "committee-print/{congress}/{chamber}/{jacketNumber}",
        "/committee-print/{congress}/{chamber}/{jacketNumber}/text": "committee-print/{congress}/{chamber}/{jacketNumber}/text",
        "/committee-meeting": "committee-meeting",
        "/committee-meeting/{congress}": "committee-meeting/{congress}",
        "/committee-meeting/{congress}/{chamber}": "committee-meeting/{congress}/{chamber}",
        "/committee-meeting/{congress}/{chamber}/{eventId}": "committee-meeting/{congress}/{chamber}/{eventId}",
        "/hearing": "hearing",
        "/hearing/{congress}": "hearing/{congress}",
        "/hearing/{congress}/{chamber}": "hearing/{congress}/{chamber}",
        "/hearing/{congress}/{chamber}/{jacketNumber}": "hearing/{congress}/{chamber}/{jacketNumber}",
        "/congressional-record": "congressional-record",
        "/daily-congressional-record": "daily-congressional-record",
        "/daily-congressional-record/{volumeNumber}": "daily-congressional-record/{volumeNumber}",
        "/daily-congressional-record/{volumeNumber}/{issueNumber}": "daily-congressional-record/{volumeNumber}/{issueNumber}",
        "/daily-congressional-record/{volumeNumber}/{issueNumber}/articles": "daily-congressional-record/{volumeNumber}/{issueNumber}/articles",
        "/bound-congressional-record": "bound-congressional-record",
        "/bound-congressional-record/{year}": "bound-congressional-record/{year}",
        "/bound-congressional-record/{year}/{month}": "bound-congressional-record/{year}/{month}",
        "/bound-congressional-record/{year}/{month}/{day}": "bound-congressional-record/{year}/{month}/{day}",
        "/house-communication": "house-communication",
        "/house-communication/{congress}": "house-communication/{congress}",
        "/house-communication/{congress}/{communicationType}": "house-communication/{congress}/{communicationType}",
        "/house-communication/{congress}/{communicationType}/{communicationNumber}": "house-communication/{congress}/{communicationType}/{communicationNumber}",
        "/house-requirement": "house-requirement",
        "/house-requirement/{requirementNumber}": "house-requirement/{requirementNumber}",
        "/house-requirement/{requirementNumber}/matching-communications": "house-requirement/{requirementNumber}/matching-communications",
        "/senate-communication": "senate-communication",
        "/senate-communication/{congress}": "senate-communication/{congress}",
        "/senate-communication/{congress}/{communicationType}": "senate-communication/{congress}/{communicationType}",
        "/senate-communication/{congress}/{communicationType}/{communicationNumber}": "senate-communication/{congress}/{communicationType}/{communicationNumber}",
        "/nomination": "nomination",
        "/nomination/{congress}": "nomination/{congress}",
        "/nomination/{congress}/{nominationNumber}": "nomination/{congress}/{nominationNumber}",
        "/nomination/{congress}/{nominationNumber}/{ordinal}": "nomination/{congress}/{nominationNumber}/{ordinal}",
        "/nomination/{congress}/{nominationNumber}/actions": "nomination/{congress}/{nominationNumber}/actions",
        "/nomination/{congress}/{nominationNumber}/committees": "nomination/{congress}/{nominationNumber}/committees",
        "/nomination/{congress}/{nominationNumber}/hearings": "nomination/{congress}/{nominationNumber}/hearings",
        "/crsreport": "crsreport",
        "/crsreport/{reportNumber}": "crsreport/{reportNumber}",
        "/treaty": "treaty",
        "/treaty/{congress}": "treaty/{congress}",
        "/treaty/{congress}/{treatyNumber}": "treaty/{congress}/{treatyNumber}",
        "/treaty/{congress}/{treatyNumber}/{treatySuffix}": "treaty/{congress}/{treatyNumber}/{treatySuffix}",
        "/treaty/{congress}/{treatyNumber}/actions": "treaty/{congress}/{treatyNumber}/actions",
        "/treaty/{congress}/{treatyNumber}/{treatySuffix}/actions": "treaty/{congress}/{treatyNumber}/{treatySuffix}/actions",
        "/treaty/{congress}/{treatyNumber}/committees": "treaty/{congress}/{treatyNumber}/committees",
    }

    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(http_client=http_client, timeout=timeout)
        self.api_key = api_key or os.getenv("CONGRESS_API_KEY") or os.getenv("CONGRESS_GOV_API_KEY")

    def authenticate(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ConnectorAuthenticationError(
                "Congress.gov requires an API key. Set CONGRESS_API_KEY or pass api_key."
            )
        return {**parameters, "api_key": self.api_key}

    def resolve_operation(self, operation: str, parameters: dict[str, Any]) -> str:
        if operation == "bill" and {
            "congress",
            "billType",
            "bill_type",
            "billNumber",
            "bill_number",
        }.intersection(parameters):
            return super().resolve_operation(
                "/bill/{congress}/{billType}/{billNumber}",
                parameters,
            )
        if operation == "amendment" and {
            "congress",
            "amendmentType",
            "amendment_type",
            "amendmentNumber",
            "amendment_number",
        }.intersection(parameters):
            return super().resolve_operation(
                "/amendment/{congress}/{amendmentType}/{amendmentNumber}",
                parameters,
            )
        if not operation.startswith("/") and f"/{operation}" in self.operations:
            return super().resolve_operation(f"/{operation}", parameters)
        if operation.startswith("/"):
            parameter_aliases = {
                "billType": "billType",
                "bill_type": "billType",
                "billNumber": "billNumber",
                "bill_number": "billNumber",
                "lawType": "lawType",
                "law_type": "lawType",
                "lawNumber": "lawNumber",
                "law_number": "lawNumber",
                "amendmentType": "amendmentType",
                "amendment_type": "amendmentType",
                "amendmentNumber": "amendmentNumber",
                "amendment_number": "amendmentNumber",
                "bioguideId": "bioguideId",
                "bioguide_id": "bioguideId",
                "stateCode": "stateCode",
                "state_code": "stateCode",
                "committeeCode": "committeeCode",
                "committee_code": "committeeCode",
                "reportType": "reportType",
                "report_type": "reportType",
                "reportNumber": "reportNumber",
                "report_number": "reportNumber",
                "jacketNumber": "jacketNumber",
                "jacket_number": "jacketNumber",
                "eventId": "eventId",
                "event_id": "eventId",
                "communicationType": "communicationType",
                "communication_type": "communicationType",
                "communicationNumber": "communicationNumber",
                "communication_number": "communicationNumber",
                "requirementNumber": "requirementNumber",
                "requirement_number": "requirementNumber",
                "nominationNumber": "nominationNumber",
                "nomination_number": "nominationNumber",
                "treatyNumber": "treatyNumber",
                "treaty_number": "treatyNumber",
                "treatySuffix": "treatySuffix",
                "treaty_suffix": "treatySuffix",
                "voteNumber": "voteNumber",
                "vote_number": "voteNumber",
                "issueNumber": "issueNumber",
                "issue_number": "issueNumber",
                "volumeNumber": "volumeNumber",
                "volume_number": "volumeNumber",
                "reportNumber": "reportNumber",
                "report_number": "reportNumber",
            }
            for source, target in parameter_aliases.items():
                if source in parameters and target not in parameters:
                    parameters[target] = parameters[source]
            return super().resolve_operation(operation, parameters)
        normalized = re.sub(r"[^a-z0-9]+", "_", operation.lower()).strip("_")
        aliases = {
            "bills": "/bill",
            "amendments": "/amendment",
            "members": "/member",
            "committees": "/committee",
            "congresses": "/congress",
            "get_bills": "/bill",
            "get_bill": "/bill/{congress}/{bill_type}/{bill_number}",
            "get_congress": "/congress",
            "get_members": "/member",
            "get_member": "/member/{bioguide_id}",
            "get_committees": "/committee",
            "get_committee": "/committee/{chamber}/{committee_code}",
        }
        normalized = aliases.get(normalized, normalized)
        normalized_parameters = {
            "bill_type": parameters.pop("billType", parameters.pop("bill_type", None)),
            "bill_number": parameters.pop("billNumber", parameters.pop("bill_number", None)),
            "committee_code": parameters.pop("committeeCode", parameters.pop("committee_code", None)),
            "amendment_type": parameters.pop("amendmentType", parameters.pop("amendment_type", None)),
            "amendment_number": parameters.pop("amendmentNumber", parameters.pop("amendment_number", None)),
            "bioguide_id": parameters.pop("bioguideId", parameters.pop("bioguide_id", None)),
            "congress": parameters.pop("congress", None),
            "chamber": parameters.pop("chamber", None),
        }
        parameters.update({key: value for key, value in normalized_parameters.items() if value is not None})
        try:
            path = super().resolve_operation(normalized, parameters)
        except ConnectorOperationError:
            raise
        for key in normalized_parameters:
            parameters.pop(key, None)
        return path

    def get_bills(self, **parameters: Any) -> dict[str, Any]:
        return self.execute("/bill", **parameters)

    def get_bill(self, congress: int, bill_type: str, bill_number: int, **parameters: Any) -> dict[str, Any]:
        return self.execute(
            "/bill/{congress}/{billType}/{billNumber}",
            congress=congress,
            bill_type=bill_type,
            bill_number=bill_number,
            **parameters,
        )


# Compatibility name for integrations that use the service name.
CongressConnector = CongressGovConnector
