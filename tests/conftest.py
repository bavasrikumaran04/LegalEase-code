"""Shared fixtures for the LegalEase backend test suite.

Every test runs as if no Gemini API key were configured and can never reach
the network: LegalEase/Gemini environment variables are removed, cached
settings and generators are reset, and constructing a real ``genai.Client`` is
an immediate test failure. API tests swap the generator dependency for
:class:`FakeGenerator`, which records the validated inputs it receives.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google import genai

from backend.ai_core.gemini_generator import GenerationResult, get_generator
from backend.config import get_settings
from backend.main import create_app

_ISOLATED_ENV_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_THINKING_LEVEL",
    "GEMINI_MAX_OUTPUT_TOKENS",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_MAX_RETRIES",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "CORS_ORIGINS",
    "LOG_LEVEL",
    "DOCUMENT_PAGE_SIZE",
)

CONTRACT_TEXT = """\
FREELANCE WORK CONTRACT

This Freelance Work Contract (the "Agreement") is made and entered into as of the 15th day of April, 2025 (the "Effective Date").

Between:

Jane Doe, an individual residing at [ADDRESS] (the "Service Provider"); and

TechNova Inc., a company with its principal place of business at [COMPANY ADDRESS] (the "Client").

RECITALS

WHEREAS, the Client wishes to engage the Service Provider to perform certain services; and

NOW, THEREFORE, in consideration of the mutual covenants contained herein, the Parties agree as follows:

1. DEFINITIONS

1.1 "Deliverables" means all work product, materials and documentation that the Service Provider creates for the Client under this Agreement.

2. SCOPE OF SERVICES

2.1 The Service Provider shall perform the services described in [DESCRIPTION OF SERVICES] with reasonable skill and care, subject to the following:
(a) the Services shall conform to any written specifications agreed by the Parties; and
(b) the Service Provider shall keep the Client reasonably informed of progress.

3. TERMS AND CONDITIONS

• The Service Provider shall deliver all Deliverables on or before May 15, 2025.
• The Client shall pay each valid invoice within seven (7) days of receipt.
• Either Party may terminate this Agreement by giving fifteen (15) days' written notice to the other Party.

4. FEES AND PAYMENT

4.1 The Client shall pay the Service Provider the fee of [AMOUNT] (the "Fee"). Payment terms are as set out in Section 3.

SIGNATURES

IN WITNESS WHEREOF, the Parties have executed this Agreement as of the Effective Date.

____________________________
Jane Doe (Service Provider)

____________________________
TechNova Inc. (Client)
Title: [TITLE]

____________________________
Date
"""


@dataclass(frozen=True)
class GenerateCall:
    """Arguments one ``generate_document`` call received."""

    document_type: str
    parties: str
    terms: list[str]
    dates: date


class FakeGenerator:
    """Drop-in replacement for ``GeminiDocumentGenerator`` in API tests.

    Returns ``text`` (or raises ``error``) and records every call so tests can
    assert on the validated inputs the route passed through.
    """

    def __init__(self, text: str = CONTRACT_TEXT, *, model: str = "gemini-test-model") -> None:
        self.text = text
        self.model = model
        self.is_configured = True
        self.truncated = False
        self.error: Exception | None = None
        self.calls: list[GenerateCall] = []

    def generate_document(self, document_type: str, parties: str, terms: list[str], dates: date) -> GenerationResult:
        self.calls.append(GenerateCall(document_type, parties, list(terms), dates))
        if self.error is not None:
            raise self.error
        return GenerationResult(
            text=self.text,
            model=self.model,
            truncated=self.truncated,
            finish_reason="MAX_TOKENS" if self.truncated else "STOP",
        )


def _forbid_real_client(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail("Tests must never construct a real google.genai.Client.")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove API keys and config overrides, reset caches and block real clients."""
    for name in _ISOLATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(genai, "Client", _forbid_real_client)
    get_settings.cache_clear()
    get_generator.cache_clear()
    yield
    get_settings.cache_clear()
    get_generator.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    """A freshly built application using the scrubbed environment."""
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_generator(app: FastAPI) -> Iterator[FakeGenerator]:
    """Install a :class:`FakeGenerator` as the app's generator dependency."""
    generator = FakeGenerator()
    app.dependency_overrides[get_generator] = lambda: generator
    yield generator
    app.dependency_overrides.clear()


@pytest.fixture
def contract_text() -> str:
    """A complete document that follows every LegalEase text convention."""
    return CONTRACT_TEXT
