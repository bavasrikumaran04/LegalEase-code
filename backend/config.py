"""Centralised application configuration.

All settings come from environment variables (optionally loaded from a local
``.env`` file). Nothing secret is hard-coded, and the API key is never included
in ``repr()`` output or logs.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"

APP_NAME = "LegalEase"
APP_VERSION = "1.0.0"

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
THINKING_LEVELS = ("low", "medium", "high")
PAGE_SIZES = ("A4", "LETTER")

# Load `.env` from the project root without overriding real environment variables.
load_dotenv(PROJECT_ROOT / ".env", override=False)

logger = logging.getLogger(__name__)


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid integer for %s; using %s.", name, default)
        return default
    return max(minimum, min(maximum, value))


def _env_choice(name: str, default: str, choices: tuple[str, ...], *, upper: bool = False) -> str:
    value = _env_str(name, default)
    value = value.upper() if upper else value.lower()
    if value not in choices:
        logger.warning("Ignoring invalid value for %s; using %s.", name, default)
        return default
    return value


def _env_list(name: str, default: str) -> tuple[str, ...]:
    raw = _env_str(name, default)
    return tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings. Build via :func:`get_settings`."""

    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_thinking_level: str = "medium"
    gemini_max_output_tokens: int = 16384
    gemini_timeout_seconds: int = 90
    gemini_max_retries: int = 2
    gemini_fallback_models: tuple[str, ...] = ()
    cors_origins: tuple[str, ...] = ("http://localhost:8501", "http://127.0.0.1:8501")
    log_level: str = "INFO"
    page_size: str = "A4"

    @property
    def ai_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gemini_api_key=_env_str("GEMINI_API_KEY"),
            gemini_model=_env_str("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL,
            gemini_thinking_level=_env_choice("GEMINI_THINKING_LEVEL", "medium", THINKING_LEVELS),
            gemini_max_output_tokens=_env_int("GEMINI_MAX_OUTPUT_TOKENS", 16384, 1024, 65536),
            gemini_timeout_seconds=_env_int("GEMINI_TIMEOUT_SECONDS", 90, 10, 600),
            gemini_max_retries=_env_int("GEMINI_MAX_RETRIES", 2, 0, 5),
            gemini_fallback_models=_env_list("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.5-flash"),
            cors_origins=_env_list("CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"),
            log_level=_env_choice(
                "LOG_LEVEL", "INFO", ("DEBUG", "INFO", "WARNING", "ERROR"), upper=True
            ),
            page_size=_env_choice("DOCUMENT_PAGE_SIZE", "A4", PAGE_SIZES, upper=True),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    return Settings.from_env()
