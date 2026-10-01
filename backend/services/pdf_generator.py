"""PDF export: a branded, print-ready rendering of the (edited) document.

Every page carries the logo in its header and a footer with the disclaimer and
"Page X of Y". Page 1 opens with the centred logo and the title; later pages
use a compact running header. Text is set in an embedded Unicode serif family
found on the system (Times New Roman, Liberation Serif or DejaVu Serif). If
none is installed the core Times font is used and text is transliterated to
latin-1, so an unsupported character can never make an export fail.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from fpdf import FPDF, XPos, YPos

from backend.services.branding import (
    BRAND_NAME,
    FOOTER_DISCLAIMER,
    GOLD,
    INK,
    MUTED,
    NAVY,
    RULE,
    Logo,
    load_default_logo,
)
from backend.services.document_service import Block, BlockType, ParsedDocument, parse_document, split_lead

Color = tuple[int, int, int]

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_EMBEDDED_FAMILY = "LegalEaseSerif"
_CORE_FAMILY = "Times"
_FONT_STYLES = ("", "B", "I")

_WINDOWS_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_MACOS_FONTS = Path("/System/Library/Fonts/Supplemental")
_LIBERATION_DIRS = (
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/liberation2"),
    Path("/usr/share/fonts/liberation-serif"),
    Path("/usr/share/fonts/liberation"),
)
_DEJAVU_DIRS = (Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"))

# (regular, bold, italic) files of each candidate family, in order of preference.
_SERIF_CANDIDATES: tuple[tuple[Path, Path, Path], ...] = (
    (_WINDOWS_FONTS / "times.ttf", _WINDOWS_FONTS / "timesbd.ttf", _WINDOWS_FONTS / "timesi.ttf"),
    *(
        (d / "LiberationSerif-Regular.ttf", d / "LiberationSerif-Bold.ttf", d / "LiberationSerif-Italic.ttf")
        for d in _LIBERATION_DIRS
    ),
    *((d / "DejaVuSerif.ttf", d / "DejaVuSerif-Bold.ttf", d / "DejaVuSerif-Italic.ttf") for d in _DEJAVU_DIRS),
    (
        _MACOS_FONTS / "Times New Roman.ttf",
        _MACOS_FONTS / "Times New Roman Bold.ttf",
        _MACOS_FONTS / "Times New Roman Italic.ttf",
    ),
)


@lru_cache(maxsize=1)
def _find_serif_fonts() -> tuple[Path, Path, Path] | None:
    """The first installed serif family with regular, bold and italic faces."""
    for paths in _SERIF_CANDIDATES:
        if all(path.is_file() for path in paths):
            return paths
    return None


# ---------------------------------------------------------------------------
# Character fitting
# ---------------------------------------------------------------------------

_LATIN1_GLYPHS = frozenset(range(0x20, 0x7F)) | frozenset(range(0xA0, 0x100))

# Stand-ins used when the active font cannot draw a character.
_SUBSTITUTES = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2022": "\xb7", "\u2023": "\xb7", "\u2043": "-", "\u2219": "\xb7",
    "\u25aa": "\xb7", "\u25cf": "\xb7", "\u25e6": "\xb7",
    "\u2026": "...",
    "\u20b9": "Rs.", "\u20a8": "Rs.", "\u20ac": "EUR",
    "\u2190": "<-", "\u2192": "->", "\u2194": "<->", "\u21d2": "=>",
    "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u2248": "~",
}


def _substitute(char: str, glyphs: frozenset[int]) -> str:
    """A drawable stand-in for ``char``: a known substitute, its decomposition or "?"."""
    if unicodedata.category(char) in ("Cc", "Cf"):
        return ""
    substitute = _SUBSTITUTES.get(char)
    if substitute and all(ord(c) in glyphs for c in substitute):
        return substitute
    decomposed = "".join(
        c for c in unicodedata.normalize("NFKD", char) if ord(c) in glyphs and not unicodedata.combining(c)
    )
    return decomposed or "?"


def _fit_text(text: str, glyphs: frozenset[int]) -> str:
    """Replace every character outside ``glyphs`` so the text can always be drawn."""
    if all(ord(char) in glyphs for char in text):
        return text
    return "".join(char if ord(char) in glyphs else _substitute(char, glyphs) for char in text)


# ---------------------------------------------------------------------------
# Layout (millimetres; font sizes in points)
# ---------------------------------------------------------------------------

_PAGE_FORMATS = {"A4": "a4", "LETTER": "letter"}
_MARGIN_X = 22.0
_HEADER_TOP = 12.0
_BOTTOM_MARGIN = 25.0          # body text ends here, clear of the footer

_COVER_LOGO_MAX_W, _COVER_LOGO_MAX_H = 56.0, 16.0
_RUNNING_LOGO_H, _RUNNING_LOGO_MAX_W = 6.5, 40.0
_WORDMARK_COVER_SIZE, _COVER_WORDMARK_H = 22.0, 10.0
_WORDMARK_RUNNING_SIZE = 11.0
_RUNNING_TITLE_SIZE, _RUNNING_TITLE_GAP = 8.5, 8.0
_COVER_GAP = 8.0               # logo -> title on page 1
_RUNNING_RULE_GAP = 2.5        # running logo -> header rule
_RUNNING_BODY_GAP = 7.0        # header rule -> body text

_FOOTER_PAGE_Y = 12.5          # page-number line, measured up from the page bottom
_FOOTER_PAGE_SIZE, _FOOTER_PAGE_LINE_H = 8.5, 4.0
_FOOTER_NOTE_SIZE, _FOOTER_NOTE_LINE_H = 7.5, 3.4
_FOOTER_RULE_GAP = 1.8

_TITLE_SIZE, _TITLE_LINE_H = 17.0, 8.0
_TITLE_RULE_W, _TITLE_RULE_GAP, _TITLE_BODY_GAP = 36.0, 2.5, 8.0
_HEADING_SIZE, _HEADING_LINE_H = 12.0, 6.2
_BODY_SIZE, _LINE_H = 11.5, 5.8

_HEADING_GAP_BEFORE, _HEADING_GAP_AFTER = 6.0, 1.8
_PARAGRAPH_GAP = 2.8           # above blocks preceded by a blank line
_ITEM_GAP = 1.0                # between list items written on consecutive lines
_KEEP_LINES = 2                # a block never starts with fewer lines than this on a page
_KEEP_WITH_NEXT_LINES = 4      # lead-ins and attestations up to this length stay with what follows
_MAX_JUSTIFIED_WORD = 0.4      # blocks with a longer token (share of the column) are left-aligned

_BULLET = "\u2022"
_BULLET_STEP = 6.0             # hanging indent per bullet level
_BULLET_OFFSET = 4.2           # bullet glyph sits this far left of the item text
_CLAUSE_COLUMN, _SUBCLAUSE_COLUMN = 11.0, 9.0
_MARKER_GAP = 2.5
_MAX_LEVEL = 4

_SIGNATURE_SPACE = 13.0        # room above the line for a handwritten signature
_SIGNATURE_W, _SIGNATURE_GAP_BELOW = 70.0, 1.5
_MAX_SIGNATURE_RUN = 120.0     # consecutive signature blocks up to this height share a page

_HAIRLINE, _TITLE_RULE_LINE, _SIGNATURE_LINE = 0.25, 0.6, 0.3


@dataclass(frozen=True)
class _TextLayout:
    """How one text block is set: a single multi_cell plus an optional hanging marker."""

    text: str
    indent: float = 0.0          # start of the text column, relative to the left margin
    style: str = ""
    size: float = _BODY_SIZE
    line_height: float = _LINE_H
    color: Color = INK
    align: str = "J"
    markdown: bool = False
    marker: str = ""
    marker_indent: float = 0.0
    marker_style: str = ""
    marker_color: Color = INK


class _LegalPdf(FPDF):
    """An FPDF document with LegalEase page furniture and body-block rendering."""

    # fpdf2's inline markup is remapped to control characters, which
    # sanitize_text() and _fit_text() strip from all document text. User text
    # such as "____", "--" or "**" is therefore always drawn literally, while
    # the renderer can still switch to bold mid-line for a leading phrase.
    MARKDOWN_BOLD_MARKER = "\x02\x02"
    MARKDOWN_ITALICS_MARKER = "\x03\x03"
    MARKDOWN_STRIKETHROUGH_MARKER = "\x04\x04"
    MARKDOWN_UNDERLINE_MARKER = "\x05\x05"
    MARKDOWN_MARKERS = (
        MARKDOWN_BOLD_MARKER,
        MARKDOWN_ITALICS_MARKER,
        MARKDOWN_STRIKETHROUGH_MARKER,
        MARKDOWN_UNDERLINE_MARKER,
    )
    MARKDOWN_ESCAPE_CHARACTER = "\x01"
    MARKDOWN_LINK_REGEX = re.compile(r"(?!)")  # never matches: "[x](y)" stays literal
    # fpdf2's total-pages alias, spelt so that document text can never contain it.
    TOTAL_PAGES_ALIAS = "\x06\x06\x06"

    def __init__(self, *, title: str, logo: Logo | None, include_disclaimer: bool, page_size: str) -> None:
        page_format = _PAGE_FORMATS.get((page_size or "").upper())
        if page_format is None:
            raise ValueError(f"Unsupported page size: {page_size!r}")
        super().__init__(orientation="portrait", unit="mm", format=page_format)
        self._family, self._glyphs = self._load_fonts()
        self._title = self._fit(title.upper())
        self._logo = logo
        self._include_disclaimer = include_disclaimer
        self._body_top = _HEADER_TOP
        self.c_margin = 0
        self.set_margins(_MARGIN_X, _HEADER_TOP, _MARGIN_X)
        self.set_auto_page_break(True, margin=_BOTTOM_MARGIN)
        self.alias_nb_pages(self.TOTAL_PAGES_ALIAS)

    def _load_fonts(self) -> tuple[str, frozenset[int]]:
        """Embed the system serif family, or fall back to core Times (latin-1)."""
        paths = _find_serif_fonts()
        if paths is None:
            return _CORE_FAMILY, _LATIN1_GLYPHS
        for style, path in zip(_FONT_STYLES, paths):
            self.add_font(_EMBEDDED_FAMILY, style, str(path))
        # Only characters every face can draw count as supported.
        covered = frozenset.intersection(*(frozenset(font.cmap) for font in self.fonts.values()))
        return _EMBEDDED_FAMILY, frozenset(cp for cp in covered if cp >= 0x20 and not 0x7F <= cp < 0xA0)

    # -- helpers ------------------------------------------------------------

    def _fit(self, text: str) -> str:
        return _fit_text(text, self._glyphs)

    def _use_font(self, style: str, size: float, color: Color) -> None:
        self.set_font(self._family, style, size)
        self.set_text_color(*color)

    def _hline(self, x1: float, x2: float, y: float, color: Color, width: float) -> None:
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(x1, y, x2, y)

    def _truncate(self, text: str, width: float) -> str:
        """Shorten ``text`` with an ellipsis until it fits ``width`` in the current font."""
        if self.get_string_width(text) <= width:
            return text
        ellipsis = self._fit("\u2026")
        while text and self.get_string_width(text + ellipsis) > width:
            text = text[:-1]
        return text.rstrip() + ellipsis

    # -- page furniture -----------------------------------------------------

    def header(self) -> None:
        if self.page_no() == 1:
            self._cover_header()
        else:
            self._running_header()
        self._body_top = self.y

    def _cover_header(self) -> None:
        """Page 1: the logo (or wordmark) centred above the title."""
        if self._logo is not None:
            width, height = _logo_size(self._logo, _COVER_LOGO_MAX_W, _COVER_LOGO_MAX_H)
            self.image(self._logo.stream(), x=(self.w - width) / 2, y=_HEADER_TOP, w=width, h=height)
        else:
            height = _COVER_WORDMARK_H
            self._use_font("B", _WORDMARK_COVER_SIZE, NAVY)
            self.set_xy(self.l_margin, _HEADER_TOP)
            self.cell(self.epw, height, BRAND_NAME, align="C")
        self.set_y(_HEADER_TOP + height + _COVER_GAP)

    def _running_header(self) -> None:
        """Pages 2+: a small logo at the left, the title at the right and a rule below."""
        band = _RUNNING_LOGO_H
        if self._logo is not None:
            width, height = _logo_size(self._logo, _RUNNING_LOGO_MAX_W, band)
            y = _HEADER_TOP + (band - height) / 2
            self.image(self._logo.stream(), x=self.l_margin, y=y, w=width, h=height)
        else:
            self._use_font("B", _WORDMARK_RUNNING_SIZE, NAVY)
            width = self.get_string_width(BRAND_NAME)
            self.set_xy(self.l_margin, _HEADER_TOP)
            self.cell(width, band, BRAND_NAME)
        self._use_font("", _RUNNING_TITLE_SIZE, MUTED)
        self.set_xy(self.l_margin, _HEADER_TOP)
        self.cell(self.epw, band, self._truncate(self._title, self.epw - width - _RUNNING_TITLE_GAP), align="R")
        rule_y = _HEADER_TOP + band + _RUNNING_RULE_GAP
        self._hline(self.l_margin, self.w - self.r_margin, rule_y, RULE, _HAIRLINE)
        self.set_y(rule_y + _RUNNING_BODY_GAP)

    def footer(self) -> None:
        page_y = self.h - _FOOTER_PAGE_Y
        top = page_y
        if self._include_disclaimer:
            self._use_font("I", _FOOTER_NOTE_SIZE, MUTED)
            note = self._fit(FOOTER_DISCLAIMER)
            lines = self.multi_cell(self.epw, _FOOTER_NOTE_LINE_H, note, dry_run=True, output="LINES")
            top = page_y - len(lines) * _FOOTER_NOTE_LINE_H - 0.4
            self.set_xy(self.l_margin, top)
            self.multi_cell(self.epw, _FOOTER_NOTE_LINE_H, note, align="C")
        self._hline(self.l_margin, self.w - self.r_margin, top - _FOOTER_RULE_GAP, RULE, _HAIRLINE)
        self._use_font("", _FOOTER_PAGE_SIZE, MUTED)
        self.set_xy(self.l_margin, page_y)
        self.cell(self.epw, _FOOTER_PAGE_LINE_H, f"Page {self.page_no()} of {self.TOTAL_PAGES_ALIAS}", align="C")

    # -- body ---------------------------------------------------------------

    def render_document(self, parsed: ParsedDocument) -> None:
        """Lay out the title and every body block."""
        self.add_page()
        self._render_title()
        blocks = parsed.blocks
        for index, block in enumerate(blocks):
            previous = blocks[index - 1] if index else None
            gap = self._gap(block, previous)
            keep = self._keep_height(blocks, index)
            if block.type is BlockType.SIGNATURE_LINE:
                self._advance(gap, keep, collapsible=False)
                self._hline(self.l_margin, self.l_margin + _SIGNATURE_W, self.y, INK, _SIGNATURE_LINE)
                self.y += _SIGNATURE_GAP_BELOW
                continue
            self._advance(gap, keep)
            if block.type is BlockType.HEADING:
                self.start_section(block.display_text)
            self._draw_text(self._layout(block))
            if block.type is BlockType.HEADING:
                self.y += _HEADING_GAP_AFTER

    def _render_title(self) -> None:
        self._use_font("B", _TITLE_SIZE, NAVY)
        self.multi_cell(self.epw, _TITLE_LINE_H, self._title, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        rule_y = self.y + _TITLE_RULE_GAP
        centre = self.w / 2
        self._hline(centre - _TITLE_RULE_W / 2, centre + _TITLE_RULE_W / 2, rule_y, GOLD, _TITLE_RULE_LINE)
        self.set_y(rule_y + _TITLE_BODY_GAP)
        self._body_top = self.y  # no extra gap above the first block

    def _rich(self, text: str) -> tuple[str, bool]:
        """Fit ``text`` for the font, marking a leading legal phrase ("WHEREAS,") bold."""
        lead, rest = split_lead(text)
        if not lead:
            return self._fit(text), False
        bold = self.MARKDOWN_BOLD_MARKER
        return f"{bold}{self._fit(lead)}{bold}{self._fit(rest)}", True

    def _layout(self, block: Block) -> _TextLayout:
        """Font, indentation and marker of a text block."""
        if block.type is BlockType.HEADING:
            return _TextLayout(
                self._fit(block.display_text), style="B", size=_HEADING_SIZE,
                line_height=_HEADING_LINE_H, color=NAVY, align="L",
            )
        if block.type is BlockType.SUBHEADING:
            return _TextLayout(self._fit(block.display_text), style="B", align="L")
        text, markdown = self._rich(block.text)
        level = min(block.level, _MAX_LEVEL)
        self._use_font("", _BODY_SIZE, INK)
        if block.type is BlockType.BULLET:
            indent = _BULLET_STEP * (level + 1)
            layout = _TextLayout(
                text, indent=indent, markdown=markdown, marker=self._fit(_BULLET),
                marker_indent=indent - _BULLET_OFFSET, marker_style="B", marker_color=NAVY,
            )
        elif block.type is BlockType.NUMBERED:
            marker = self._fit(block.marker)
            marker_indent = _CLAUSE_COLUMN * min(level, 1) + _SUBCLAUSE_COLUMN * max(level - 1, 0)
            column = _CLAUSE_COLUMN if level == 0 else _SUBCLAUSE_COLUMN
            column = max(column, self.get_string_width(marker) + _MARKER_GAP)
            layout = _TextLayout(
                text, indent=marker_indent + column, markdown=markdown, marker=marker, marker_indent=marker_indent
            )
        else:
            layout = _TextLayout(text, markdown=markdown)
        # A very long token (e.g. a URL) is wrapped mid-word; justifying the
        # line before it would leave gaping word spaces.
        longest = max(block.text.split(), key=len, default="")
        if self.get_string_width(self._fit(longest)) > (self.epw - layout.indent) * _MAX_JUSTIFIED_WORD:
            layout = replace(layout, align="L")
        return layout

    def _line_count(self, layout: _TextLayout, at_most: int | None = None) -> int:
        """Number of lines the text wraps to, capped at ``at_most``."""
        self._use_font(layout.style, layout.size, layout.color)
        width = self.epw - layout.indent
        if self.get_string_width(layout.text, markdown=layout.markdown) <= width:
            return 1
        if at_most is not None and at_most <= 2:
            return at_most  # longer than one line; no need to wrap it
        lines = self.multi_cell(
            width, layout.line_height, layout.text, align=layout.align,
            markdown=layout.markdown, dry_run=True, output="LINES",
        )
        return len(lines) if at_most is None else min(len(lines), at_most)

    def _draw_text(self, layout: _TextLayout) -> None:
        y = self.y
        if layout.marker:
            self._use_font(layout.marker_style, layout.size, layout.marker_color)
            self.set_xy(self.l_margin + layout.marker_indent, y)
            self.cell(layout.indent - layout.marker_indent, layout.line_height, layout.marker)
        self._use_font(layout.style, layout.size, layout.color)
        self.set_xy(self.l_margin + layout.indent, y)
        self.multi_cell(
            self.epw - layout.indent, layout.line_height, layout.text, align=layout.align,
            markdown=layout.markdown, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )

    @staticmethod
    def _gap(block: Block, previous: Block | None) -> float:
        """Vertical space above ``block``."""
        if block.type is BlockType.HEADING:
            return _HEADING_GAP_BEFORE
        if block.type is BlockType.SIGNATURE_LINE:
            return _SIGNATURE_SPACE
        if previous is None or previous.type is BlockType.HEADING:
            return 0.0  # the title / heading already leaves room
        if block.space_before:
            return _PARAGRAPH_GAP
        return _ITEM_GAP if block.type in (BlockType.BULLET, BlockType.NUMBERED) else 0.0

    def _keep_height(self, blocks: Sequence[Block], index: int, depth: int = 0) -> float:
        """Height that must fit below the gap for ``blocks[index]`` to start on this page.

        Headings, labels and short lead-ins keep with what follows, a signature
        line keeps with the name/date lines beneath it, and other blocks need
        their first lines.
        """
        block = blocks[index]
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        if block.type is BlockType.SIGNATURE_LINE:
            return self._signature_keep_height(blocks, index)
        layout = self._layout(block)
        if following is None or depth >= 2 or not self._keeps_with_next(block, following, layout):
            return self._line_count(layout, at_most=_KEEP_LINES) * layout.line_height
        after = _HEADING_GAP_AFTER if block.type is BlockType.HEADING else 0.0
        return (
            self._line_count(layout) * layout.line_height
            + after
            + self._gap(following, block)
            + self._keep_height(blocks, index + 1, depth + 1)
        )

    def _keeps_with_next(self, block: Block, following: Block, layout: _TextLayout) -> bool:
        """Headings and labels always; a short "...the following:" lead-in or attestation clause too."""
        if block.type in (BlockType.HEADING, BlockType.SUBHEADING):
            return True
        leads_in = block.text.endswith(":") and following.type in (BlockType.BULLET, BlockType.NUMBERED)
        attests = block.space_before and following.type is BlockType.SIGNATURE_LINE
        if not (leads_in or attests):
            return False
        return self._line_count(layout, at_most=_KEEP_WITH_NEXT_LINES + 1) <= _KEEP_WITH_NEXT_LINES

    def _signature_keep_height(self, blocks: Sequence[Block], index: int) -> float:
        """Height of the signature line at ``index`` with its captions.

        The signature lines that directly follow are kept on the same page too
        (so a party's "Date" line is never stranded) when the run is not too tall.
        """
        heights = [
            _SIGNATURE_GAP_BELOW
            + sum(self._line_count(layout) * layout.line_height for layout in map(self._layout, captions))
            for captions in _signature_run(blocks, index)
        ]
        run = sum(heights) + _SIGNATURE_SPACE * (len(heights) - 1)
        return run if run <= _MAX_SIGNATURE_RUN else heights[0]

    def _advance(self, gap: float, keep: float, *, collapsible: bool = True) -> None:
        """Move down by ``gap``, starting a new page first unless ``keep`` mm fit below it.

        Collapsible gaps are dropped at the top of a page.
        """
        at_top = self.y <= self._body_top + 0.01
        if not at_top and self.will_page_break(gap + keep):
            self.add_page()
            at_top = True
        if not (collapsible and at_top):
            self.y += gap


def _logo_size(logo: Logo, max_w: float, max_h: float) -> tuple[float, float]:
    """The largest (width, height) within max_w x max_h that keeps the logo's aspect ratio."""
    width = min(max_w, max_h * logo.aspect_ratio)
    return width, width / logo.aspect_ratio


def _signature_captions(blocks: Sequence[Block], index: int) -> list[Block]:
    """The name/title/date lines written directly beneath the signature line at ``index``."""
    captions: list[Block] = []
    for block in blocks[index + 1:]:
        if block.space_before or block.type not in (BlockType.PARAGRAPH, BlockType.SUBHEADING):
            break
        captions.append(block)
    return captions


def _signature_run(blocks: Sequence[Block], index: int) -> list[list[Block]]:
    """Captions of each signature line in the run of consecutive signature lines at ``index``."""
    run: list[list[Block]] = []
    while index < len(blocks) and blocks[index].type is BlockType.SIGNATURE_LINE:
        captions = _signature_captions(blocks, index)
        run.append(captions)
        index += 1 + len(captions)
    return run


def format_pdf(
    text: str,
    doc_type: str = "Legal Document",
    *,
    include_disclaimer: bool = True,
    logo: Logo | None = None,
    page_size: str = "A4",
) -> bytes:
    """Render the (edited) document as a branded PDF and return its bytes.

    ``logo`` defaults to the bundled LegalEase logo, or a text wordmark when
    that asset is missing. ``page_size`` is "A4" or "LETTER".

    Raises:
        ValueError: for an unsupported ``page_size``.
    """
    doc_type = doc_type or "Legal Document"
    parsed = parse_document(text, doc_type)
    pdf = _LegalPdf(
        title=parsed.title,
        logo=logo or load_default_logo(),
        include_disclaimer=include_disclaimer,
        page_size=page_size,
    )
    pdf.set_title(parsed.title)
    pdf.set_author(BRAND_NAME)
    pdf.set_subject(doc_type)
    pdf.set_creator(BRAND_NAME)
    pdf.set_lang("en")
    pdf.render_document(parsed)
    return bytes(pdf.output())
