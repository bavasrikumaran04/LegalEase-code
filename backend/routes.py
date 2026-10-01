"""API routes for LegalEase."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Response

from backend.ai_core.document_types import DOCUMENT_TYPES
from backend.ai_core.gemini_generator import GeminiDocumentGenerator, get_generator
from backend.config import APP_NAME, APP_VERSION, get_settings
from backend.models import (
    AIStatus,
    ContentRequest,
    DocumentRequest,
    DocumentTypeInfo,
    ErrorResponse,
    ExportFormat,
    ExportRequest,
    GenerateResponse,
    HealthResponse,
    PreviewResponse,
)
from backend.services.document_service import (
    build_filename,
    find_placeholders,
    format_date_long,
    parse_document,
    word_count,
)
from backend.services.export_service import MEDIA_TYPES, export_document
from backend.services.html_preview import format_html_preview

logger = logging.getLogger(__name__)

router = APIRouter()

_ERROR_RESPONSES = {
    422: {"model": ErrorResponse, "description": "Invalid input"},
    429: {"model": ErrorResponse, "description": "AI service rate limit"},
    502: {"model": ErrorResponse, "description": "AI service error"},
    503: {"model": ErrorResponse, "description": "AI service not configured or unavailable"},
    504: {"model": ErrorResponse, "description": "AI service timeout"},
}

TRUNCATION_WARNING = (
    "The AI response reached its length limit, so the end of the document may be incomplete. "
    "Review it carefully or generate it again."
)


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(generator: GeminiDocumentGenerator = Depends(get_generator)) -> HealthResponse:
    """Report service status and whether the AI provider is configured."""
    return HealthResponse(
        status="ok",
        service=f"{APP_NAME} API",
        version=APP_VERSION,
        ai=AIStatus(model=generator.model, configured=generator.is_configured),
    )


@router.get("/document-types", response_model=list[DocumentTypeInfo], tags=["documents"])
def list_document_types() -> list[DocumentTypeInfo]:
    """Predefined document templates (custom types are also accepted by /generate)."""
    return [DocumentTypeInfo(id=dt.id, label=dt.label, description=dt.description) for dt in DOCUMENT_TYPES]


@router.post("/generate", response_model=GenerateResponse, responses=_ERROR_RESPONSES, tags=["documents"])
def generate_legal_document(
    request: DocumentRequest,
    generator: GeminiDocumentGenerator = Depends(get_generator),
) -> GenerateResponse:
    """Generate a legal document draft with Gemini from structured inputs."""
    started = time.perf_counter()
    terms = request.term_list
    result = generator.generate_document(
        request.document_type,
        request.parties,
        terms,
        request.effective_date,
    )
    parsed = parse_document(result.text, request.document_type)
    logger.info(
        "Generated document: type=%r terms=%d words=%d elapsed=%.1fs",
        request.document_type, len(terms), word_count(result.text), time.perf_counter() - started,
    )
    return GenerateResponse(
        document=result.text,
        title=parsed.title,
        document_type=request.document_type,
        effective_date=request.effective_date,
        effective_date_display=format_date_long(request.effective_date),
        terms=terms,
        placeholders=find_placeholders(result.text),
        word_count=word_count(result.text),
        model=result.model,
        truncated=result.truncated,
        warnings=[TRUNCATION_WARNING] if result.truncated else [],
    )


@router.post("/preview", response_model=PreviewResponse, responses={422: _ERROR_RESPONSES[422]}, tags=["documents"])
def preview_document(request: ContentRequest) -> PreviewResponse:
    """Render (edited) document text as safe, styled HTML for the preview pane."""
    parsed = parse_document(request.content, request.document_type)
    return PreviewResponse(
        html=format_html_preview(request.content, request.document_type),
        title=parsed.title,
        placeholders=find_placeholders(request.content),
        word_count=word_count(request.content),
    )


@router.post(
    "/export/{export_format}",
    responses={
        200: {"content": {media: {} for media in MEDIA_TYPES.values()}, "description": "The document file"},
        422: _ERROR_RESPONSES[422],
        500: {"model": ErrorResponse, "description": "File generation failed"},
    },
    response_class=Response,
    tags=["documents"],
)
def export_file(export_format: ExportFormat, request: ExportRequest) -> Response:
    """Export the final (edited) document as TXT, DOCX or PDF."""
    started = time.perf_counter()
    payload = export_document(
        export_format.value,
        request.content,
        request.document_type,
        include_disclaimer=request.include_disclaimer,
        custom_logo=request.logo_bytes,
        page_size=get_settings().page_size,
    )
    filename = build_filename(request.document_type, export_format.value)
    logger.info(
        "Exported %s: bytes=%d custom_logo=%s elapsed=%.2fs",
        export_format.value, len(payload), request.logo_base64 is not None, time.perf_counter() - started,
    )
    return Response(
        content=payload,
        media_type=MEDIA_TYPES[export_format.value],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
