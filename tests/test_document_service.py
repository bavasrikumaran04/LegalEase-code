"""Tests for the shared text pipeline and the HTML/TXT renderers built on it.

Covers character sanitisation, Markdown normalisation, block parsing, the
input helpers (terms, dates, placeholders, file names) and the finished
HTML preview and plain-text renderers.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

import pytest

from backend.services.branding import DISCLAIMER_TEXT
from backend.services.document_service import (
    Block,
    BlockType,
    build_filename,
    find_placeholders,
    format_date_long,
    format_date_ordinal,
    is_terms_section,
    normalize_document_text,
    parse_document,
    parse_effective_date,
    parse_terms,
    sanitize_text,
    split_lead,
    split_placeholders,
    word_count,
)
from backend.services.html_preview import format_html_preview
from backend.services.txt_generator import LINE_WIDTH, format_txt

MARKDOWN_TEXT = """\
## Non-Disclosure Agreement

**This Agreement** is made on April 10, 2025 between \u201cAlice Smith\u201d and XYZ Realty \u2014 a company at [ADDRESS].

**Between:**

Alice Smith (Disclosing Party) and XYZ Realty (Receiving Party)

### 1. Purpose
The parties wish to explore a business opportunity (the \u201cPurpose\u201d).

**2. Confidential Information.** Includes all technical and business information\u2026

* Item one with **bold** and *italic*
* Item two with a very long URL https://example.com/a/very/long/path/that/keeps/going/and/going/without/any/spaces
    * Nested item
| Term | Value |
|---|---|
| Duration | [NUMBER] years |
| Fee | ₹50,000 / €600 |

