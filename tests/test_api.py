"""HTTP API tests: endpoints, validation, error envelopes, exports and headers.

The generator dependency is replaced by a recording fake (see ``conftest.py``),
so no request ever reaches Gemini.
"""

from __future__ import annotations

import base64
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import errors

from backend.ai_core.exceptions import (
    GeminiAuthenticationError,
    GeminiConfigurationError,
    GeminiContentBlockedError,
    GeminiEmptyResponseError,
    GeminiError,
    GeminiModelNotFoundError,
    GeminiNetworkError,
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)
from backend.ai_core.gemini_generator import GeminiDocumentGenerator, get_generator
from backend.config import Settings
from backend.main import app as module_app
from backend.routes import TRUNCATION_WARNING
from backend.services.branding import DISCLAIMER_TEXT
from tests.conftest import FakeGenerator

SECRET_KEY = "AIzaSy-test-secret-key-do-not-leak"

CONTRACT_PLACEHOLDERS = ["[ADDRESS]", "[COMPANY ADDRESS]", "[DESCRIPTION OF SERVICES]", "[AMOUNT]", "[TITLE]"]

VALID_REQUEST = {
    "document_type": "Freelance Work Contract",
    "parties": "Jane Doe (Service Provider), TechNova Inc. (Client)",
    "terms": "Payment within 30 days of invoice; Either party may terminate with 15 days notice",
    "dates": "2025-04-15",
}


def payload(**overrides: object) -> dict:
    """A valid /generate body with some fields replaced."""
    return {**VALID_REQUEST, **overrides}


def flat(text: str) -> str:
    """Collapse whitespace so wrapped output can be searched for phrases."""
    return " ".join(text.split())


def assert_validation_error(response: httpx.Response, *fields: str) -> dict[str, str]:
    """Assert a 422 validation envelope that flags exactly ``fields``; return its messages."""
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"]
    assert set(error["fields"]) == set(fields)
    assert all(error["fields"].values())
    return error["fields"]


# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------


