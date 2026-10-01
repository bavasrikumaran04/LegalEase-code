"""Pydantic request/response models for the LegalEase API.

All incoming data is validated here: unknown fields are rejected, text is
stripped and length-limited, the effective date is parsed strictly and terms
must contain at least one usable clause.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services.document_service import parse_effective_date, parse_terms

MAX_DOCUMENT_TYPE_LENGTH = 100
MAX_PARTIES_LENGTH = 2_000
MAX_TERMS_LENGTH = 6_000
MAX_TERMS_COUNT = 60
MAX_CONTENT_LENGTH = 150_000
MAX_LOGO_BYTES = 2 * 1024 * 1024
_MAX_LOGO_BASE64_LENGTH = (MAX_LOGO_BYTES * 4) // 3 + 8

_DOCUMENT_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/'().,\-]*$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_document_type(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        raise ValueError("Document type is required.")
    if len(value) < 2:
        raise ValueError("Document type is too short.")
    if not _DOCUMENT_TYPE_RE.fullmatch(value) or not re.search(r"[A-Za-z]{2}", value):
        raise ValueError(
            "Document type may only contain letters, numbers, spaces and basic punctuation "
            "(for example: Service Agreement)."
        )
    return value


class DocumentRequest(_StrictModel):
    """Inputs for ``POST /generate`` (field names follow the project specification)."""

    document_type: str = Field(
        ..., max_length=MAX_DOCUMENT_TYPE_LENGTH, examples=["Freelance Work Contract"],
        description="Type of legal document, e.g. 'NDA' or 'Lease Agreement'.",
    )
    parties: str = Field(
        ..., max_length=MAX_PARTIES_LENGTH, examples=["Jane Doe (Service Provider), TechNova Inc. (Client)"],
        description="Names and roles of the parties involved.",
    )
    terms: str = Field(
        ..., max_length=MAX_TERMS_LENGTH,
        examples=["Payment to be made within 30 days of invoice; Either party may terminate with 15 days notice"],
        description="Terms and conditions, one per line or separated by semicolons.",
    )
    dates: str = Field(
        ..., max_length=40, examples=["2025-04-15"],
        description="Effective date as YYYY-MM-DD or a written date such as 'April 15, 2025'.",
    )

    @field_validator("document_type")
    @classmethod
    def _check_document_type(cls, value: str) -> str:
        return _validate_document_type(value)

    @field_validator("parties")
    @classmethod
    def _check_parties(cls, value: str) -> str:
        if not value:
            raise ValueError("Parties involved are required.")
        if len(re.findall(r"[A-Za-z]", value)) < 2:
            raise ValueError("Parties must include at least one name.")
        return value

    @field_validator("terms")
    @classmethod
    def _check_terms(cls, value: str) -> str:
        if not value:
            raise ValueError("At least one term or condition is required.")
        terms = parse_terms(value)
        if not terms:
            raise ValueError("At least one term or condition is required.")
        if len(terms) > MAX_TERMS_COUNT:
            raise ValueError(f"Please provide at most {MAX_TERMS_COUNT} terms.")
        return value

    @field_validator("dates")
    @classmethod
    def _check_dates(cls, value: str) -> str:
        return parse_effective_date(value).isoformat()

    @property
    def effective_date(self) -> date:
        return date.fromisoformat(self.dates)

    @property
    def term_list(self) -> list[str]:
        return parse_terms(self.terms)


class GenerateResponse(BaseModel):
    document: str = Field(..., description="Generated document as clean plain text.")
    title: str
    document_type: str
    effective_date: date
    effective_date_display: str
    terms: list[str]
    placeholders: list[str] = Field(default_factory=list, description="Unfilled [PLACEHOLDER] tokens.")
    word_count: int
    model: str
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class ContentRequest(_StrictModel):
    """A (possibly user-edited) document to preview or export."""

    content: str = Field(..., max_length=MAX_CONTENT_LENGTH, description="Document text (the edited version).")
    document_type: str = Field("Legal Document", max_length=MAX_DOCUMENT_TYPE_LENGTH)

    @field_validator("content")
    @classmethod
    def _check_content(cls, value: str) -> str:
        if not value or not re.search(r"\w", value):
            raise ValueError("The document is empty. Generate or enter content before exporting.")
        return value

    @field_validator("document_type")
    @classmethod
    def _check_document_type(cls, value: str) -> str:
        return _validate_document_type(value or "Legal Document")


class PreviewResponse(BaseModel):
    html: str
    title: str
    placeholders: list[str]
    word_count: int


class ExportFormat(str, Enum):
    txt = "txt"
    docx = "docx"
    pdf = "pdf"


class ExportRequest(ContentRequest):
    include_disclaimer: bool = Field(True, description="Add the AI-draft disclaimer to the footer.")
    logo_base64: str | None = Field(
        None, max_length=_MAX_LOGO_BASE64_LENGTH,
        description="Optional custom logo (PNG/JPEG, base64, max 2 MB) replacing the LegalEase logo.",
    )

    @field_validator("logo_base64")
    @classmethod
    def _check_logo(cls, value: str | None) -> str | None:
        if not value:
            return None
        if value.startswith("data:"):
            value = value.split(",", 1)[-1]
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("The logo must be a base64-encoded PNG or JPEG image.") from None
        if not raw or len(raw) > MAX_LOGO_BYTES:
            raise ValueError("The logo must be smaller than 2 MB.")
        return value

    @property
    def logo_bytes(self) -> bytes | None:
        return base64.b64decode(self.logo_base64) if self.logo_base64 else None


class DocumentTypeInfo(BaseModel):
    id: str
    label: str
    description: str


class AIStatus(BaseModel):
    provider: str = "Google Gemini"
    model: str
    configured: bool


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    ai: AIStatus


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
