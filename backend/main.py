"""FastAPI application entry point.

Run locally with:

    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.ai_core.exceptions import GeminiError
from backend.config import APP_NAME, APP_VERSION, get_settings
from backend.routes import router
from backend.services.branding import InvalidLogoError
from backend.services.export_service import DocumentExportError

logger = logging.getLogger("legalease")

FIELD_LABELS = {
    "document_type": "Document type",
    "parties": "Parties involved",
    "terms": "Terms & conditions",
    "dates": "Effective date",
    "content": "Document content",
    "include_disclaimer": "Include disclaimer",
    "logo_base64": "Logo",
    "export_format": "Export format",
}


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # The HTTP client logs full request URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def error_response(status_code: int, code: str, message: str, fields: dict[str, str] | None = None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return JSONResponse(status_code=status_code, content=body)


def _validation_message(error: dict) -> tuple[str, str]:
    location = [str(part) for part in error.get("loc", ()) if part not in ("body", "path", "query")]
    field = location[0] if location else "request"
    label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
    kind = error.get("type", "")
    context = error.get("ctx") or {}

    if kind == "missing":
        return field, f"{label} is required."
    if kind == "string_too_long":
        return field, f"{label} is too long (maximum {context.get('max_length')} characters)."
    if kind == "extra_forbidden":
        return field, f"Unexpected field '{field}'."
    if kind == "enum" and field == "export_format":
        return field, "Unsupported export format. Choose txt, docx or pdf."
    if kind in ("json_invalid", "model_attributes_type", "dict_type"):
        return "request", "The request body must be a valid JSON object."
    if kind in ("string_type", "bool_type", "bool_parsing"):
        return field, f"{label} has an invalid value."
    message = str(error.get("msg", "Invalid value.")).removeprefix("Value error, ")
    return field, message


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=f"{APP_NAME} - AI Legal Document Generator",
        version=APP_VERSION,
        description=(
            "Generate professional legal document drafts with Google Gemini and export them as "
            "TXT, DOCX or PDF. Drafts are for informational purposes only and are not legal advice."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            # Documents may contain sensitive information: never cache them.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for error in exc.errors():
            field, message = _validation_message(error)
            fields.setdefault(field, message)
        summary = next(iter(fields.values()), "Invalid request.")
        if len(fields) > 1:
            summary = "Please correct the highlighted fields: " + " ".join(fields.values())
        return error_response(422, "validation_error", summary, fields)

    @app.exception_handler(GeminiError)
    async def on_ai_error(request: Request, exc: GeminiError) -> JSONResponse:
        logger.warning("AI generation failed: %s (%s)", exc.code, exc.detail or type(exc).__name__)
        return error_response(exc.status_code, exc.code, exc.user_message)

    @app.exception_handler(InvalidLogoError)
    async def on_invalid_logo(request: Request, exc: InvalidLogoError) -> JSONResponse:
        return error_response(422, "invalid_logo", str(exc), {"logo_base64": str(exc)})

    @app.exception_handler(DocumentExportError)
    async def on_export_error(request: Request, exc: DocumentExportError) -> JSONResponse:
        return error_response(500, exc.code, exc.user_message)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {404: "Resource not found.", 405: "Method not allowed."}
        message = messages.get(exc.status_code, str(exc.detail) if exc.status_code < 500 else "Server error.")
        return error_response(exc.status_code, f"http_{exc.status_code}", message)

    @app.exception_handler(Exception)
    async def on_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "internal_error", "An unexpected error occurred. Please try again.")

    @app.get("/", tags=["system"])
    def home() -> dict[str, str]:
        """Root endpoint confirming the service is running."""
        return {
            "message": "Welcome to LegalEase AI Legal Document Generator API",
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
        }

    app.include_router(router)

    if not settings.ai_configured:
        logger.warning("GEMINI_API_KEY is not set - /generate will return 503 until it is configured.")
    logger.info("LegalEase API ready (model=%s, CORS origins=%s)", settings.gemini_model, ", ".join(settings.cors_origins))
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