def test_root_confirms_service_is_running(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "LegalEase" in body["message"]


def test_module_level_app_serves_requests() -> None:
    response = TestClient(module_app).get("/health")

    assert response.status_code == 200
    assert response.json()["ai"]["configured"] is False


def test_health_reports_ai_not_configured_without_api_key(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ai"] == {"provider": "Google Gemini", "model": "gemini-3.8-flash", "configured": False}


def test_health_reports_ai_configured_when_generator_is_configured(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    body = client.get("/health").json()

    assert body["ai"]["configured"] is True
    assert body["ai"]["model"] == "gemini-test-model"


def test_health_never_exposes_the_api_key(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_generator] = lambda: GeminiDocumentGenerator(Settings(gemini_api_key=SECRET_KEY))

    response = client.get("/health")

    assert response.json()["ai"]["configured"] is True
    assert SECRET_KEY not in response.text


def test_document_types_lists_the_predefined_templates(client: TestClient) -> None:
    response = client.get("/document-types")

    assert response.status_code == 200
    types = response.json()
    assert len(types) == 8
    assert all(set(item) == {"id", "label", "description"} for item in types)
    assert {"nda", "lease_agreement", "offer_letter"} <= {item["id"] for item in types}
    assert "Non-Disclosure Agreement (NDA)" in {item["label"] for item in types}


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_404", "message": "Resource not found."}}


# ---------------------------------------------------------------------------
# POST /generate - success
# ---------------------------------------------------------------------------


def test_generate_returns_document_and_metadata(
    client: TestClient, fake_generator: FakeGenerator, contract_text: str
) -> None:
    response = client.post("/generate", json=payload())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"] == contract_text
    assert body["title"] == "FREELANCE WORK CONTRACT"
    assert body["document_type"] == "Freelance Work Contract"
    assert body["effective_date"] == "2025-04-15"
    assert body["effective_date_display"] == "April 15, 2025"
    assert body["terms"] == [
        "Payment within 30 days of invoice",
        "Either party may terminate with 15 days notice",
    ]
    assert body["placeholders"] == CONTRACT_PLACEHOLDERS
    assert body["word_count"] == len(contract_text.split())
    assert body["model"] == "gemini-test-model"
    assert body["truncated"] is False
    assert body["warnings"] == []


def test_generate_passes_validated_inputs_to_the_generator(client: TestClient, fake_generator: FakeGenerator) -> None:
    client.post(
        "/generate",
        json={
            "document_type": "  Freelance   Work Contract ",
            "parties": "  Jane Doe (Service Provider), TechNova Inc. (Client)  ",
            "terms": "- Payment within 30 days\n• Deliver by May 15, 2025\n",
            "dates": " 2025-04-15 ",
        },
    )

    assert len(fake_generator.calls) == 1
    call = fake_generator.calls[0]
    assert call.document_type == "Freelance Work Contract"
    assert call.parties == "Jane Doe (Service Provider), TechNova Inc. (Client)"
    assert call.terms == ["Payment within 30 days", "Deliver by May 15, 2025"]
    assert call.dates == date(2025, 4, 15)


def test_generate_splits_terms_on_semicolons_and_newlines(client: TestClient, fake_generator: FakeGenerator) -> None:
    terms = "Payment within 30 days; Termination with 15 days notice\nConfidentiality survives termination"

    body = client.post("/generate", json=payload(terms=terms)).json()

    expected = [
        "Payment within 30 days",
        "Termination with 15 days notice",
        "Confidentiality survives termination",
    ]
    assert body["terms"] == expected
    assert fake_generator.calls[0].terms == expected


@pytest.mark.parametrize("written_date", ["April 15, 2025", "15 April 2025", "April 15th, 2025"])
def test_generate_accepts_written_dates(client: TestClient, fake_generator: FakeGenerator, written_date: str) -> None:
    response = client.post("/generate", json=payload(dates=written_date))

    assert response.status_code == 200, response.text
    assert response.json()["effective_date"] == "2025-04-15"
    assert response.json()["effective_date_display"] == "April 15, 2025"
    assert fake_generator.calls[0].dates == date(2025, 4, 15)


def test_generate_warns_when_output_was_truncated(client: TestClient, fake_generator: FakeGenerator) -> None:
    fake_generator.truncated = True

    body = client.post("/generate", json=payload()).json()

    assert body["truncated"] is True
    assert body["warnings"] == [TRUNCATION_WARNING]


# ---------------------------------------------------------------------------
# POST /generate - input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("document_type", "Document type"),
        ("parties", "Parties involved"),
        ("terms", "Terms & conditions"),
        ("dates", "Effective date"),
    ],
)
def test_generate_reports_each_missing_field(
    client: TestClient, fake_generator: FakeGenerator, field: str, label: str
) -> None:
    body = payload()
    del body[field]

    messages = assert_validation_error(client.post("/generate", json=body), field)

    assert messages[field].startswith(label)
    assert "required" in messages[field]
    assert fake_generator.calls == []


def test_generate_reports_all_missing_fields_at_once(client: TestClient, fake_generator: FakeGenerator) -> None:
    response = client.post("/generate", json={})

    messages = assert_validation_error(response, "document_type", "parties", "terms", "dates")
    summary = response.json()["error"]["message"]
    assert all(message in summary for message in messages.values())


@pytest.mark.parametrize("blank", ["", "   ", "\n\t  "])
def test_generate_rejects_blank_inputs(client: TestClient, fake_generator: FakeGenerator, blank: str) -> None:
    body = {field: blank for field in VALID_REQUEST}

    messages = assert_validation_error(client.post("/generate", json=body), *VALID_REQUEST)

    assert messages == {
        "document_type": "Document type is required.",
        "parties": "Parties involved are required.",
        "terms": "At least one term or condition is required.",
        "dates": "Effective date is required.",
    }
    assert fake_generator.calls == []


@pytest.mark.parametrize("document_type", ["<script>", "!!!", "A", "1234", "NDA<script>alert(1)</script>"])
def test_generate_rejects_invalid_document_types(
    client: TestClient, fake_generator: FakeGenerator, document_type: str
) -> None:
    response = client.post("/generate", json=payload(document_type=document_type))

    assert_validation_error(response, "document_type")
    assert "<script>" not in response.text
    assert fake_generator.calls == []


def test_generate_rejects_parties_without_any_name(client: TestClient, fake_generator: FakeGenerator) -> None:
    messages = assert_validation_error(client.post("/generate", json=payload(parties="123 - 456")), "parties")

    assert messages["parties"] == "Parties must include at least one name."


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        ("10/04/2025", "not a valid date"),
        ("04-10-2025", "not a valid date"),
        ("2025-02-30", "not a valid date"),
        ("not a date", "not a valid date"),
        ("1850-01-01", "between the years 1900 and 2200"),
    ],
)
def test_generate_rejects_invalid_or_ambiguous_dates(
    client: TestClient, fake_generator: FakeGenerator, dates: str, expected: str
) -> None:
    messages = assert_validation_error(client.post("/generate", json=payload(dates=dates)), "dates")

    assert expected in messages["dates"]
    assert fake_generator.calls == []


