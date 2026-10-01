"""Generate the LegalEase brand assets in ``assets/``.

Run once (or after changing the design):

    python scripts/generate_logo.py

Produces:
    assets/logo.png        navy wordmark + gold scales, transparent (documents, light UI)
    assets/logo_light.png  ivory wordmark + gold scales, transparent (dark UI)
    assets/icon.png        square scales icon (favicon / page icon)

The artwork is drawn from primitive shapes, so it has no third-party image
dependencies.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SCALE = 4  # draw large, then downsample for smooth edges

NAVY = (27, 42, 74, 255)
IVORY = (241, 236, 224, 255)
GOLD = (190, 150, 58, 255)

SERIF_CANDIDATES = [
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/times.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/Library/Fonts/Georgia.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in SERIF_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def draw_scales(draw: ImageDraw.ImageDraw, cx: float, top: float, size: float, color) -> None:
    """Draw a stylised scales-of-justice icon of height ``size`` centred on ``cx``."""
    s = size
    stroke = max(2, int(s * 0.045))
    beam_y = top + s * 0.20
    half = s * 0.42

    # Finial, pillar and base
    r = s * 0.055
    draw.ellipse([cx - r, top + s * 0.06 - r, cx + r, top + s * 0.06 + r], fill=color)
    draw.rectangle([cx - stroke * 0.6, top + s * 0.10, cx + stroke * 0.6, top + s * 0.86], fill=color)
    draw.polygon(
        [(cx - s * 0.10, top + s * 0.86), (cx + s * 0.10, top + s * 0.86),
         (cx + s * 0.05, top + s * 0.80), (cx - s * 0.05, top + s * 0.80)],
        fill=color,
    )
    draw.rounded_rectangle(
        [cx - s * 0.26, top + s * 0.86, cx + s * 0.26, top + s * 0.93], radius=s * 0.02, fill=color
    )
    # Beam
    draw.rounded_rectangle(
        [cx - half, beam_y - stroke / 2, cx + half, beam_y + stroke / 2], radius=stroke / 2, fill=color
    )

    # Pans hanging from each end of the beam
    for side in (-1, 1):
        px = cx + side * half
        pan_y = top + s * 0.58
        pan_w = s * 0.19
        thin = max(1, int(stroke * 0.55))
        draw.line([(px, beam_y), (px - pan_w, pan_y)], fill=color, width=thin)
        draw.line([(px, beam_y), (px + pan_w, pan_y)], fill=color, width=thin)
        draw.pieslice([px - pan_w, pan_y - s * 0.10, px + pan_w, pan_y + s * 0.10], 0, 180, fill=color)


def make_wordmark(text_color, path: Path) -> None:
    height = 300 * SCALE
    font = _font(int(height * 0.50))
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bbox = probe.textbbox((0, 0), "LegalEase", font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    icon_size = height * 0.78
    icon_width = icon_size * 1.26  # pans extend beyond the nominal icon height
    gap = height * 0.12
    pad = height * 0.06
    width = int(pad + icon_width + gap + text_w + pad)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_scales(draw, pad + icon_width / 2, (height - icon_size) / 2, icon_size, GOLD)
    text_x = pad + icon_width + gap - bbox[0]
    text_y = (height - text_h) / 2 - bbox[1] + height * 0.02
    draw.text((text_x, text_y), "LegalEase", font=font, fill=text_color)

    image = image.resize((width // SCALE, height // SCALE), Image.LANCZOS)
    image.save(path, optimize=True)


def make_icon(path: Path) -> None:
    size = 256 * SCALE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22, fill=NAVY)
    draw_scales(draw, size / 2, size * 0.14, size * 0.72, GOLD)
    image.resize((256, 256), Image.LANCZOS).save(path, optimize=True)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    make_wordmark(NAVY, ASSETS / "logo.png")
    make_wordmark(IVORY, ASSETS / "logo_light.png")
    make_icon(ASSETS / "icon.png")
    print(f"Brand assets written to {ASSETS}")


if __name__ == "__main__":
    main()
