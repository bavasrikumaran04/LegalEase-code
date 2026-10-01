"""Single entry point for turning document text into downloadable files."""

from __future__ import annotations

import logging

from backend.services.branding import InvalidLogoError, resolve_logo
from backend.services.docx_generator import format_docx
from backend.services.pdf_generator import format_pdf
from backend.services.txt_generator import format_txt

logger = logging.getLogger(__name__)

MEDIA_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


class DocumentExportError(Exception):
    """A file could not be produced. ``user_message`` is safe to display."""

    def __init__(self, export_format: str) -> None:
        self.export_format = export_format
        self.code = f"{export_format}_export_failed"
        self.user_message = f"The {export_format.upper()} file could not be generated. Please try again."
        super().__init__(self.user_message)


def export_document(
    export_format: str,
    content: str,
    document_type: str,
    *,
    include_disclaimer: bool = True,
    custom_logo: bytes | None = None,
    page_size: str = "A4",
) -> bytes:
    """Render ``content`` (the edited document) in the requested format.

    Raises:
        InvalidLogoError: the custom logo is not a usable image (client error).
        DocumentExportError: the file could not be generated (server error).
        ValueError: unknown export format.
    """
    if export_format not in MEDIA_TYPES:
        raise ValueError(f"Unsupported export format: {export_format}")
    try:
        if export_format == "txt":
            return format_txt(content, document_type, include_disclaimer=include_disclaimer).encode("utf-8")
        logo = resolve_logo(custom_logo)
        if export_format == "docx":
            return format_docx(
                content, document_type, include_disclaimer=include_disclaimer, logo=logo, page_size=page_size
            )
        return format_pdf(
            content, document_type, include_disclaimer=include_disclaimer, logo=logo, page_size=page_size
        )
    except InvalidLogoError:
        raise
    except Exception as exc:
        logger.exception("%s export failed", export_format.upper())
        raise DocumentExportError(export_format) from exc