@pytest.mark.parametrize("terms", [";;;", "\n;\n", "- \n• \n;", "..."])
def test_generate_rejects_terms_without_content(client: TestClient, fake_generator: FakeGenerator, terms: str) -> None:
    messages = assert_validation_error(client.post("/generate", json=payload(terms=terms)), "terms")

    assert messages["terms"] == "At least one term or condition is required."


def test_generate_rejects_too_many_terms(client: TestClient, fake_generator: FakeGenerator) -> None:
    terms = "\n".join(f"Term number {index}" for index in range(61))

    messages = assert_validation_error(client.post("/generate", json=payload(terms=terms)), "terms")

    assert messages["terms"] == "Please provide at most 60 terms."


def test_generate_rejects_unknown_fields(client: TestClient, fake_generator: FakeGenerator) -> None:
    response = client.post("/generate", json=payload(governing_law="Delaware"))

    messages = assert_validation_error(response, "governing_law")
    assert messages["governing_law"] == "Unexpected field 'governing_law'."
    assert fake_generator.calls == []


@pytest.mark.parametrize("field", ["parties", "terms"])
def test_generate_rejects_non_string_values(client: TestClient, fake_generator: FakeGenerator, field: str) -> None:
    messages = assert_validation_error(client.post("/generate", json=payload(**{field: 123})), field)

    assert messages[field].endswith("has an invalid value.")


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b'{"document_type": "NDA", ', "application/json"),
        (b"[]", "application/json"),
        (b'"just a string"', "application/json"),
        (b"document_type=NDA", "text/plain"),
    ],
)
def test_generate_rejects_malformed_bodies(
    client: TestClient, fake_generator: FakeGenerator, body: bytes, content_type: str
) -> None:
    response = client.post("/generate", content=body, headers={"Content-Type": content_type})

    messages = assert_validation_error(response, "request")
    assert messages["request"] == "The request body must be a valid JSON object."
    assert fake_generator.calls == []


@pytest.mark.parametrize(
    ("field", "limit"),
    [("document_type", 100), ("parties", 2_000), ("terms", 6_000), ("dates", 40)],
)
def test_generate_rejects_overlong_fields(
    client: TestClient, fake_generator: FakeGenerator, field: str, limit: int
) -> None:
    response = client.post("/generate", json=payload(**{field: "a" * (limit + 1)}))

    messages = assert_validation_error(response, field)
    assert messages[field].endswith(f"is too long (maximum {limit} characters).")
    assert fake_generator.calls == []


# ---------------------------------------------------------------------------
# POST /generate - AI failures
# ---------------------------------------------------------------------------

AI_ERRORS = [
    (GeminiConfigurationError, 503, "ai_not_configured"),
    (GeminiAuthenticationError, 502, "ai_auth_failed"),
    (GeminiRateLimitError, 429, "ai_rate_limited"),
    (GeminiTimeoutError, 504, "ai_timeout"),
    (GeminiNetworkError, 503, "ai_unreachable"),
    (GeminiUnavailableError, 503, "ai_unavailable"),
    (GeminiContentBlockedError, 422, "ai_content_blocked"),
    (GeminiEmptyResponseError, 502, "ai_empty_response"),
    (GeminiModelNotFoundError, 502, "ai_model_unavailable"),
    (GeminiRequestError, 502, "ai_request_rejected"),
    (GeminiError, 502, "ai_error"),
]


