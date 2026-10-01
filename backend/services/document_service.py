"""Shared text utilities used by every LegalEase output format.

The generated (and user-edited) document is stored as *plain text* that follows
a few simple conventions (ALL-CAPS / numbered headings, "• " bullets, "1.1"
clauses, "(a)" sub-items, "____" signature lines). This module:

* sanitises raw text (smart quotes, invisible characters, control characters);
* normalises Markdown artefacts that the AI may still emit into those conventions;
* parses the text into typed :class:`Block` objects that the HTML preview, TXT,
  DOCX and PDF renderers all consume - so formatting rules live in one place;
* provides small helpers for terms, dates, placeholders and file names.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

# ---------------------------------------------------------------------------
# Character-level sanitisation
# ---------------------------------------------------------------------------

_CHAR_REPLACEMENTS = {
    # Typographic quotes -> straight quotes
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u00ab": '"', "\u00bb": '"',
    # Ellipsis and odd dashes
    "\u2026": "...", "\u2012": "-", "\u2015": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
    # Exotic spaces -> regular space
    "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ", "\u2005": " ",
    "\u2006": " ", "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ", "\u205f": " ", "\u3000": " ",
    # Line / paragraph separators -> newline
    "\u2028": "\n", "\u2029": "\n", "\x0b": "\n", "\x0c": "\n",
    # Invisible characters -> removed
    "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\ufeff": "", "\u00ad": "",
    # Tabs -> spaces (keeps indentation meaningful)
    "\t": "    ",
}
_CHAR_TABLE = str.maketrans(_CHAR_REPLACEMENTS)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def sanitize_text(text: str | None) -> str:
    """Normalise characters so text renders cleanly in every output format.

    Converts typographic quotes to straight quotes, unusual spaces to regular
    spaces, removes invisible/control characters and unifies line endings.
    Legitimate Unicode (accents, currency symbols, dashes) is preserved.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_CHAR_TABLE)
    text = _CONTROL_CHARS_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Markdown normalisation
# ---------------------------------------------------------------------------

_BULLET_CHARS = "-*+•●▪◦‣∙·○■□➢►"
_MD_BULLET_RE = re.compile(rf"^(?P<indent>\s*)[{re.escape(_BULLET_CHARS)}]\s+(?P<text>\S.*)$")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:=\s*){3,}|(?:~\s*){3,})$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_WHOLE_BOLD_RE = re.compile(r"^(?:\*\*(?P<a>[^*_][^*]*?)\*\*|__(?P<b>[^*_][^_]*?)__)(?P<tail>[:.]?)\s*$")
_LEADING_BOLD_RE = re.compile(r"^(?:\*\*(?P<a>[^*_][^*]{0,79}?)\*\*|__(?P<b>[^*_][^_]{0,79}?)__)\s*(?P<rest>\S.*)$")
_SECTION_NUMBER_RE = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVXLC]{1,6}\.)\s+\S")

# Underscore runs are signature blanks ("Date: ________"), so "__bold__" only
# matches when it wraps real words and is not part of a longer underscore run.
_BOLD_STAR_RE = re.compile(r"(?<!\*)\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*(?!\*)")
_BOLD_UNDERSCORE_RE = re.compile(r"(?<!_)__(?=[^\s_])(.+?)(?<=[^\s_])__(?!_)")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_ESCAPED_MD_RE = re.compile(r"\\([*_#`\[\]])")


def strip_inline_markdown(text: str) -> str:
    """Remove inline Markdown emphasis/code/link syntax, keeping the words."""
    text = _LINK_RE.sub(r"\1 (\2)", text)
    text = _CODE_RE.sub(r"\1", text)
    text = _BOLD_STAR_RE.sub(r"\1", text)
    text = _BOLD_UNDERSCORE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _ESCAPED_MD_RE.sub(r"\1", text)
    return text


def _indent_level(indent: str) -> int:
    width = len(indent.replace("\t", "    "))
    if width < 2:
        return 0
    if width < 6:
        return 1
    return 2


def _table_row_to_bullet(line: str) -> str:
    cells = [strip_inline_markdown(c.strip()) for c in line.strip().strip("|").split("|")]
    cells = [c for c in cells if c]
    if not cells:
        return ""
    joined = f"{cells[0]}: {cells[1]}" if len(cells) == 2 else "; ".join(cells)
    return f"• {joined}"


