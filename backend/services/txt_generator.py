"""Plain-text (.txt) export."""

from __future__ import annotations

import textwrap

from backend.services.branding import DISCLAIMER_TEXT
from backend.services.document_service import BlockType, parse_document

LINE_WIDTH = 88
_INDENT = "    "


def _wrap(text: str, *, first: str = "", rest: str = "") -> list[str]:
    return textwrap.wrap(
        text, width=LINE_WIDTH, initial_indent=first, subsequent_indent=rest,
        break_long_words=False, break_on_hyphens=False,
    ) or [first.rstrip()]


def format_txt(text: str, doc_type: str = "Legal Document", *, include_disclaimer: bool = True) -> str:
    """Render the (edited) document as neatly wrapped plain text.

    Headings are separated by blank lines, list items get hanging indents and
    paragraphs wrap at 88 characters. The wording is exactly the user's.
    """
    parsed = parse_document(text, doc_type)
    title = parsed.title.upper()
    lines: list[str] = [title.center(LINE_WIDTH).rstrip(), ("=" * min(len(title), LINE_WIDTH)).center(LINE_WIDTH).rstrip(), ""]

    for block in parsed.blocks:
        if block.type is BlockType.HEADING:
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(_wrap(block.display_text))
            lines.append("")
            continue

        if block.space_before and lines and lines[-1] != "":
            lines.append("")

        indent = _INDENT * block.level
        if block.type is BlockType.BULLET:
            lines.extend(_wrap(block.text, first=f"{indent}  • ", rest=f"{indent}    "))
        elif block.type is BlockType.NUMBERED:
            marker = f"{indent}{block.marker} "
            lines.extend(_wrap(block.text, first=marker, rest=" " * len(marker)))
        elif block.type is BlockType.SIGNATURE_LINE:
            lines.append("_" * 36)
        else:  # paragraph / subheading
            lines.extend(_wrap(block.display_text))

    while lines and lines[-1] == "":
        lines.pop()

    if include_disclaimer:
        lines.extend(["", "", "-" * LINE_WIDTH])
        lines.extend(_wrap(DISCLAIMER_TEXT))
    return "\n".join(lines) + "\n"
