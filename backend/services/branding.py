"""Branding assets and texts shared by the DOCX and PDF exporters."""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, UnidentifiedImageError

from backend.config import ASSETS_DIR

BRAND_NAME = "LegalEase"
BRAND_TAGLINE = "AI Legal Document Generator"
DEFAULT_LOGO_PATH = ASSETS_DIR / "logo.png"

DISCLAIMER_TEXT = (
    "LegalEase provides AI-generated legal document drafts for informational and drafting purposes "
    "only. It does not provide legal advice, and generated documents should be reviewed by a "
    "qualified legal professional before use."
)
FOOTER_DISCLAIMER = (
    "AI-generated draft prepared with LegalEase. Not legal advice - review by a qualified "
    "legal professional is recommended before use."
)

# Brand colours (RGB)
NAVY = (27, 42, 74)
GOLD = (176, 138, 46)
INK = (33, 37, 41)
MUTED = (110, 117, 128)
RULE = (200, 204, 212)
TABLE_HEADER_FILL = NAVY
TABLE_STRIPE_FILL = (243, 245, 249)

_ALLOWED_LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}
_MAX_LOGO_PIXELS = 25_000_000
_MAX_LOGO_EDGE = 1600


class InvalidLogoError(ValueError):
    """Raised when an uploaded logo is not a usable image."""


@dataclass(frozen=True)
class Logo:
    """A validated logo, re-encoded as PNG."""

    png_bytes: bytes
    width_px: int
    height_px: int

    @property
    def aspect_ratio(self) -> float:
        """Width divided by height."""
        return self.width_px / self.height_px if self.height_px else 1.0

    def stream(self) -> io.BytesIO:
        return io.BytesIO(self.png_bytes)


def _to_logo(image: Image.Image) -> Logo:
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    # Crop fully transparent borders so logos sit tightly in headers.
    if image.mode == "RGBA":
        bbox = image.getchannel("A").getbbox()
        if bbox:
            image = image.crop(bbox)
    image.thumbnail((_MAX_LOGO_EDGE, _MAX_LOGO_EDGE))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Logo(buffer.getvalue(), image.width, image.height)


def decode_logo(raw: bytes) -> Logo:
    """Validate untrusted image bytes and return a clean PNG logo.

    Re-encoding strips metadata and guarantees the exporters only ever embed a
    well-formed PNG.

    Raises:
        InvalidLogoError: if the bytes are not a PNG/JPEG/WEBP image or are too large.
    """
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in _ALLOWED_LOGO_FORMATS:
                raise InvalidLogoError("The logo must be a PNG or JPEG image.")
            if probe.width * probe.height > _MAX_LOGO_PIXELS:
                raise InvalidLogoError("The logo image dimensions are too large.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            return _to_logo(image)
    except InvalidLogoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidLogoError("The logo file could not be read as an image.") from exc


@lru_cache(maxsize=1)
def load_default_logo() -> Logo | None:
    """The bundled LegalEase logo, or ``None`` if the asset is missing."""
    try:
        with Image.open(DEFAULT_LOGO_PATH) as image:
            image.load()
            return _to_logo(image)
    except (OSError, UnidentifiedImageError):
        return None


def resolve_logo(custom_logo: bytes | None) -> Logo | None:
    """Use the custom logo when supplied, otherwise the LegalEase logo."""
    return decode_logo(custom_logo) if custom_logo else load_default_logo()