def normalize_document_text(text: str | None) -> str:
    """Convert AI output (or pasted text) into LegalEase's plain-text conventions.

    Markdown headings become ALL-CAPS heading lines, list markers become "• "
    bullets, emphasis/code markers are stripped, code fences, horizontal rules
    and table separators are removed, and blank lines are collapsed. The
    function is idempotent: normalising already-normalised text is a no-op.
    """
    text = sanitize_text(text)
    out: list[str] = []
    source_lines = text.split("\n")

    for index, raw_line in enumerate(source_lines):
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            out.append("")
            continue
        if _FENCE_RE.match(stripped) or _HR_RE.match(stripped):
            continue
        if stripped.count("|") >= 1 and _TABLE_SEPARATOR_RE.match(stripped):
            continue
        if stripped.startswith(">"):
            line = stripped.lstrip(">").strip()
            stripped = line
            if not stripped:
                out.append("")
                continue

        # Markdown tables -> bullets ("| Fee | [AMOUNT] |" -> "• Fee: [AMOUNT]").
        # A header row (one followed by a "|---|" separator) is dropped.
        if stripped.startswith("|") and stripped.count("|") >= 2:
            next_line = source_lines[index + 1].strip() if index + 1 < len(source_lines) else ""
            if next_line.count("|") >= 1 and _TABLE_SEPARATOR_RE.match(next_line):
                continue
            bullet = _table_row_to_bullet(stripped)
            if bullet:
                out.append(bullet)
            continue

        # Markdown headings -> ALL-CAPS heading lines.
        heading = _MD_HEADING_RE.match(line)
        if heading:
            heading_text = strip_inline_markdown(heading.group("text")).strip()
            heading_text = heading_text.rstrip(":").strip()
            if heading_text:
                out.append(heading_text.upper())
            continue

        # Whole-line bold -> heading (or label when it ends with a colon).
        whole_bold = _WHOLE_BOLD_RE.match(stripped)
        bold_text = (whole_bold.group("a") or whole_bold.group("b") or "") if whole_bold else ""
        if whole_bold and len(bold_text) <= 100:
            inner = strip_inline_markdown(bold_text).strip()
            tail = whole_bold.group("tail")
            if inner.endswith(":") or tail == ":":
                out.append(inner.rstrip(":").strip() + ":")
            else:
                out.append(inner.rstrip(".").strip().upper())
            continue

        # "**1. Services.** The provider shall..." -> heading line + paragraph.
        leading_bold = _LEADING_BOLD_RE.match(stripped)
        bold_head = (leading_bold.group("a") or leading_bold.group("b") or "").strip() if leading_bold else ""
        if leading_bold and _SECTION_NUMBER_RE.match(bold_head + " x"):
            head = bold_head.rstrip(":.").strip()
            if re.fullmatch(r"\d{1,2}\.?|[IVXLC]{1,6}\.", head) is None:
                out.append(head.upper())
                out.append(strip_inline_markdown(leading_bold.group("rest")).strip())
                continue

        # Bullets with any common marker -> canonical "• " with indentation.
        bullet = _MD_BULLET_RE.match(line)
        if bullet and not re.fullmatch(r"[-*_\s]+", stripped):
            level = _indent_level(bullet.group("indent"))
            item = strip_inline_markdown(bullet.group("text")).strip()
            out.append(f"{'  ' * level}• {item}")
            continue

        indent = line[: len(line) - len(line.lstrip())]
        cleaned = strip_inline_markdown(stripped)
        out.append(f"{indent}{cleaned}" if indent and _is_list_like(cleaned) else cleaned)

    # Collapse runs of blank lines and trim.
    collapsed: list[str] = []
    for line in out:
        if not line.strip():
            if collapsed and collapsed[-1] == "":
                continue
            collapsed.append("")
        else:
            collapsed.append(line)
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    return "\n".join(collapsed)


def _is_list_like(text: str) -> bool:
    return bool(_CLAUSE_RE.match(text) or _SUBITEM_RE.match(text))


# ---------------------------------------------------------------------------
# Structured parsing
# ---------------------------------------------------------------------------


class BlockType(str, Enum):
    """Kinds of content a legal document is built from."""

    HEADING = "heading"                # Section heading, e.g. "1. SERVICES" / "RECITALS"
    SUBHEADING = "subheading"          # Label line, e.g. "Between:" / "SERVICE PROVIDER:"
    PARAGRAPH = "paragraph"
    BULLET = "bullet"                  # Unordered list item ("• ...")
    NUMBERED = "numbered"              # Clause / ordered item with explicit marker ("1.1", "(a)")
    SIGNATURE_LINE = "signature_line"  # A blank line to sign on ("________")