---
Signature: ____________________   Date: ____________
"""


def words(text: str) -> Counter[str]:
    """Multiset of the alphanumeric words in ``text``."""
    return Counter(re.findall(r"[A-Za-z0-9]+", text))


def parsed_words(text: str) -> Counter[str]:
    parsed = parse_document(text)
    title = parsed.title if parsed.has_explicit_title else ""
    return words(" ".join([title, *(block.display_text for block in parsed.blocks)]))


def classify(line: str) -> Block:
    """Parse one body line (after a title, so the line itself is never taken as the title)."""
    blocks = parse_document(f"TITLE\n\n{line}").blocks
    assert len(blocks) == 1
    return blocks[0]


def flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# sanitize_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("\u201cQuoted\u201d and \u2018single\u2019", "\"Quoted\" and 'single'"),
        ("non\u00a0breaking\u202fspace\u2009here", "non breaking space here"),
        ("zero\u200bwidth\u200d\ufeffjoin\u00aders", "zerowidthjoiners"),
        ("bell\x07null\x00escape\x1bdelete\x7f", "bellnullescapedelete"),
        ("one\r\ntwo\rthree\u2028four", "one\ntwo\nthree\nfour"),
        ("tab\there", "tab    here"),
        ("wait\u2026 minus\u2212sign", "wait... minus-sign"),
    ],
    ids=["smart-quotes", "exotic-spaces", "invisible", "control", "line-endings", "tabs", "punctuation"],
)
def test_sanitize_text_normalises_characters(raw: str, expected: str) -> None:
    assert sanitize_text(raw) == expected


def test_sanitize_text_preserves_legitimate_unicode() -> None:
    text = "Caf\u00e9 \u2014 ₹50,000 / €600 / £450 \u2013 na\u00efve § 4"

    assert sanitize_text(text) == text


def test_sanitize_text_composes_combining_accents() -> None:
    assert sanitize_text("Cafe\u0301") == "Caf\u00e9"


@pytest.mark.parametrize("empty", [None, ""])
def test_sanitize_text_handles_empty_input(empty: str | None) -> None:
    assert sanitize_text(empty) == ""


# ---------------------------------------------------------------------------
# normalize_document_text
# ---------------------------------------------------------------------------


def test_markdown_headings_become_caps_heading_lines() -> None:
    text = "## Non-Disclosure Agreement\n\n### 1. Purpose:\n\n#### Scope ##"

    assert normalize_document_text(text) == "NON-DISCLOSURE AGREEMENT\n\n1. PURPOSE\n\nSCOPE"


def test_inline_markdown_is_stripped() -> None:
    text = "The **Client** shall pay *promptly* by `wire transfer` via [the portal](https://pay.example/x)."

    assert normalize_document_text(text) == (
        "The Client shall pay promptly by wire transfer via the portal (https://pay.example/x)."
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [("**Confidentiality**", "CONFIDENTIALITY"), ("**Between:**", "Between:"), ("__Recitals.__", "RECITALS")],
)
def test_whole_line_bold_becomes_heading_or_label(line: str, expected: str) -> None:
    assert normalize_document_text(line) == expected


def test_bold_numbered_lead_is_split_into_heading_and_paragraph() -> None:
    text = "**2. Confidential Information.** Includes all technical information."

    assert normalize_document_text(text) == "2. CONFIDENTIAL INFORMATION\nIncludes all technical information."


@pytest.mark.parametrize("marker", ["-", "*", "+", "•", "●", "▪", "◦"])
def test_bullet_markers_become_canonical(marker: str) -> None:
    assert normalize_document_text(f"{marker} Pay each invoice on time") == "• Pay each invoice on time"


def test_nested_bullets_keep_their_indentation() -> None:
    text = "* Parent item\n    * Child item\n* Next parent"

    assert normalize_document_text(text) == "• Parent item\n  • Child item\n• Next parent"


@pytest.mark.xfail(
    reason="BUG: normalize_document_text writes a third-level bullet with 4 spaces, which "
    "_indent_level reads back as level 1, so level-2 bullets are flattened and the function "
    "is not idempotent",
    strict=True,
)
def test_third_level_bullets_survive_normalisation_and_parsing() -> None:
    text = "* One\n  * Two\n      * Three"

    once = normalize_document_text(text)

    assert normalize_document_text(once) == once
    assert [block.level for block in parse_document(f"TITLE\n\n{text}").blocks] == [0, 1, 2]


@pytest.mark.parametrize(
    "line",
    [
        "____________________________",
        "Signature: ____________________   Date: ____________",
        "Name: __________ Title: __________",
    ],
)
def test_signature_underscores_are_preserved(line: str) -> None:
    assert normalize_document_text(line) == line


def test_tables_become_bullets_and_header_row_is_dropped() -> None:
    text = (
        "| Term | Value |\n|---|---|\n| Duration | [NUMBER] years |\n| **Fee** | ₹50,000 |\n\n"
        "| Name | Role | Status |\n| :--- | :---: | ---: |\n| Jane | Provider | Signed |"
    )

    assert normalize_document_text(text) == (
        "• Duration: [NUMBER] years\n• Fee: ₹50,000\n\n• Jane; Provider; Signed"
    )


@pytest.mark.xfail(
    reason="BUG: _TABLE_SEPARATOR_RE requires two or more hyphens per cell, so a valid GFM delimiter "
    "row such as '|-|-|' is not recognised: the header row leaks and the delimiter becomes '• -: -'",
    strict=True,
)
def test_single_hyphen_table_delimiter_rows_are_recognised() -> None:
    assert normalize_document_text("| Term | Value |\n|-|-|\n| Fee | [AMOUNT] |") == "• Fee: [AMOUNT]"


def test_code_fences_rules_and_blank_runs_are_removed() -> None:
    text = "```text\nTITLE\n```\n\n\n\nBody\n---\n***\n===\nEnd\n\n"

    assert normalize_document_text(text) == "TITLE\n\nBody\nEnd"


def test_blockquote_markers_are_removed() -> None:
    assert normalize_document_text("> Quoted clause\n>\n> Second") == "Quoted clause\n\nSecond"


@pytest.mark.xfail(
    reason="BUG: '***bold italic***' is matched by neither the bold nor the italic pattern, so the "
    "asterisks survive into the document",
    strict=True,
)
def test_bold_italic_markers_are_stripped() -> None:
    assert normalize_document_text("***Important*** notice") == "Important notice"


def test_text_following_conventions_is_left_unchanged(contract_text: str) -> None:
    assert normalize_document_text(contract_text) == contract_text.strip()


@pytest.mark.parametrize(
    "text",
    [MARKDOWN_TEXT, "* A\n  * B\n* C", "# T\n\n| a | b |\n|---|---|\n| c | d |", "**1. Scope.** Text\n\n> quote"],
    ids=["markdown-sample", "nested-bullets", "table", "bold-lead-and-quote"],
)
def test_normalisation_is_idempotent(text: str) -> None:
    once = normalize_document_text(text)

    assert normalize_document_text(once) == once


def test_markdown_sample_is_fully_normalised() -> None:
    normalized = normalize_document_text(MARKDOWN_TEXT)

    assert normalized.startswith("NON-DISCLOSURE AGREEMENT\n\nThis Agreement is made on April 10, 2025")
    assert '"Alice Smith"' in normalized
    assert "• Item one with bold and italic" in normalized
    assert "  • Nested item" in normalized
    assert "• Fee: ₹50,000 / €600" in normalized
    assert normalized.endswith("Signature: ____________________   Date: ____________")
    for artefact in ("**", "##", "|", "---", "\u201c", "\u2026"):
        assert artefact not in normalized


# ---------------------------------------------------------------------------
# parse_document
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "block_type", "marker", "text", "level"),
    [
        ("1. DEFINITIONS", BlockType.HEADING, "1.", "DEFINITIONS", 0),
        ("2. Scope of Services", BlockType.HEADING, "2.", "Scope of Services", 0),
        ("RECITALS", BlockType.HEADING, "", "RECITALS", 0),
        ("ARTICLE IV - TERMINATION", BlockType.HEADING, "ARTICLE IV", "TERMINATION", 0),
        ("IV. TERMINATION", BlockType.HEADING, "IV.", "TERMINATION", 0),
        ("Between:", BlockType.SUBHEADING, "", "Between:", 0),
        ("SERVICE PROVIDER:", BlockType.SUBHEADING, "", "SERVICE PROVIDER:", 0),
        ("1.1 DEFINITIONS", BlockType.SUBHEADING, "1.1", "DEFINITIONS", 0),
        ("The Parties agree as follows.", BlockType.PARAGRAPH, "", "The Parties agree as follows.", 0),
        ("Title: [TITLE]", BlockType.PARAGRAPH, "", "Title: [TITLE]", 0),
        ("[COMPANY NAME]", BlockType.PARAGRAPH, "", "[COMPANY NAME]", 0),
        ("• Pay each invoice on time", BlockType.BULLET, "", "Pay each invoice on time", 0),
        ("  • Nested obligation", BlockType.BULLET, "", "Nested obligation", 1),
        ("1.1 The Client shall pay.", BlockType.NUMBERED, "1.1", "The Client shall pay.", 0),
        ("2.3.1 Invoices are due monthly.", BlockType.NUMBERED, "2.3.1", "Invoices are due monthly.", 1),
        ("1. The Client shall pay in 30 days.", BlockType.NUMBERED, "1.", "The Client shall pay in 30 days.", 0),
        ("(a) the first obligation;", BlockType.NUMBERED, "(a)", "the first obligation;", 1),
        ("ii. the second obligation", BlockType.NUMBERED, "ii.", "the second obligation", 1),
        ("____________________________", BlockType.SIGNATURE_LINE, "", "", 0),
    ],
)
def test_lines_are_classified_into_block_types(
    line: str, block_type: BlockType, marker: str, text: str, level: int
) -> None:
    block = classify(line)

    assert (block.type, block.marker, block.text, block.level) == (block_type, marker, text, level)


def test_every_block_type_occurs_in_a_complete_document(contract_text: str) -> None:
    assert {block.type for block in parse_document(contract_text).blocks} == set(BlockType)


def test_explicit_caps_title_is_detected(contract_text: str) -> None:
    parsed = parse_document(contract_text, "Ignored Fallback")

    assert parsed.title == "FREELANCE WORK CONTRACT"
    assert parsed.has_explicit_title is True
    assert all(block.text != "FREELANCE WORK CONTRACT" for block in parsed.blocks)


def test_short_title_case_first_line_is_a_title() -> None:
    parsed = parse_document("Non-Disclosure Agreement\n\nThe parties agree.")

    assert parsed.title == "Non-Disclosure Agreement"
    assert parsed.has_explicit_title is True


@pytest.mark.parametrize(
    "text",
    ["This Agreement is made on April 10, 2025.\n\n1. SERVICES", "1. DEFINITIONS\n\n1.1 Terms have their meaning."],
)
def test_fallback_title_is_used_and_first_line_is_kept(text: str) -> None:
    parsed = parse_document(text, "Service Agreement")

    assert parsed.title == "Service Agreement"
    assert parsed.has_explicit_title is False
    assert parsed.blocks[0].display_text == text.split("\n")[0]


@pytest.mark.parametrize("text", [None, "", "  \n\n "])
def test_empty_document_has_fallback_title_and_no_blocks(text: str | None) -> None:
    parsed = parse_document(text, "")

    assert parsed.title == "Legal Document"
    assert parsed.blocks == []


def test_blocks_record_the_section_they_belong_to(contract_text: str) -> None:
    blocks = parse_document(contract_text).blocks
    first_heading = next(index for index, block in enumerate(blocks) if block.type is BlockType.HEADING)
    bullets = [block for block in blocks if block.type is BlockType.BULLET]
    signature_lines = [block for block in blocks if block.type is BlockType.SIGNATURE_LINE]

    assert first_heading > 0
    assert all(block.section == "" for block in blocks[:first_heading])
    assert blocks[first_heading].section == "RECITALS"
    assert len(bullets) == 3
    assert {block.section for block in bullets} == {"TERMS AND CONDITIONS"}
    assert all(is_terms_section(block.section) for block in bullets)
    assert {block.section for block in signature_lines} == {"SIGNATURES"}


def test_section_names_are_uppercased() -> None:
    blocks = parse_document("TITLE\n\n2. Scope of Services\n\nThe Provider shall perform.").blocks

    assert blocks[1].section == "SCOPE OF SERVICES"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("TERMS AND CONDITIONS", True),
        ("KEY TERMS", True),
        ("TERMS OF OFFER", True),
        ("Terms & Conditions", True),
        ("TERMINATION", False),
        ("DEFINITIONS", False),
        ("", False),
    ],
)
def test_is_terms_section(heading: str, expected: bool) -> None:
    assert is_terms_section(heading) is expected


def test_space_before_marks_lines_without_a_blank_line_before_them(contract_text: str) -> None:
    blocks = parse_document(contract_text).blocks

    def starting_with(prefix: str) -> Block:
        return next(block for block in blocks if block.display_text.startswith(prefix))

    assert blocks[0].space_before is True
    assert starting_with("2.1 The Service Provider").space_before is True
    assert starting_with("(a) the Services").space_before is False
    assert starting_with("(b) the Service Provider").space_before is False
    assert starting_with("The Client shall pay each").space_before is False
    assert starting_with("Title: [TITLE]").space_before is False


def test_display_text_combines_marker_and_text() -> None:
    assert Block(BlockType.HEADING, "DEFINITIONS", marker="1.").display_text == "1. DEFINITIONS"
    assert Block(BlockType.PARAGRAPH, "Plain text.").display_text == "Plain text."


def test_no_content_is_lost_when_parsing(contract_text: str) -> None:
    assert parsed_words(contract_text) == words(contract_text)


def test_no_normalised_markdown_content_is_lost_when_parsing() -> None:
    assert parsed_words(MARKDOWN_TEXT) == words(normalize_document_text(MARKDOWN_TEXT))


def test_body_is_kept_when_title_is_a_fallback() -> None:
    text = "the parties agree that [PARTY A] pays; and\nthe fee is due monthly."

    assert parsed_words(text) == words(text)


# ---------------------------------------------------------------------------
# parse_terms
# ---------------------------------------------------------------------------


def test_parse_terms_splits_on_semicolons_and_newlines() -> None:
    assert parse_terms("Pay within 30 days; Keep secrets\nDeliver by May 1;\n\nGive 15 days notice") == [
        "Pay within 30 days",
        "Keep secrets",
        "Deliver by May 1",
        "Give 15 days notice",
    ]


def test_parse_terms_removes_list_markers() -> None:
    raw = "- First\n• Second\n* Third\n1. Fourth\n2) Fifth\n(3) Sixth\na) Seventh\nB. Eighth"

    assert parse_terms(raw) == ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"]


def test_parse_terms_drops_duplicates_ignoring_case_and_final_period() -> None:
    assert parse_terms("Pay within 30 days\npay within 30 days.\nPAY WITHIN 30 DAYS; Keep secrets") == [
        "Pay within 30 days",
        "Keep secrets",
    ]


def test_parse_terms_cleans_each_term() -> None:
    assert parse_terms("  **Payment**   within   30 days,  \n\u201cNet 30\u201d applies") == [
        "Payment within 30 days",
        '"Net 30" applies',
    ]


@pytest.mark.parametrize("raw", [None, "", ";;;", "\n \n", "- \n•\n...", "---"])
def test_parse_terms_ignores_empty_entries(raw: str | None) -> None:
    assert parse_terms(raw) == []


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-04-15", date(2025, 4, 15)),
        ("April 15, 2025", date(2025, 4, 15)),
        ("Apr 15, 2025", date(2025, 4, 15)),
        ("april 15 2025", date(2025, 4, 15)),
        ("15 April 2025", date(2025, 4, 15)),
        ("15 Apr, 2025", date(2025, 4, 15)),
        ("April 15th, 2025", date(2025, 4, 15)),
        ("1st April 2025", date(2025, 4, 1)),
        ("22nd June, 2025", date(2025, 6, 22)),
        ("Sept 3, 2025", date(2025, 9, 3)),
        ("  April   15,  2025 ", date(2025, 4, 15)),
        (date(2025, 4, 15), date(2025, 4, 15)),
        (datetime(2025, 4, 15, 9, 30), date(2025, 4, 15)),
    ],
)
def test_parse_effective_date_accepts_iso_written_and_ordinal_dates(value: str | date, expected: date) -> None:
    assert parse_effective_date(value) == expected


@pytest.mark.parametrize("value", ["10/04/2025", "04/10/2025", "15.04.2025", "2025/04/15", "20250415", "15-04-2025"])
def test_parse_effective_date_rejects_ambiguous_numeric_dates(value: str) -> None:
    with pytest.raises(ValueError, match="not a valid date"):
        parse_effective_date(value)


@pytest.mark.parametrize("value", ["2025-02-30", "2025-13-01", "April 31, 2025", "tomorrow", "Smarch 3, 2025"])
def test_parse_effective_date_rejects_invalid_dates(value: str) -> None:
    with pytest.raises(ValueError, match="not a valid date"):
        parse_effective_date(value)


@pytest.mark.parametrize("value", ["", "   "])
def test_parse_effective_date_requires_a_value(value: str) -> None:
    with pytest.raises(ValueError, match="Effective date is required."):
        parse_effective_date(value)


@pytest.mark.parametrize("value", ["1899-12-31", "2201-01-01", date(1066, 10, 14)])
def test_parse_effective_date_rejects_out_of_range_years(value: str | date) -> None:
    with pytest.raises(ValueError, match="between the years 1900 and 2200"):
        parse_effective_date(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2025, 4, 15), "April 15, 2025"),
        (date(2025, 1, 5), "January 5, 2025"),
        (date(2024, 12, 31), "December 31, 2024"),
    ],
)
def test_format_date_long(value: date, expected: str) -> None:
    assert format_date_long(value) == expected


@pytest.mark.parametrize(
    ("day", "suffix"),
    [(1, "st"), (2, "nd"), (3, "rd"), (4, "th"), (11, "th"), (12, "th"), (13, "th"),
     (21, "st"), (22, "nd"), (23, "rd"), (30, "th"), (31, "st")],
)
def test_format_date_ordinal(day: int, suffix: str) -> None:
    assert format_date_ordinal(date(2025, 1, day)) == f"{day}{suffix} day of January, 2025"


# ---------------------------------------------------------------------------
# Placeholders, leads, file names, word counts
# ---------------------------------------------------------------------------


def test_find_placeholders_returns_unique_tokens_in_order() -> None:
    text = "Pay [AMOUNT] to [PARTY NAME] at [ADDRESS]. [AMOUNT] is due. See [1] and [x]."

    assert find_placeholders(text) == ["[AMOUNT]", "[PARTY NAME]", "[ADDRESS]"]


@pytest.mark.parametrize("text", [None, "", "No placeholders here.", "Footnote [12] and [ ]"])
def test_find_placeholders_ignores_text_without_placeholders(text: str | None) -> None:
    assert find_placeholders(text) == []


def test_split_placeholders_flags_placeholder_segments() -> None:
    text = "Pay [AMOUNT] by [DATE] per clause [3]."

    parts = split_placeholders(text)

    assert parts == [
        ("Pay ", False), ("[AMOUNT]", True), (" by ", False), ("[DATE]", True), (" per clause [3].", False),
    ]
    assert "".join(segment for segment, _ in parts) == text


@pytest.mark.parametrize(
    ("text", "lead"),
    [
        ("WHEREAS, the Client wishes to engage the Provider", "WHEREAS,"),
        ("NOW, THEREFORE, in consideration of the covenants", "NOW, THEREFORE,"),
        ("IN WITNESS WHEREOF, the Parties have signed", "IN WITNESS WHEREOF,"),
        ("The Client shall pay the Fee", ""),
        ("NDA terms apply", ""),
        ("[COMPANY NAME] shall pay", ""),
    ],
)
def test_split_lead(text: str, lead: str) -> None:
    head, rest = split_lead(text)

    assert head == lead
    assert head + rest == text


@pytest.mark.parametrize(
    ("document_type", "extension", "expected"),
    [
        ("Freelance Work Contract", "pdf", "freelance_work_contract.pdf"),
        ("Non-Disclosure Agreement (NDA)", "docx", "non_disclosure_agreement_nda.docx"),
        ("Caf\u00e9 Lease / Rental", "txt", "cafe_lease_rental.txt"),
        ("../../etc/passwd", ".PDF", "etc_passwd.pdf"),
        ('Evil"; filename="x.exe', "txt", "evil_filename_x_exe.txt"),
        ("", "txt", "legal_document.txt"),
        (None, "pdf", "legal_document.pdf"),
        ("!!!", "pdf", "legal_document.pdf"),
    ],
)
def test_build_filename_produces_safe_slugs(document_type: str | None, extension: str, expected: str) -> None:
    assert build_filename(document_type, extension) == expected


def test_build_filename_limits_length() -> None:
    filename = build_filename("Very Long Document Type " * 5, "pdf")

    assert len(filename) <= 64
    assert re.fullmatch(r"[a-z0-9_]+\.pdf", filename)


@pytest.mark.xfail(
    reason="BUG: build_filename truncates the slug to 60 characters after stripping underscores, "
    "so it can end with '_' (e.g. 'aaa..._.pdf')",
    strict=True,
)
def test_build_filename_never_ends_with_an_underscore() -> None:
    filename = build_filename("A" * 59 + " Contract", "pdf")

    assert not filename.removesuffix(".pdf").endswith("_")


@pytest.mark.parametrize(
    ("text", "count"), [("", 0), (None, 0), ("One two  three\nfour", 4), ("1.1 The [PARTY] pays.", 4)]
)
def test_word_count(text: str | None, count: int) -> None:
    assert word_count(text) == count


# ---------------------------------------------------------------------------
# HTML preview
# ---------------------------------------------------------------------------


def test_html_preview_structure(contract_text: str) -> None:
    html = format_html_preview(contract_text, "Freelance Work Contract")

    assert html.startswith('<article class="le-doc">\n<h1 class="le-title">FREELANCE WORK CONTRACT</h1>')
    assert html.endswith("</article>")
    assert '<h2 class="le-heading">RECITALS</h2>' in html
    assert '<h2 class="le-heading">3. TERMS AND CONDITIONS</h2>' in html
    assert '<p class="le-subheading">Between:</p>' in html
    assert '<p class="le-paragraph"><strong>WHEREAS,</strong> the Client wishes' in html
    assert '<span class="le-marker">1.1</span>' in html
    assert '<div class="le-clause le-level-1 le-tight"><span class="le-marker">(a)</span>' in html
    assert '<ul class="le-list le-level-0">' in html
    assert html.count("<li>") == 3
    assert html.count("<ul") == html.count("</ul>") == 1
    assert html.count('<div class="le-signature-line') == 3
    assert '<mark class="le-placeholder">[ADDRESS]</mark>' in html


def test_html_preview_escapes_markup_everywhere() -> None:
    text = (
        "<b>TITLE</b>\n\n"
        '1. <SCRIPT>ALERT("X")</SCRIPT>\n\n'
        "Pay [<img src=x onerror=alert(1)>] now.\n\n"
        '• <a href="javascript:alert(1)">click</a>\n\n'
        'Text " onmouseover="steal() & more'
    )

    html = format_html_preview(text)

    for raw in ("<b>", "<SCRIPT", "<img", "<a ", '" onmouseover'):
        assert raw not in html
    assert "&lt;SCRIPT&gt;ALERT(&quot;X&quot;)&lt;/SCRIPT&gt;" in html
    assert '<mark class="le-placeholder">[&lt;img src=x onerror=alert(1)&gt;]</mark>' in html
    assert "&quot; onmouseover=&quot;steal() &amp; more" in html


def test_html_preview_escapes_fallback_title() -> None:
    html = format_html_preview("the parties agree.", "Smith & Jones <Agreement>")

    assert '<h1 class="le-title">Smith &amp; Jones &lt;Agreement&gt;</h1>' in html


def test_html_preview_opens_a_new_list_per_nesting_level() -> None:
    html = format_html_preview("TITLE\n\n• Parent\n  • Child\n• Sibling")

    assert html.count("<ul") == html.count("</ul>") == 3
    assert '<ul class="le-list le-level-1 le-tight">' in html


# ---------------------------------------------------------------------------
# Plain-text rendering
# ---------------------------------------------------------------------------


def test_txt_title_is_centred_and_underlined(contract_text: str) -> None:
    lines = format_txt(contract_text).splitlines()

    assert lines[0].strip() == "FREELANCE WORK CONTRACT"
    assert lines[0].startswith(" ")
    assert lines[1].strip() == "=" * len("FREELANCE WORK CONTRACT")
    assert lines[2] == ""


def test_txt_uses_fallback_title_in_capitals() -> None:
    assert format_txt("the parties agree.", "Service Agreement").splitlines()[0].strip() == "SERVICE AGREEMENT"


def test_txt_wraps_lines_at_88_characters(contract_text: str) -> None:
    lines = format_txt(contract_text).splitlines()

    assert LINE_WIDTH == 88
    assert max(len(line) for line in lines) <= LINE_WIDTH
    assert any(len(line) > 80 for line in lines)


def test_txt_never_breaks_long_words() -> None:
    url = "https://example.com/" + "segment/" * 15

    text = format_txt(f"TITLE\n\nSee {url} for details.", include_disclaimer=False)

    assert url in text


def test_txt_renders_lists_with_hanging_indents(contract_text: str) -> None:
    lines = format_txt(contract_text).splitlines()
    bullet = next(index for index, line in enumerate(lines) if line.startswith("  • Either Party may terminate"))
    clause = next(index for index, line in enumerate(lines) if line.startswith("1.1 "))
    sub_item = next(index for index, line in enumerate(lines) if line.startswith("    (a) "))

    assert lines[bullet + 1].startswith("    ") and lines[bullet + 1].strip()
    assert lines[clause + 1].startswith("    ") and lines[clause + 1].strip()
    assert lines[sub_item + 1].startswith(" " * 8) and lines[sub_item + 1].strip()
    assert "_" * 36 in lines


def test_txt_includes_disclaimer_when_requested(contract_text: str) -> None:
    text = format_txt(contract_text, include_disclaimer=True)

    assert DISCLAIMER_TEXT in flat(text)
    assert "-" * LINE_WIDTH in text


def test_txt_omits_disclaimer_when_disabled(contract_text: str) -> None:
    text = format_txt(contract_text, include_disclaimer=False)

    assert "legal advice" not in text
    assert "-" * LINE_WIDTH not in text


def test_txt_preserves_the_edited_wording(contract_text: str) -> None:
    edited = contract_text.replace("[AMOUNT]", "€4,500").replace("seven (7) days", "ten (10) days")

    text = format_txt(edited, include_disclaimer=False)

    assert words(text) == words(edited)
    assert "€4,500" in text
    assert "ten (10) days" in flat(text)


def test_txt_ends_with_a_single_newline(contract_text: str) -> None:
    for include_disclaimer in (True, False):
        text = format_txt(contract_text, include_disclaimer=include_disclaimer)
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
