"""LegalEase - Streamlit frontend.

Run with:

    streamlit run frontend/app.py

The UI collects the document details, asks the FastAPI backend to draft the
document with Gemini, shows a styled preview, lets the user edit the text and
downloads the *edited* version as TXT, DOCX or PDF (rendered by the backend).
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from api_client import APIError, ExportedFile, LegalEaseAPI
from styles import APP_CSS, DOCUMENT_ICON, SCALES_ICON

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
load_dotenv(PROJECT_ROOT / ".env", override=False)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").strip() or "http://localhost:8000"
BACKEND_TIMEOUT = int(os.getenv("BACKEND_TIMEOUT_SECONDS", "300") or 300)

DISCLAIMER = (
    "LegalEase provides AI-generated legal document drafts for informational and drafting purposes only. "
    "It does not provide legal advice, and generated documents should be reviewed by a qualified legal "
    "professional before use."
)
MAX_LOGO_BYTES = 2 * 1024 * 1024
EXPORT_FORMATS = (
    ("txt", "Download as TXT", ":material/description:", "Plain text"),
    ("docx", "Download as DOCX", ":material/article:", "Microsoft Word"),
    ("pdf", "Download as PDF", ":material/picture_as_pdf:", "Branded PDF"),
)

st.set_page_config(
    page_title="LegalEase · AI Legal Document Generator",
    page_icon=str(ASSETS_DIR / "icon.png"),
    layout="wide",
    initial_sidebar_state="auto",
)


# ---------------------------------------------------------------------------
# Backend access (cached where the data is not user-specific)
# ---------------------------------------------------------------------------


@st.cache_resource
def get_api() -> LegalEaseAPI:
    return LegalEaseAPI(BACKEND_URL, timeout=BACKEND_TIMEOUT)


@st.cache_data(ttl=10, show_spinner=False)
def fetch_health() -> dict:
    try:
        return {"ok": True, **get_api().health()}
    except APIError as exc:
        return {"ok": False, "message": exc.message}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_document_types() -> list[str]:
    try:
        return [item["label"] for item in get_api().document_types()]
    except (APIError, KeyError, TypeError):
        return []


@lru_cache(maxsize=4)
def image_data_uri(name: str) -> str:
    data = (ASSETS_DIR / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def content_key(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(repr(part).encode("utf-8", "surrogatepass"))
        digest.update(b"\x00")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

_DEFAULT_STATE = {
    "doc": None,             # metadata returned by /generate
    "original_text": "",     # the AI draft, for "reset"
    "document_text": "",     # the current (possibly edited) text - source of truth for exports
    "preview_cache": {},
    "export_cache": {},
    "paper_view": False,
}


def init_state() -> None:
    for key, value in _DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, dict) else value


def sync_editor() -> None:
    """Copy the editor widget's value into the document (called on change)."""
    st.session_state.document_text = st.session_state.editor


def reset_to_draft() -> None:
    st.session_state.document_text = st.session_state.original_text
    st.session_state.editor = st.session_state.original_text


def clear_document() -> None:
    for key, value in _DEFAULT_STATE.items():
        st.session_state[key] = value.copy() if isinstance(value, dict) else value
    st.session_state.pop("editor", None)


def is_edited() -> bool:
    return st.session_state.document_text != st.session_state.original_text


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_header() -> None:
    st.html(
        f"""
        <div class="le-hero">
          <img src="{image_data_uri('logo_light.png')}" alt="LegalEase">
          <h1>AI Legal Document Generator</h1>
          <p>Draft professional contracts, NDAs, leases and offer letters from a few structured details &mdash;
          then review, edit and export them as TXT, DOCX or PDF.</p>
        </div>
        <div class="le-disclaimer" role="note">{SCALES_ICON}<div>{html.escape(DISCLAIMER)}</div></div>
        """
    )


def render_step(number: int, title: str, subtitle: str) -> None:
    st.html(
        f'<div class="le-step"><span class="le-step-num">{number}</span><div>'
        f'<div class="le-step-title">{html.escape(title)}</div>'
        f'<div class="le-step-sub">{html.escape(subtitle)}</div></div></div>'
    )


