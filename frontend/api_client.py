"""HTTP client for the LegalEase FastAPI backend.

The frontend never talks to Gemini directly and never sees the API key: every
operation goes through the backend. All failures surface as :class:`APIError`
with a message that is safe to show to users.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import requests

HEALTH_TIMEOUT_SECONDS = 5
QUICK_TIMEOUT_SECONDS = 30


class APIError(Exception):
    """A backend call failed; ``message`` is user-friendly."""

    def __init__(self, message: str, *, code: str = "error", status: int | None = None,
                 fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.fields = fields or {}


@dataclass
class ExportedFile:
    data: bytes
    filename: str
    mime: str


@dataclass
class LegalEaseAPI:
    base_url: str
    timeout: int = 300
    session: requests.Session = field(default_factory=requests.Session, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    # -- endpoints ---------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=HEALTH_TIMEOUT_SECONDS).json()

    def document_types(self) -> list[dict[str, str]]:
        return self._request("GET", "/document-types", timeout=QUICK_TIMEOUT_SECONDS).json()

    def generate(self, document_type: str, parties: str, terms: str, dates: str) -> dict[str, Any]:
        payload = {"document_type": document_type, "parties": parties, "terms": terms, "dates": dates}
        return self._request("POST", "/generate", json=payload, timeout=self.timeout).json()

    def preview(self, content: str, document_type: str) -> dict[str, Any]:
        payload = {"content": content, "document_type": document_type}
        return self._request("POST", "/preview", json=payload, timeout=QUICK_TIMEOUT_SECONDS).json()

    def export(self, export_format: str, content: str, document_type: str, *,
               include_disclaimer: bool = True, logo_base64: str | None = None) -> ExportedFile:
        payload = {
            "content": content,
            "document_type": document_type,
            "include_disclaimer": include_disclaimer,
            "logo_base64": logo_base64,
        }
        response = self._request("POST", f"/export/{export_format}", json=payload, timeout=QUICK_TIMEOUT_SECONDS * 2)
        disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition)
        filename = match.group(1) if match else f"legal_document.{export_format}"
        mime = response.headers.get("Content-Type", "application/octet-stream").split(";")[0]
        return ExportedFile(data=response.content, filename=filename, mime=mime)

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, *, timeout: int, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=timeout, **kwargs)
        except requests.Timeout:
            raise APIError(
                "The LegalEase backend took too long to respond. Please try again.", code="backend_timeout"
            ) from None
        except requests.ConnectionError:
            raise APIError(
                f"Cannot reach the LegalEase backend at {self.base_url}. Make sure it is running "
                "(uvicorn backend.main:app --port 8000).",
                code="backend_unreachable",
            ) from None
        except requests.RequestException:
            raise APIError("Could not contact the LegalEase backend.", code="backend_error") from None

        if response.ok:
            return response
        raise self._error_from(response)

    @staticmethod
    def _error_from(response: requests.Response) -> APIError:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        if not isinstance(error, dict):
            error = {}
        message = error.get("message") or f"The backend returned an unexpected error (HTTP {response.status_code})."
        return APIError(
            str(message),
            code=str(error.get("code", "error")),
            status=response.status_code,
            fields=error.get("fields") if isinstance(error.get("fields"), dict) else None,
        )