@dataclass(frozen=True)
class Block:
    """One renderable unit of a parsed document.

    Attributes:
        type: The kind of block.
        text: Content without its list/section marker.
        marker: Section/list marker such as "1.", "1.1" or "(a)" ("" if none).
        level: Nesting depth for list items (0 = top level).
        section: Text of the heading this block belongs to ("" before the first heading).
        space_before: False when the line directly followed the previous line
            (no blank line between) - renderers keep such lines visually tight.
    """

    type: BlockType
    text: str = ""
    marker: str = ""
    level: int = 0
    section: str = ""
    space_before: bool = True

    @property
    def display_text(self) -> str:
        """Marker and text combined, e.g. "1. SERVICES"."""
        return f"{self.marker} {self.text}".strip() if self.marker else self.text


@dataclass(frozen=True)
class ParsedDocument:
    """A document split into a title and an ordered list of body blocks."""

    title: str
    blocks: list[Block] = field(default_factory=list)
    has_explicit_title: bool = False


_SIGNATURE_RE = re.compile(r"^[_\s]*_{5,}[_\s]*$")
_CANON_BULLET_RE = re.compile(rf"^(?P<indent>\s*)[{re.escape(_BULLET_CHARS)}]\s+(?P<text>\S.*)$")
_CLAUSE_RE = re.compile(r"^(?P<marker>\d{1,2}(?:\.\d{1,2}){1,3}\.?)\s+(?P<text>\S.*)$")
_SECTION_RE = re.compile(r"^(?P<marker>\d{1,2}[.)])\s+(?P<text>\S.*)$")
_ROMAN_SECTION_RE = re.compile(r"^(?P<marker>[IVXLC]{1,6}\.)\s+(?P<text>\S.*)$")
_SUBITEM_RE = re.compile(
    r"^(?P<marker>\((?:[a-zA-Z]|[ivxlcIVXLC]{1,6}|\d{1,2})\)|[a-zA-Z][.)]|[ivx]{2,5}[.)])\s+(?P<text>\S.*)$"
)
_ARTICLE_RE = re.compile(
    r"^(?P<marker>(?:ARTICLE|SECTION|CLAUSE|PART|SCHEDULE|ANNEX|EXHIBIT|APPENDIX)\s+[0-9IVXLC]{1,6}[.:]?)"
    r"(?:\s*[-\u2013\u2014:.]\s*|\s+)?(?P<text>.*)$"
)
_PLACEHOLDER_RE = re.compile(r"\[([^\[\]\n]{2,80})\]")
_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
    "or", "per", "the", "to", "under", "upon", "via", "with", "vs", "&",
}
_LEAD_RE = re.compile(
    r"^(?P<lead>(?:[A-Z][A-Z'\-]+[,:]?\s+){0,5}[A-Z][A-Z'\-]+[,:]?)(?=\s+[a-z(\"'])"
)


def _letters_outside_brackets(text: str) -> str:
    return "".join(ch for ch in _PLACEHOLDER_RE.sub("", text) if ch.isalpha())


def _is_upper_text(text: str) -> bool:
    letters = _letters_outside_brackets(text)
    return len(letters) >= 2 and letters == letters.upper()