def render_sidebar(health: dict) -> None:
    with st.sidebar:
        st.markdown("#### System status")
        if health.get("ok"):
            ai = health.get("ai", {})
            ai_line = ("ok", "Gemini configured") if ai.get("configured") else ("warn", "Gemini API key missing")
            rows = [("ok", "Backend connected"), ai_line]
            detail = f"Model: {ai.get('model', 'unknown')}"
        else:
            rows = [("bad", "Backend offline")]
            detail = f"Expected at {BACKEND_URL}"
        st.html(
            "".join(f'<div class="le-status"><span class="le-dot le-dot-{kind}"></span>{html.escape(label)}</div>'
                    for kind, label in rows)
            + f'<div class="le-side-note" style="margin-top:0.4rem">{html.escape(detail)}</div>'
        )

        st.divider()
        st.markdown("#### How it works")
        st.markdown(
            "1. Choose or type a **document type**\n"
            "2. Describe the **parties** and **key terms**\n"
            "3. **Generate** a draft with Gemini\n"
            "4. **Review and edit** the text\n"
            "5. **Download** TXT, DOCX or PDF"
        )
        st.divider()
        st.markdown("#### Privacy")
        st.html(
            '<div class="le-side-note">Documents are processed in memory and are not stored by LegalEase. '
            "Your inputs are sent to Google Gemini only to generate the draft. Avoid including information "
            "you are not permitted to share.</div>"
        )
        if st.session_state.doc:
            st.divider()
            st.button("Start a new document", icon=":material/restart_alt:", on_click=clear_document, width="stretch")


def render_backend_notice(health: dict) -> None:
    if not health.get("ok"):
        st.error(
            f"The LegalEase backend is not reachable at `{BACKEND_URL}`. Start it with "
            "`uvicorn backend.main:app --port 8000` and refresh this page.",
            icon=":material/cloud_off:",
        )
    elif not health.get("ai", {}).get("configured"):
        st.warning(
            "The backend is running, but no Gemini API key is configured. Add `GEMINI_API_KEY` to the `.env` "
            "file and restart the backend to enable document generation.",
            icon=":material/key_off:",
        )


# ---------------------------------------------------------------------------
# Input section
# ---------------------------------------------------------------------------


def render_input_form() -> None:
    render_step(1, "Document details", "Tell LegalEase what to draft")
    document_types = fetch_document_types()

    with st.form("document_form", border=False, enter_to_submit=False):
        document_type = st.selectbox(
            "Document type",
            options=document_types,
            index=None,
            placeholder="Choose a template or type your own…",
            accept_new_options=True,
            help="Pick a predefined template or type any other document type, e.g. “Freelance Work Contract”.",
        )
        parties = st.text_area(
            "Parties involved",
            placeholder="Jane Doe (Service Provider), TechNova Inc. (Client)",
            height=96,
            max_chars=2000,
            help="Names and roles of everyone involved. Separate parties with commas or new lines.",
        )
        terms = st.text_area(
            "Terms & conditions",
            placeholder=(
                "Payment to be made within 30 days of invoice\n"
                "The provider will deliver the work by May 15, 2025\n"
                "Confidentiality must be maintained at all times\n"
                "Either party may terminate with 15 days notice"
            ),
            height=168,
            max_chars=6000,
            help="Enter one term per line, or separate terms with semicolons. Each term becomes a clause.",
        )
        effective_date = st.date_input(
            "Effective date",
            value=date.today(),
            min_value=date(1900, 1, 1),
            max_value=date(2200, 12, 31),
            format="DD/MM/YYYY",
            help="The date the document takes effect. It is written out in full, e.g. “April 15, 2025”.",
        )
        submitted = st.form_submit_button(
            "Generate Document", type="primary", icon=":material/auto_awesome:", width="stretch"
        )
        if st.session_state.doc and is_edited():
            st.caption("Generating again replaces the current document, including your edits.")

    if submitted:
        handle_generate(document_type, parties, terms, effective_date)


def handle_generate(document_type: str | None, parties: str, terms: str, effective_date: date | None) -> None:
    problems = []
    if not (document_type or "").strip():
        problems.append("Choose or type a **document type**.")
    if not parties.strip():
        problems.append("Enter the **parties involved**.")
    if not terms.strip():
        problems.append("Enter at least one **term or condition**.")
    if not isinstance(effective_date, date):
        problems.append("Select a valid **effective date**.")
    if problems:
        st.error("Please complete the form:\n\n" + "\n".join(f"- {p}" for p in problems), icon=":material/error:")
        return

    try:
        with st.spinner("Drafting your document with Gemini… this usually takes 20–60 seconds.", show_time=True):
            result = get_api().generate(document_type.strip(), parties.strip(), terms.strip(), effective_date.isoformat())
    except APIError as exc:
        details = [f"- {msg}" for field, msg in exc.fields.items() if msg != exc.message]
        st.error("\n\n".join([exc.message, *(["\n".join(details)] if details else [])]), icon=":material/error:")
        return

    text = result.get("document", "")
    st.session_state.doc = {key: value for key, value in result.items() if key != "document"}
    st.session_state.original_text = text
    st.session_state.document_text = text
    st.session_state.editor = text
    st.session_state.preview_cache = {}
    st.session_state.export_cache = {}
    st.toast("Document generated successfully", icon=":material/check_circle:")


