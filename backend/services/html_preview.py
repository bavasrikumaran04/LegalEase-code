"""Render document text as semantic, safe HTML for the in-app preview.

Every piece of text is HTML-escaped, so AI output or user edits can never
inject markup or scripts. Styling is supplied by the frontend via the
``le-*`` CSS classes.
"""

from __future__ import annotations

from html import escape

from backend.services.document_service import (
    Block,
    BlockType,
    parse_document,
    split_lead,
    split_placeholders,
)


def _inline(text: str, *, allow_lead: bool = True) -> str:
    """Escape text, bold a leading legal phrase and highlight [PLACEHOLDERS]."""
    lead, rest = split_lead(text) if allow_lead else ("", text)
    html = f"<strong>{escape(lead)}</strong>" if lead else ""
    for segment, is_placeholder in split_placeholders(rest):
        if is_placeholder:
            html += f'<mark class="le-placeholder">{escape(segment)}</mark>'
        else:
            html += escape(segment)
    return html


def _space_class(block: Block) -> str:
    return "" if block.space_before else " le-tight"


def format_html_preview(text: str | None, fallback_title: str = "Legal Document") -> str:
    """Convert document text into an ``<article>`` of semantic HTML."""
    parsed = parse_document(text, fallback_title)
    parts: list[str] = [
        '<article class="le-doc">',
        f'<h1 class="le-title">{_inline(parsed.title, allow_lead=False)}</h1>',
    ]
    open_list_level: int | None = None

    def close_list() -> None:
        nonlocal open_list_level
        if open_list_level is not None:
            parts.append("</ul>")
            open_list_level = None

    for block in parsed.blocks:
        if block.type is BlockType.BULLET:
            if open_list_level != block.level:
                close_list()
                parts.append(f'<ul class="le-list le-level-{block.level}{_space_class(block)}">')
                open_list_level = block.level
            parts.append(f"<li>{_inline(block.text)}</li>")
            continue
        close_list()

        if block.type is BlockType.HEADING:
            parts.append(f'<h2 class="le-heading">{_inline(block.display_text, allow_lead=False)}</h2>')
        elif block.type is BlockType.SUBHEADING:
            parts.append(
                f'<p class="le-subheading{_space_class(block)}">{_inline(block.display_text, allow_lead=False)}</p>'
            )
        elif block.type is BlockType.NUMBERED:
            parts.append(
                f'<div class="le-clause le-level-{block.level}{_space_class(block)}">'
                f'<span class="le-marker">{escape(block.marker)}</span>'
                f'<span class="le-clause-text">{_inline(block.text)}</span></div>'
            )
        elif block.type is BlockType.SIGNATURE_LINE:
            parts.append(f'<div class="le-signature-line{_space_class(block)}" aria-hidden="true"></div>')
        else:
            parts.append(f'<p class="le-paragraph{_space_class(block)}">{_inline(block.text)}</p>')

    close_list()
    parts.append("</article>")
    return "\n".join(parts)
