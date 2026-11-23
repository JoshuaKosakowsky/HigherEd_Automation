"""Safe request diagnostics for the Insights API and SSO session exchange."""

from html import unescape
from http import HTTPStatus
import logging
import re

import requests

from shared.workflow_logging import current_report_name

_LOG = logging.getLogger("highered_automation.insights")
DATASET_PATH = "/api/dataset"


def _query_log_fields(request: requests.PreparedRequest | None) -> str:
    body = request.body if request is not None else None
    size = len(body) if isinstance(body, bytes) else "unavailable"
    return f"report={current_report_name.get()!r}, request_bytes={size}"


def log_query_success(response: requests.Response) -> None:
    _LOG.info(
        "Insights query succeeded: POST %s, http=%s, %s",
        DATASET_PATH, response.status_code, _query_log_fields(response.request),
    )

# Only fixed phrases may leave an API error body. Unknown text can
# contain the submitted SQL, bound identifiers, or authentication details.
_ERROR_REASONS = (
    "You do not have permissions to run this query",
    "You don't have permissions to do that",
    "You do not have permissions to do that",
    "missing-required-permissions",
    "Insufficient permissions",
    "Request body too large",
    "Payload too large",
    "Request blocked",
    "Access denied",
    "The request could not be satisfied",
    "invalid-query",
    "invalid-parameter",
    "missing-required-parameter",
    "query-processor",
    "driver",
    "db",
    "Query timed out",
    "Query canceled",
    "Query cancelled",
)


def _response_reason(response: requests.Response, media_type: str, result: object) -> str:
    if not response.content:
        return "empty body"
    if result is None and len(response.content) > 16_384:
        return "body exceeds diagnostic limit"

    if result is not None or media_type == "application/json":
        body = result
        if body is None:
            try:
                body = response.json()
            except (ValueError, RecursionError):
                return "unreadable JSON"
        candidates = (
            [body.get(key) for key in ("message", "error", "error_type", "detail", "title")]
            if isinstance(body, dict) else [body]
        )
    elif media_type == "text/html":
        # Gateway error pages commonly put the status in a title or heading.
        candidates = [
            unescape(match[2]) for match in re.finditer(
                r"<(title|h[1-6]|p|body|center)\b[^<>]*>([^<>]*)</\1\s*>",
                response.text, flags=re.IGNORECASE,
            )
        ]
    elif media_type == "text/plain":
        candidates = [response.text]
    else:
        return "unsupported response format"

    # Keep recognized leading sentences even when the server appends private context.
    phrases = {
        " ".join(value.split()).partition(". ")[0].rstrip(".").casefold()
        for value in candidates if isinstance(value, str) and len(value) <= 1024
    }
    for reason in _ERROR_REASONS:
        if reason.casefold() in phrases:
            return reason
    try:
        status = HTTPStatus(response.status_code)
    except ValueError:
        return "unrecognized response text withheld"
    for phrase in (f"{status.value} {status.phrase}", status.phrase):
        if phrase.casefold() in phrases:
            return phrase
    return "unrecognized response text withheld"


def log_request_failure(
    method: str, path: str, failure: str, *, response: requests.Response | None = None,
    result: object = None, request: requests.PreparedRequest | None = None,
    timeout: int | None = None,
) -> None:
    """Record a single failed attempt using the client's fixed route and error category."""
    details = [f"failure={failure}"]
    if response is None:
        details.append("http=no response")
    else:
        if response.request is not None:
            request = response.request
        media_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
        if media_type.endswith("+json"):
            media_type = "application/json"
        elif media_type not in {"text/html", "text/plain", "application/json"}:
            media_type = "unknown"
        details.extend((f"http={response.status_code}", f"format={media_type}"))
        # A transfer error can carry headers for a partially received response.
        # Reading that stream again could hide the original failure.
        if failure not in {"timeout", "connection"}:
            details.append(f"response_bytes={len(response.content or b'')}")

        # The SSO exchange carries a JWT and returns session credentials.
        # Only query/metadata failure bodies are eligible for a reason summary.
        if path in {"/api/dataset", "/api/user/current", "/api/database", "/api/session/properties"}:
            if failure == "invalid_json" and media_type == "application/json":
                details.append("reason=unreadable JSON")
            elif failure in {"http", "query_failed", "invalid_json"}:
                details.append(f"reason={_response_reason(response, media_type, result)}")
            if path == "/api/dataset" and isinstance(result, dict):
                status = result.get("status")
                if status in ("completed", "failed", "canceled", "cancelled", "running"):
                    details.append(f"query_status={status}")

        if response.headers.get("Server", "").lower() == "awselb/2.0":
            details.append("server=awselb/2.0")
        for header in ("X-Amzn-RequestId", "X-Request-Id"):
            request_id = response.headers.get(header, "")
            if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", request_id):
                details.append(f"request_id={request_id}")
                break
    if path == DATASET_PATH:
        details.append(_query_log_fields(request))
    elif request is not None and isinstance(request.body, bytes):
        details.append(f"request_bytes={len(request.body)}")
    if timeout is not None:
        details.append(f"timeout_seconds={timeout}")
    _LOG.warning("Insights request failed: %s %s, %s", method, path, ", ".join(details))
