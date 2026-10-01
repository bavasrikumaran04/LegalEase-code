"""Gemini integration for legal document generation.

Uses the official Google Gen AI SDK (``google-genai``) and its stateless
``models.generate_content`` endpoint: each request is self-contained and no
conversation state is stored server-side, which suits sensitive legal inputs.

The model, thinking level, token limit, timeout and retry policy all come from
:mod:`backend.config`, so switching models is a configuration change only.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors, types

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
from backend.ai_core.prompts import SYSTEM_INSTRUCTION, DocumentSpec, build_user_prompt
from backend.config import Settings, get_settings
from backend.services.document_service import normalize_document_text, parse_effective_date, parse_terms

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = [408, 429, 500, 502, 503, 504]
_BLOCKED_FINISH_REASONS = {
    "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE",
}
# Transient capacity errors on one model are retried on the configured fallback models.
_FALLBACK_ERRORS = (GeminiUnavailableError, GeminiRateLimitError, GeminiTimeoutError, GeminiModelNotFoundError)
_PREAMBLE_RE =re.compile(
    r"^(?:sure|certainly|of course|okay|ok|here(?:'s| is| are))\b[^\n]{0,160}[:.!]\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class GenerationResult:
    """Clean document text plus metadata about how it was produced."""

    text: str
    model: str
    truncated: bool = False
    finish_reason: str | None = None


def clean_model_output(text: str) -> str:
    """Remove chatty preambles and Markdown artefacts from model output."""
    lines = (text or "").strip().splitlines()
    while lines and (not lines[0].strip() or _PREAMBLE_RE.match(lines[0].strip())):
        lines.pop(0)
    return normalize_document_text("\n".join(lines))


class GeminiDocumentGenerator:
    """Generates legal documents with Google Gemini.

    The client is created lazily, so the API can start (and report its status)
    even when no API key is configured yet.
    """

    def __init__(self, settings: Settings | None = None, client: genai.Client | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    # -- configuration -----------------------------------------------------

    @property
    def model(self) -> str:
        return self._settings.gemini_model

    @property
    def is_configured(self) -> bool:
        return self._client is not None or self._settings.ai_configured

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self._settings.ai_configured:
                raise GeminiConfigurationError("GEMINI_API_KEY is not set")
            http_options = types.HttpOptions(
                timeout=self._settings.gemini_timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(
                    attempts=self._settings.gemini_max_retries + 1,
                    http_status_codes=_RETRYABLE_STATUS_CODES,
                    initial_delay=1.0,
                    max_delay=20.0,
                ),
            )
            self._client = genai.Client(api_key=self._settings.gemini_api_key, http_options=http_options)
        return self._client

    def _generation_config(self) -> types.GenerateContentConfig:
        # Gemini 3.x: sampling parameters (temperature/top_p/top_k), thinking_budget
        # and candidate_count are deprecated, so only thinking_level is set.
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            thinking_config=types.ThinkingConfig(thinking_level=self._settings.gemini_thinking_level),
            max_output_tokens=self._settings.gemini_max_output_tokens,
        )

    # -- public API --------------------------------------------------------

    def generate_document(
        self,
        document_type: str,
        parties: str,
        terms: str | Sequence[str],
        dates: str | date,
    ) -> GenerationResult:
        """Generate a legal document from the four user inputs.

        Args:
            document_type: e.g. "Freelance Work Contract".
            parties: Free text such as "Jane Doe (Service Provider), TechNova Inc. (Client)".
            terms: Terms as a newline/semicolon separated string or a sequence of terms.
            dates: Effective date as a ``date`` or string (ISO or written form).
        """
        term_list = parse_terms(terms) if isinstance(terms, str) else [t.strip() for t in terms if t.strip()]
        if not term_list:
            raise ValueError("At least one term or condition is required.")
        spec = DocumentSpec(
            document_type=document_type.strip(),
            parties=parties.strip(),
            terms=tuple(term_list),
            effective_date=parse_effective_date(dates),
        )
        return self.generate(spec)

    def generate(self, spec: DocumentSpec) -> GenerationResult:
        client = self._get_client()
        prompt = build_user_prompt(spec)
        started = time.perf_counter()
        models = [self.model, *(m for m in self._settings.gemini_fallback_models if m != self.model)]
        last_error: GeminiError | None = None
        last_cause: Exception | None = None
        for model in models:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=self._generation_config(),
                )
            except Exception as exc:  # noqa: BLE001 - translated into a typed, user-safe error
                last_error, last_cause = self._translate_error(exc), exc
                if isinstance(last_error, _FALLBACK_ERRORS):
                    logger.warning("Model %s unavailable (%s); trying next fallback model.", model, last_error.code)
                    continue
                raise last_error from exc

            result = self._parse_response(response, model)
            logger.info(
                "Gemini generation succeeded: model=%s type=%r terms=%d chars=%d finish=%s elapsed=%.1fs",
                model, spec.document_type, len(spec.terms), len(result.text),
                result.finish_reason, time.perf_counter() - started,
            )
            return result
        assert last_error is not None
        raise last_error from last_cause

    # -- helpers -----------------------------------------------------------

    def _parse_response(self, response: types.GenerateContentResponse, model: str | None = None) -> GenerationResult:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise GeminiContentBlockedError(f"Prompt blocked: {feedback.block_reason}")

        candidates = getattr(response, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        finish_reason = getattr(finish, "value", None) or (str(finish) if finish else None)
        if finish_reason in _BLOCKED_FINISH_REASONS:
            raise GeminiContentBlockedError(f"Generation stopped: {finish_reason}")

        text = clean_model_output(response.text or "")
        if not text:
            raise GeminiEmptyResponseError(f"Empty response (finish_reason={finish_reason})")

        truncated = finish_reason == "MAX_TOKENS"
        if truncated:
            logger.warning("Gemini output hit max_output_tokens=%s", self._settings.gemini_max_output_tokens)
        return GenerationResult(text=text, model=model or self.model, truncated=truncated, finish_reason=finish_reason)

    def _translate_error(self, exc: Exception) -> GeminiError:
        """Map SDK / transport exceptions onto user-safe LegalEase errors."""
        if isinstance(exc, GeminiError):
            return exc
        if isinstance(exc, errors.APIError):
            code = getattr(exc, "code", None) or 0
            status = (getattr(exc, "status", None) or "").upper()
            message = (getattr(exc, "message", None) or "")[:300]
            logger.warning("Gemini API error: code=%s status=%s message=%s", code, status, message)
            lowered = message.lower()
            if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED") or "api key" in lowered:
                return GeminiAuthenticationError(f"{code} {status}")
            if code == 404 or status == "NOT_FOUND":
                return GeminiModelNotFoundError(f"{code} {status}: model={self.model}")
            if code == 429 or status == "RESOURCE_EXHAUSTED":
                return GeminiRateLimitError(f"{code} {status}")
            if code in (408, 504) or status == "DEADLINE_EXCEEDED":
                return GeminiTimeoutError(f"{code} {status}")
            if isinstance(exc, errors.ServerError) or code >= 500:
                return GeminiUnavailableError(f"{code} {status}")
            return GeminiRequestError(f"{code} {status}")
        if isinstance(exc, httpx.TimeoutException):
            logger.warning("Gemini request timed out: %s", type(exc).__name__)
            return GeminiTimeoutError(type(exc).__name__)
        if isinstance(exc, httpx.TransportError):
            logger.warning("Gemini network error: %s", type(exc).__name__)
            return GeminiNetworkError(type(exc).__name__)
        logger.exception("Unexpected error while calling Gemini")
        return GeminiError(type(exc).__name__)


@lru_cache(maxsize=1)
def get_generator() -> GeminiDocumentGenerator:
    """Process-wide generator (FastAPI dependency; overridable in tests)."""
    return GeminiDocumentGenerator()