def _is_title_case(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", _PLACEHOLDER_RE.sub("", text))
    if not words:
        return False
    significant = [w for w in words if w.lower() not in _SMALL_WORDS]
    return bool(significant) and all(w[0].isupper() for w in significant)


def _is_numbered_heading_text(text: str) -> bool:
    """Decide whether the text after a "1." marker is a heading or a list item."""
    candidate = text.strip().rstrip(":").strip()
    if not candidate or len(candidate) > 90 or candidate[-1] in ".;,":
        return False
    if _is_upper_text(candidate):
        return True
    return len(candidate) <= 60 and len(candidate.split()) <= 8 and _is_title_case(candidate)


def _is_caps_heading(text: str) -> bool:
    if len(text) > 100 or len(text.split()) > 14 or text[-1] in ";,":
        return False
    return _is_upper_text(text) and len(_letters_outside_brackets(text)) >= 3


def _is_label(text: str) -> bool:
    if not text.endswith(":") or len(text) > 60 or len(text.split()) > 9:
        return False
    body = text[:-1]
    return bool(body.strip()) and not re.search(r"[.;!?]\s", body) and bool(re.search(r"[A-Za-z]", body))


def _classify(line: str) -> Block:
    """Classify one normalised, non-blank line (section/space set by caller)."""
    stripped = line.strip()
    indent = line[: len(line) - len(line.lstrip())]
    indent_level = _indent_level(indent)

    if _SIGNATURE_RE.match(stripped):
        return Block(BlockType.SIGNATURE_LINE)

    m = _CANON_BULLET_RE.match(line)
    if m and not re.fullmatch(r"[-*_\s]+", stripped):
        return Block(BlockType.BULLET, m.group("text").strip(), level=_indent_level(m.group("indent")))

    m = _ARTICLE_RE.match(stripped)
    if m and (not m.group("text") or _is_upper_text(m.group("text")) or _is_title_case(m.group("text"))):
        return Block(BlockType.HEADING, m.group("text").strip().rstrip(":.").strip(), marker=m.group("marker").rstrip(":"))

    m = _CLAUSE_RE.match(stripped)
    if m:
        depth = m.group("marker").rstrip(".").count(".")
        text = m.group("text").strip()
        if depth == 1 and _is_upper_text(text) and _is_caps_heading(text):
            # e.g. "1.1 DEFINITIONS" used as a sub-heading
            return Block(BlockType.SUBHEADING, text.rstrip(":").strip(), marker=m.group("marker"))
        return Block(BlockType.NUMBERED, text, marker=m.group("marker"), level=max(depth - 1, indent_level))

    for pattern in (_SECTION_RE, _ROMAN_SECTION_RE):
        m = pattern.match(stripped)
        if m:
            text = m.group("text").strip()
            if _is_numbered_heading_text(text) and indent_level == 0:
                return Block(BlockType.HEADING, text.rstrip(":").rstrip(".").strip(), marker=m.group("marker"))
            return Block(BlockType.NUMBERED, text, marker=m.group("marker"), level=indent_level)

    m = _SUBITEM_RE.match(stripped)
    if m:
        marker = m.group("marker")
        level = 0 if re.fullmatch(r"[A-Z][.)]", marker) else 1
        return Block(BlockType.NUMBERED, m.group("text").strip(), marker=marker, level=max(level, indent_level))

    if _is_caps_heading(stripped):
        if stripped.endswith(":"):
            return Block(BlockType.SUBHEADING, stripped)
        return Block(BlockType.HEADING, stripped.rstrip(".").strip())

    if _is_label(stripped):
        return Block(BlockType.SUBHEADING, stripped)

    return Block(BlockType.PARAGRAPH, stripped)


def _is_title_line(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 120 or text[-1] in ".;,:" or _SIGNATURE_RE.match(text):
        return False
    if _CANON_BULLET_RE.match(text) or _CLAUSE_RE.match(text) or _SECTION_RE.match(text):
        return False
    return _is_upper_text(text) or (len(text.split()) <= 10 and _is_title_case(text))


def parse_document(text: str | None, fallback_title: str = "Legal Document") -> ParsedDocument:
    """Parse document text into a title and typed body blocks.

    The first line becomes the title when it looks like one (ALL CAPS or a short
    Title Case line); otherwise ``fallback_title`` (usually the document type)
    is used and every line is kept as body content. No non-blank line of
    content is ever dropped.
    """
    normalized = normalize_document_text(text)
    lines = normalized.split("\n") if normalized else []

    title = ""
    start = 0
    if lines and _is_title_line(lines[0]):
        title = lines[0].strip()
        start = 1

    blocks: list[Block] = []
    section = ""
    previous_blank = True
    for line in lines[start:]:
        if not line.strip():
            previous_blank = True
            continue
        block = _classify(line)
        if block.type is BlockType.HEADING:
            section = block.text.upper()
        blocks.append(
            Block(
                type=block.type,
                text=block.text,
                marker=block.marker,
                level=block.level,
                section=section,
                space_before=previous_blank or not blocks,
            )
        )
        previous_blank = False

    fallback = (fallback_title or "Legal Document").strip()
    return ParsedDocument(title=title or fallback, blocks=blocks, has_explicit_title=bool(title))


# ---------------------------------------------------------------------------
# Inline helpers shared by renderers
# ---------------------------------------------------------------------------


def split_lead(text: str) -> tuple[str, str]:
    """Split a leading ALL-CAPS legal phrase from the rest of a paragraph.

    >>> split_lead("WHEREAS, the Client wishes to engage the Provider")
    ('WHEREAS,', ' the Client wishes to engage the Provider')

    Renderers show the lead in bold. Returns ("", text) when there is no lead.
    """
    m = _LEAD_RE.match(text)
    if not m or len(_letters_outside_brackets(m.group("lead"))) < 4:
        return "", text
    lead = m.group("lead")
    return lead, text[len(lead):]


def split_placeholders(text: str) -> list[tuple[str, bool]]:
    """Split text into (segment, is_placeholder) pairs for highlighting "[...]"."""
    parts: list[tuple[str, bool]] = []
    last = 0
    for m in _PLACEHOLDER_RE.finditer(text):
        if not re.search(r"[A-Za-z]", m.group(1)):
            continue
        if m.start() > last:
            parts.append((text[last:m.start()], False))
        parts.append((m.group(0), True))
        last = m.end()
    if last < len(text):
        parts.append((text[last:], False))
    return parts


def find_placeholders(text: str | None) -> list[str]:
    """Return unique "[PLACEHOLDER]" tokens in order of first appearance."""
    seen: dict[str, None] = {}
    for m in _PLACEHOLDER_RE.finditer(text or ""):
        if re.search(r"[A-Za-z]", m.group(1)):
            seen.setdefault(m.group(0), None)
    return list(seen)


def is_terms_section(heading: str) -> bool:
    """True for headings such as "TERMS AND CONDITIONS" or "KEY TERMS"."""
    return bool(re.search(r"\bTERMS\b", heading or "", re.IGNORECASE))


def word_count(text: str | None) -> int:
    return len(re.findall(r"\S+", text or ""))


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

_TERM_MARKER_RE = re.compile(rf"^(?:[{re.escape(_BULLET_CHARS)}]|\(?\d{{1,3}}[.)]|\(?[a-zA-Z][.)])\s+")


def parse_terms(raw: str | None) -> list[str]:
    """Split user-entered terms into a clean list.

    Terms may be entered one per line, separated by semicolons, or both. List
    markers ("-", "•", "1.", "a)") are removed and duplicates are dropped.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[;\n]+", sanitize_text(raw)):
        term = strip_inline_markdown(_TERM_MARKER_RE.sub("", part.strip())).strip().rstrip(",").strip()
        term = re.sub(r"\s{2,}", " ", term)
        if not term or not re.search(r"[A-Za-z0-9]", term):
            continue
        key = term.casefold().rstrip(".")
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y", "%d %B, %Y", "%d %b, %Y",
)
MIN_YEAR, MAX_YEAR = 1900, 2200


def parse_effective_date(value: str | date | datetime) -> date:
    """Parse an effective date.

    Accepts ISO dates (``2025-04-15``) and written dates such as
    ``April 15, 2025``, ``15 April 2025`` or ``April 15th, 2025``. Purely numeric
    formats like ``10/04/2025`` are rejected because they are ambiguous
    (day/month order differs by country).

    Raises:
        ValueError: with a user-friendly message if the date is invalid.
    """
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = re.sub(r"\s+", " ", sanitize_text(value)).strip()
        if not text:
            raise ValueError("Effective date is required.")
        text = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
        text = text.replace("Sept ", "Sep ")
        parsed = None
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError(
                "Effective date is not a valid date. Use YYYY-MM-DD (for example 2025-04-15) "
                "or a written date such as April 15, 2025."
            )
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise ValueError(f"Effective date must be between the years {MIN_YEAR} and {MAX_YEAR}.")
    return parsed


def format_date_long(value: date) -> str:
    """Format a date professionally, e.g. ``April 15, 2025``."""
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def format_date_ordinal(value: date) -> str:
    """Format a date in formal legal style, e.g. ``15th day of April, 2025``."""
    day = value.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} day of {value.strftime('%B')}, {value.year}"


def build_filename(document_type: str | None, extension: str) -> str:
    """Build a safe download file name such as ``freelance_work_contract.pdf``."""
    ascii_text = unicodedata.normalize("NFKD", document_type or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:60] or "legal_document"
    return f"{slug}.{extension.lstrip('.').lower()}"
