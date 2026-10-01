"""Errors raised by the AI layer.

Each error carries an HTTP status, a stable machine-readable ``code`` and a
``user_message`` that is safe to show to end users (no keys, stack traces or
internal details). Technical detail goes to the server log only.
"""

from __future__ import annotations


class GeminiError(Exception):
    """Base class for AI generation failures."""

    status_code = 502
    code = "ai_error"
    user_message = "The AI service could not generate the document. Please try again."

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        super().__init__(detail or self.user_message)
        self.detail = detail
        if user_message:
            self.user_message = user_message


class GeminiConfigurationError(GeminiError):
    status_code = 503
    code = "ai_not_configured"
    user_message = (
        "The AI service is not configured. Add a GEMINI_API_KEY to the backend .env file "
        "and restart the backend."
    )


class GeminiAuthenticationError(GeminiError):
    status_code = 502
    code = "ai_auth_failed"
    user_message = (
        "The AI service rejected the configured API key. Please check the backend's "
        "GEMINI_API_KEY setting."
    )


class GeminiModelNotFoundError(GeminiError):
    status_code = 502
    code = "ai_model_unavailable"
    user_message = "The configured AI model is not available. Please check the GEMINI_MODEL setting."


class GeminiRateLimitError(GeminiError):
    status_code = 429
    code = "ai_rate_limited"
    user_message = "The AI service is receiving too many requests. Please wait a moment and try again."


class GeminiTimeoutError(GeminiError):
    status_code = 504
    code = "ai_timeout"
    user_message = "The AI service took too long to respond. Please try again."


class GeminiNetworkError(GeminiError):
    status_code = 503
    code = "ai_unreachable"
    user_message = "Could not reach the AI service. Please check the server's internet connection and try again."


class GeminiUnavailableError(GeminiError):
    status_code = 503
    code = "ai_unavailable"
    user_message = "The AI service is temporarily unavailable. Please try again shortly."


class GeminiRequestError(GeminiError):
    status_code = 502
    code = "ai_request_rejected"
    user_message = "The AI service could not process this request. Please adjust your inputs and try again."


class GeminiContentBlockedError(GeminiError):
    status_code = 422
    code = "ai_content_blocked"
    user_message = (
        "The AI service declined to generate this document because of its content policies. "
        "Please review your inputs and try again."
    )


class GeminiEmptyResponseError(GeminiError):
    status_code = 502
    code = "ai_empty_response"
    user_message = "The AI service returned an empty document. Please try again."