@pytest.mark.parametrize(("error_class", "status", "code"), AI_ERRORS, ids=[e[0].__name__ for e in AI_ERRORS])
def test_generate_maps_ai_errors_to_safe_responses(
    client: TestClient, fake_generator: FakeGenerator, error_class: type[GeminiError], status: int, code: str
) -> None:
    detail = f"upstream detail key={SECRET_KEY} Traceback (most recent call last)"
    fake_generator.error = error_class(detail)

    response = client.post("/generate", json=payload())

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": error_class.user_message}}
    for leaked in (SECRET_KEY, "Traceback", "upstream detail"):
        assert leaked not in response.text


def test_generate_without_api_key_returns_not_configured(client: TestClient) -> None:
    response = client.post("/generate", json=payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


def test_generate_translates_sdk_errors_end_to_end(app: FastAPI, client: TestClient) -> None:
    def reject(**kwargs: object) -> None:
        error = {"code": 401, "message": f"Bad key {SECRET_KEY}", "status": "UNAUTHENTICATED"}
        raise errors.ClientError(401, {"error": error})

    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=reject))
    generator = GeminiDocumentGenerator(Settings(gemini_api_key=SECRET_KEY), client=fake_client)
    app.dependency_overrides[get_generator] = lambda: generator

    response = client.post("/generate", json=payload())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ai_auth_failed"
    assert SECRET_KEY not in response.text
    assert "UNAUTHENTICATED" not in response.text


def test_generate_hides_unexpected_errors_behind_generic_500(app: FastAPI, fake_generator: FakeGenerator) -> None:
    fake_generator.error = RuntimeError(f"database password hunter2, key {SECRET_KEY}")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/generate", json=payload())

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred. Please try again."}
    }
    for leaked in (SECRET_KEY, "hunter2", "RuntimeError", "Traceback"):
        assert leaked not in response.text


@pytest.mark.xfail(
    reason="BUG: the catch-all 500 handler runs in Starlette's ServerErrorMiddleware, outside the "
    "security-headers middleware, so internal errors are returned without nosniff/no-store headers",
    strict=True,
)
def test_unexpected_error_response_still_has_security_headers(app: FastAPI, fake_generator: FakeGenerator) -> None:
    fake_generator.error = RuntimeError("boom")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/generate", json=payload())

    assert response.status_code == 500
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Cache-Control") == "no-store"


# ---------------------------------------------------------------------------
# POST /preview
# ---------------------------------------------------------------------------