# ---------------------------------------------------------------------------
# Output section
# ---------------------------------------------------------------------------


def render_empty_state() -> None:
    st.html(
        f"""
        <div class="le-empty">
          {DOCUMENT_ICON}
          <div class="le-empty-title">Your document will appear here</div>
          <p>Fill in the details and select <strong>Generate Document</strong>. You can then preview the draft,
          edit it, and download the final version.</p>
          <ol>
            <li>Choose a document type</li>
            <li>Describe the parties and the key terms</li>
            <li>Generate, review and edit the draft</li>
            <li>Download it as TXT, DOCX or PDF</li>
          </ol>
        </div>
        """
    )


def get_preview(content: str, document_type: str) -> dict | None:
    key = content_key(document_type, content)
    cache: dict = st.session_state.preview_cache
    if key not in cache:
        try:
            cache.clear()  # only the latest preview is needed
            cache[key] = get_api().preview(content, document_type)
        except APIError as exc:
            st.error(f"Preview unavailable: {exc.message}", icon=":material/error:")
            return None
    return cache[key]


def render_document_meta(doc: dict, preview: dict | None) -> None:
    edited = is_edited()
    if edited:
        st.info("You have edited this document. Your edited version is used for every download.",
                icon=":material/edit_note:")
    else:
        st.success("Document Generated Successfully", icon=":material/check_circle:")

    title = (preview or {}).get("title") or doc.get("title") or doc.get("document_type", "Legal Document")
    words = (preview or {}).get("word_count", doc.get("word_count", 0))
    placeholders = (preview or {}).get("placeholders", doc.get("placeholders", []))
    chips = [
        f'<span class="le-chip">{html.escape(doc.get("document_type", ""))}</span>',
        f'<span class="le-chip">Effective {html.escape(doc.get("effective_date_display", ""))}</span>',
        f'<span class="le-chip">{words:,} words</span>',
    ]
    if placeholders:
        chips.append(f'<span class="le-chip le-chip-gold">{len(placeholders)} to complete</span>')
    if edited:
        chips.append('<span class="le-chip le-chip-blue">Edited</span>')
    st.html(f'<div class="le-doc-meta-title">{html.escape(title)}</div><div class="le-chips">{"".join(chips)}</div>')

    for warning in doc.get("warnings", []):
        st.warning(warning, icon=":material/warning:")
    if placeholders:
        with st.expander(f"{len(placeholders)} detail(s) still need your input", icon=":material/edit_square:"):
            st.caption("These bracketed placeholders mark information you did not provide. "
                       "Replace them in **Edit Document** before using the document.")
            items = "".join(f"<code>{html.escape(p)}</code>" for p in placeholders[:40])
            st.html(f'<div class="le-placeholder-list">{items}</div>')


def render_preview_tab(preview: dict | None) -> None:
    st.toggle("Paper view", key="paper_view", help="Show the preview as a printed page.")
    if preview:
        css_class = "le-preview le-paper" if st.session_state.paper_view else "le-preview"
        st.html(f'<div class="{css_class}" lang="en">{preview["html"]}</div>')


def render_edit_tab() -> None:
    if "editor" not in st.session_state:
        st.session_state.editor = st.session_state.document_text
    st.caption(
        "Edit the text directly. Keep headings on their own line; start bullet points with “• ”. "
        "Changes are applied when you click outside the editor or press Ctrl+Enter."
    )
    st.text_area(
        "Edit Document Below:",
        key="editor",
        on_change=sync_editor,
        height=560,
        label_visibility="collapsed",
    )
    left, right = st.columns(2)
    with left:
        st.button("Apply changes", icon=":material/check:", width="stretch",
                  help="Update the preview and downloads with your edits.")
    with right:
        st.button("Reset to AI draft", icon=":material/undo:", width="stretch",
                  on_click=reset_to_draft, disabled=not is_edited(),
                  help="Discard your edits and restore the generated draft.")