def test_preview_renders_document_as_html(client: TestClient, contract_text: str) -> None:
    response = client.post("/preview", json={"content": contract_text, "document_type": "Freelance Work Contract"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "FREELANCE WORK CONTRACT"
    assert body["html"].startswith('<article class="le-doc">')
    assert '<h2 class="le-heading">1. DEFINITIONS</h2>' in body["html"]
    assert body["placeholders"] == CONTRACT_PLACEHOLDERS
    assert body["word_count"] == len(contract_text.split())


def test_preview_escapes_markup_in_content(client: TestClient) -> None:
    content = 'SERVICE AGREEMENT\n\nThe Client <script>alert("x")</script> agrees <img src=x onerror=alert(1)>.'

    html = client.post("/preview", json={"content": content}).json()["html"]

    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html


def test_preview_reflects_edited_content(client: TestClient, contract_text: str) -> None:
    edited = contract_text.replace("[AMOUNT]", "USD 5,000").replace("seven (7) days", "ten (10) days")

    body = client.post("/preview", json={"content": edited}).json()

    assert "USD 5,000" in body["html"]
    assert "ten (10) days" in body["html"]
    assert "seven (7) days" not in body["html"]
    assert "[AMOUNT]" not in body["placeholders"]


def test_preview_uses_document_type_when_content_has_no_title(client: TestClient) -> None:
    body = client.post(
        "/preview", json={"content": "The parties agree as follows.", "document_type": "Service Agreement"}
    ).json()

    assert body["title"] == "Service Agreement"


@pytest.mark.parametrize("content", ["", "   \n  ", "!!! ---"])
def test_preview_rejects_empty_content(client: TestClient, content: str) -> None:
    messages = assert_validation_error(client.post("/preview", json={"content": content}), "content")

    assert messages["content"].startswith("The document is empty.")


def test_preview_rejects_missing_content(client: TestClient) -> None:
    messages = assert_validation_error(client.post("/preview", json={"document_type": "NDA"}), "content")

    assert messages["content"] == "Document content is required."


# ---------------------------------------------------------------------------
# POST /export/txt
# ---------------------------------------------------------------------------


def test_export_txt_returns_utf8_attachment(client: TestClient, contract_text: str) -> None:
    response = client.post(
        "/export/txt", json={"content": contract_text, "document_type": "Freelance Work Contract"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="freelance_work_contract.txt"'
    text = response.content.decode("utf-8")
    assert "FREELANCE WORK CONTRACT" in text
    assert "• The Client shall pay each valid invoice" in text


def test_export_txt_filename_defaults_to_legal_document(client: TestClient) -> None:
    response = client.post("/export/txt", json={"content": "The parties agree."})

    assert response.headers["content-disposition"] == 'attachment; filename="legal_document.txt"'


def test_export_txt_contains_the_edited_content(client: TestClient, contract_text: str) -> None:
    edited = contract_text.replace("[AMOUNT]", "€4,500 (four thousand five hundred euros)")

    text = client.post("/export/txt", json={"content": edited}).content.decode("utf-8")

    assert "€4,500 (four thousand five hundred euros)" in flat(text)
    assert "[AMOUNT]" not in text


def test_export_txt_includes_disclaimer_by_default(client: TestClient, contract_text: str) -> None:
    text = client.post("/export/txt", json={"content": contract_text}).content.decode("utf-8")

    assert DISCLAIMER_TEXT in flat(text)


def test_export_txt_omits_disclaimer_when_disabled(client: TestClient, contract_text: str) -> None:
    text = client.post(
        "/export/txt", json={"content": contract_text, "include_disclaimer": False}
    ).content.decode("utf-8")

    assert "not provide legal advice" not in flat(text)


@pytest.mark.parametrize("export_format", ["html", "rtf", "TXT", "exe"])
def test_export_rejects_unsupported_formats(client: TestClient, export_format: str) -> None:
    response = client.post(f"/export/{export_format}", json={"content": "The parties agree."})

    messages = assert_validation_error(response, "export_format")
    assert messages["export_format"] == "Unsupported export format. Choose txt, docx or pdf."


def test_export_rejects_logo_that_is_not_base64(client: TestClient) -> None:
    response = client.post("/export/txt", json={"content": "The parties agree.", "logo_base64": "not base64!!"})

    messages = assert_validation_error(response, "logo_base64")
    assert messages["logo_base64"] == "The logo must be a base64-encoded PNG or JPEG image."


def test_export_rejects_logo_that_is_not_an_image(client: TestClient) -> None:
    logo = base64.b64encode(b"%PDF-1.7 definitely not a picture").decode()

    response = client.post("/export/pdf", json={"content": "The parties agree.", "logo_base64": logo})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_logo"
    assert "logo_base64" in error["fields"]


def test_export_rejects_non_boolean_disclaimer_flag(client: TestClient) -> None:
    response = client.post("/export/txt", json={"content": "The parties agree.", "include_disclaimer": "maybe"})

    assert_validation_error(response, "include_disclaimer")


def test_export_rejects_empty_content(client: TestClient) -> None:
    assert_validation_error(client.post("/export/txt", json={"content": "  "}), "content")


# ---------------------------------------------------------------------------
# Security headers and CORS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/health", None),
        ("GET", "/document-types", None),
        ("POST", "/generate", VALID_REQUEST),
        ("POST", "/generate", {}),
        ("POST", "/preview", {"content": "The parties agree."}),
        ("POST", "/export/txt", {"content": "The parties agree."}),
    ],
)
def test_api_responses_carry_security_headers(
    client: TestClient, fake_generator: FakeGenerator, method: str, path: str, body: dict | None
) -> None:
    response = client.request(method, path, json=body)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_cors_preflight_allows_the_streamlit_origin(client: TestClient) -> None:
    response = client.options(
        "/generate",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8501"


def test_cors_preflight_rejects_other_origins(client: TestClient) -> None:
    response = client.options(
        "/generate",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_exposes_content_disposition_to_allowed_origin(client: TestClient) -> None:
    response = client.post(
        "/export/txt", json={"content": "The parties agree."}, headers={"Origin": "http://localhost:8501"}
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:8501"
    assert "content-disposition" in response.headers["access-control-expose-headers"].lower()