def get_logo_base64() -> tuple[str | None, str | None]:
    """Return (base64 logo or None, error message or None) from the uploader."""
    upload = st.session_state.get("logo_upload")
    if upload is None:
        return None, None
    data = upload.getvalue()
    if len(data) > MAX_LOGO_BYTES:
        return None, "The logo must be smaller than 2 MB. The LegalEase logo will be used instead."
    return base64.b64encode(data).decode(), None


def get_export(export_format: str, content: str, document_type: str,
               include_disclaimer: bool, logo_b64: str | None) -> ExportedFile | APIError:
    key = content_key(export_format, document_type, include_disclaimer, logo_b64, content)
    cache: dict = st.session_state.export_cache
    if key not in cache:
        # Drop stale versions of this format so memory holds only current files.
        for stale in [k for k, v in cache.items() if v[0] == export_format]:
            cache.pop(stale)
        try:
            result: ExportedFile | APIError = get_api().export(
                export_format, content, document_type,
                include_disclaimer=include_disclaimer, logo_base64=logo_b64,
            )
        except APIError as exc:
            result = exc
        cache[key] = (export_format, result)
    return cache[key][1]


def render_downloads(doc: dict) -> None:
    st.markdown("##### Download")
    st.caption("Every file is generated from the latest version shown above, including your edits.")

    with st.expander("Branding & export options", icon=":material/tune:"):
        st.file_uploader(
            "Company logo (optional)",
            type=["png", "jpg", "jpeg"],
            key="logo_upload",
            help="Replaces the LegalEase logo in DOCX and PDF files. PNG or JPEG, up to 2 MB.",
        )
        st.toggle("Include AI-draft disclaimer in the footer", value=True, key="include_disclaimer")

    logo_b64, logo_error = get_logo_base64()
    if logo_error:
        st.warning(logo_error, icon=":material/image_not_supported:")
    include_disclaimer = st.session_state.get("include_disclaimer", True)
    content = st.session_state.document_text
    document_type = doc.get("document_type", "Legal Document")

    columns = st.columns(len(EXPORT_FORMATS))
    with st.spinner("Preparing files…"):
        exports = {fmt: get_export(fmt, content, document_type, include_disclaimer, logo_b64)
                   for fmt, *_ in EXPORT_FORMATS}
    for column, (fmt, label, icon, caption) in zip(columns, EXPORT_FORMATS):
        with column:
            exported = exports[fmt]
            if isinstance(exported, ExportedFile):
                st.download_button(
                    label, data=exported.data, file_name=exported.filename, mime=exported.mime,
                    icon=icon, width="stretch", on_click="ignore", key=f"download_{fmt}",
                    type="primary" if fmt == "pdf" else "secondary",
                )
                st.html(f'<div class="le-download-caption">{caption}</div>')
            else:
                st.button(label, icon=icon, width="stretch", disabled=True, key=f"download_{fmt}_disabled")
                st.caption(f":red[{exported.message}]")


def render_output() -> None:
    render_step(2, "Review & export", "Preview, edit and download your document")
    doc = st.session_state.doc
    if not doc:
        render_empty_state()
        return

    content = st.session_state.document_text
    if not content.strip():
        st.warning("The document is empty. Reset to the AI draft or add content before downloading.",
                   icon=":material/warning:")
        st.button("Reset to AI draft", icon=":material/undo:", on_click=reset_to_draft)
        return

    preview = get_preview(content, doc.get("document_type", "Legal Document"))
    render_document_meta(doc, preview)
    preview_tab, edit_tab = st.tabs([":material/visibility: Preview", ":material/edit: Edit Document"])
    with preview_tab:
        render_preview_tab(preview)
    with edit_tab:
        render_edit_tab()
    st.divider()
    render_downloads(doc)


def render_footer(health: dict) -> None:
    model = health.get("ai", {}).get("model") if health.get("ok") else None
    powered = f"Powered by Google Gemini ({html.escape(model)})" if model else "Powered by Google Gemini"
    st.html(
        f'<div class="le-footer">{html.escape(DISCLAIMER)}<br>LegalEase v1.0 · {powered}</div>'
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def main() -> None:
    init_state()
    st.html(APP_CSS)
    st.logo(str(ASSETS_DIR / "logo_light.png"), size="large", icon_image=str(ASSETS_DIR / "icon.png"))
    health = fetch_health()

    render_sidebar(health)
    render_header()
    render_backend_notice(health)

    input_column, output_column = st.columns([4, 7], gap="large")
    with input_column:
        with st.container(border=True):
            render_input_form()
    with output_column:
        with st.container(border=True):
            render_output()

    render_footer(health)


main()
