<p align="center">
  <img src="assets/logo.png" alt="LegalEase" width="320">
</p>

<h1 align="center">LegalEase — AI-Powered Legal Document Generator</h1>

<p align="center">
  Generate professional, editable legal document drafts from structured inputs with Google Gemini,
  then export them as branded <b>TXT</b>, <b>DOCX</b> and <b>PDF</b> files.
</p>

---

> **Legal disclaimer** — LegalEase provides AI-generated legal document drafts for informational and
> drafting purposes only. It does not provide legal advice, and generated documents should be reviewed by a
> qualified legal professional before use.

## 1. Project description

LegalEase helps entrepreneurs, professionals and individuals produce well-structured first drafts of common
legal documents — employment contracts, offer letters, NDAs, lease agreements, service agreements, freelance
contracts and more. The user supplies the document type, the parties, the key terms and the effective date;
LegalEase asks **Gemini 3.8 Flash** to draft a document with a structure appropriate to that type, shows a styled
preview, lets the user edit the text, and exports the *edited* version as a professionally formatted file with
the LegalEase (or the user's own) logo, running headers, footers and page numbers.

The AI is instructed never to invent facts it was not given (names, addresses, amounts, dates, jurisdictions,
legal citations, signatures…). Missing details become clearly marked placeholders such as `[ADDRESS]`, which the
UI highlights so they can be completed before use.

## 2. Features

| Area | What you get |
| --- | --- |
| Inputs | Document-type select box with 8 templates **plus custom types**, free-text parties, multi-line terms (one per line *or* semicolon-separated), calendar date picker |
| AI drafting | Gemini 3.8 Flash via the official `google-genai` SDK, type-specific drafting guidance, strict no-fabrication rules, placeholder policy, prompt-injection hardening |
| Preview | Dark legal-document preview card (as in the specification) with an optional "paper" view, bold legal lead-ins (WHEREAS, NOW, THEREFORE…), highlighted placeholders, no raw Markdown |
| Editing | Full-text editor; edits are never overwritten automatically and become the single source of truth for every download; one-click "Reset to AI draft" |
| TXT export | Clean, wrapped plain text with title, hanging-indent lists and optional disclaimer |
| DOCX export | python-docx: logo on page 1, Times New Roman, 1" margins, styled headings, real Word bullets, **terms table**, signature lines, running header, footer with disclaimer and `Page X of Y` fields |
| PDF export | fpdf2: logo and footer on **every** page, embedded Unicode serif font, justified body, bullet-style terms, headings kept with their text, signature blocks kept together, `Page X of Y` |
| Branding | Generated LegalEase logo set; optional **custom company logo** upload (validated and re-encoded server-side) for DOCX/PDF |
| Robustness | Friendly messages for every failure (missing/invalid key, rate limit, timeout, network, blocked content, empty output, invalid input, export failure); automatic retries for transient Gemini errors |
| Security | Key only in backend env vars, strict input validation, escaped HTML, no document storage or logging, `Cache-Control: no-store`, configurable CORS |

## 3. Architecture

```
┌────────────────────┐   HTTP/JSON   ┌──────────────────────────┐   google-genai   ┌──────────────────┐
│ Streamlit frontend │ ────────────▶ │ FastAPI backend          │ ───────────────▶ │ Gemini 3.8 Flash │
│ frontend/app.py    │ ◀──────────── │ backend/main.py          │ ◀─────────────── │ (Google AI)      │
│ • inputs           │  document /   │ • validation (Pydantic)  │   draft text     └──────────────────┘
│ • preview & editor │  HTML / files │ • ai_core/ (Gemini)      │
│ • downloads        │               │ • services/ (formatting) │
└────────────────────┘               └──────────────────────────┘
```

1. The **frontend** collects inputs and calls `POST /generate`. It never talks to Gemini and never sees the API key.
2. The **backend** validates the request, builds a structured prompt (`ai_core/prompts.py`) and calls Gemini
   (`ai_core/gemini_generator.py`) with the stateless `generate_content` API.
3. The response is cleaned into LegalEase's plain-text conventions (ALL-CAPS/numbered headings, `•` bullets,
   `1.1` clauses, `(a)` items, `____` signature lines).
4. The user edits the text; `POST /preview` renders it as safe HTML and `POST /export/{txt|docx|pdf}` renders
   the final file. All renderers share one parser (`services/document_service.py`), so formatting rules live in
   one place.

### API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Welcome message — confirms the service is running |
| `GET` | `/health` | Service status, version, AI model and whether a key is configured |
| `GET` | `/document-types` | Predefined templates for the select box |
| `POST` | `/generate` | `{document_type, parties, terms, dates}` → generated document + metadata |
| `POST` | `/preview` | `{content, document_type}` → styled, escaped HTML |
| `POST` | `/export/{txt\|docx\|pdf}` | `{content, document_type, include_disclaimer, logo_base64?}` → file download |

Interactive API docs are available at `http://localhost:8000/docs` while the backend is running. Errors always
use the shape `{"error": {"code": "...", "message": "...", "fields": {...}}}`.

## 4. Technology stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.10+ (tested on 3.14), FastAPI, Pydantic v2, Uvicorn |
| Frontend | Streamlit 1.64 |
| AI | Google Gemini **3.8 Flash** through the official **Google Gen AI SDK** (`google-genai`) |
| Documents | python-docx (DOCX), fpdf2 (PDF), plain Python (TXT), HTML/CSS (preview) |
| Images | Pillow (logo validation and generation) |
| Config / HTTP | python-dotenv, requests |
| Tests | pytest, FastAPI TestClient, pypdf |

> The specification mentions `gemini-1.5-pro` and the deprecated `google-generativeai` package. Per the updated
> requirements, LegalEase uses **`gemini-3.8-flash`** with the current `google-genai` SDK. Gemini 3 guidance is
> followed: sampling parameters (`temperature`, `top_p`, `top_k`), `thinking_budget` and `candidate_count` are not
> sent; reasoning depth is controlled with `thinking_level` (`low` / `medium` / `high`).

## 5. Project structure

```
LegalEase/
├── LegalEase.pdf                 # Project specification
├── README.md
├── requirements.txt              # Runtime dependencies (pinned)
├── requirements-dev.txt          # + pytest, pypdf
├── .env.example                  # Documented configuration (copy to .env)
├── .gitignore                    # Ignores .env, venv, caches
├── .streamlit/config.toml        # Theme, upload limit, telemetry off
├── Dockerfile / docker-compose.yml / Procfile / .dockerignore
│
├── backend/
│   ├── main.py                   # FastAPI app: CORS, security headers, error handlers, "/"
│   ├── routes.py                 # /health, /document-types, /generate, /preview, /export
│   ├── models.py                 # Pydantic request/response models and validation
│   ├── config.py                 # Centralised settings from environment variables
│   ├── ai_core/
│   │   ├── gemini_generator.py   # GeminiDocumentGenerator (google-genai client, error mapping)
│   │   ├── prompts.py            # System instruction + prompt builder
│   │   ├── document_types.py     # Template registry and type-specific guidance
│   │   └── exceptions.py         # User-safe AI error types
│   └── services/
│       ├── document_service.py   # sanitize_text, normalisation, parser, terms/date helpers
│       ├── html_preview.py       # format_html_preview
│       ├── txt_generator.py      # format_txt
│       ├── docx_generator.py     # format_docx
│       ├── pdf_generator.py      # format_pdf
│       ├── branding.py           # Logo handling, brand colours, disclaimer text
│       └── export_service.py     # Single entry point for file exports
│
├── frontend/
│   ├── app.py                    # Streamlit UI
│   ├── api_client.py             # HTTP client for the backend
│   └── styles.py                 # UI and preview CSS
│
├── assets/                       # logo.png, logo_light.png, icon.png
├── scripts/generate_logo.py      # Regenerates the brand assets
└── tests/                        # pytest suite (Gemini is always mocked)
```

## 6. Installation

Prerequisites: **Python 3.10+** and pip. Commands below are for **Windows PowerShell**; macOS/Linux equivalents
are shown where they differ.

```powershell
git clone <your-repo-url> LegalEase
cd LegalEase
```

## 7. Virtual environment setup

```powershell
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks the activation script, run once:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

## 8. Environment variables

Copy the template and fill in your key:

```powershell
Copy-Item .env.example .env      # macOS/Linux: cp .env.example .env
```

| Variable | Default | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | **Required** for generation. Backend only — never exposed to the frontend |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model ID. Change here to switch models — no code changes needed |
| `GEMINI_THINKING_LEVEL` | `medium` | `low`, `medium` or `high` |
| `GEMINI_MAX_OUTPUT_TOKENS` | `16384` | Cap on thinking + output tokens (1024–65536) |
| `GEMINI_TIMEOUT_SECONDS` | `90` | Per-request timeout |
| `GEMINI_MAX_RETRIES` | `2` | Automatic retries for 408/429/5xx and transient network errors |
| `BACKEND_URL` | `http://localhost:8000` | Where the frontend reaches the backend |
| `BACKEND_TIMEOUT_SECONDS` | `300` | How long the frontend waits for generation |
| `CORS_ORIGINS` | `http://localhost:8501,http://127.0.0.1:8501` | Comma-separated browser origins allowed to call the API |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DOCUMENT_PAGE_SIZE` | `A4` | `A4` or `LETTER` for DOCX/PDF exports |

`.env` is listed in `.gitignore` and must never be committed.

## 9. Gemini API setup

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and sign in.
2. Create an API key.
3. Paste it into `.env` as `GEMINI_API_KEY=...`.
4. Restart the backend. The sidebar in the app (and `GET /health`) shows **Gemini configured** when the key is loaded.

Without a key the application still starts: the UI shows a clear warning and `/generate` returns a friendly
`503 ai_not_configured` error.

## 10. Running the backend

```powershell
venv\Scripts\activate
uvicorn backend.main:app --reload --port 8000
```

Check it: open `http://localhost:8000/` (welcome message), `http://localhost:8000/health` or the API docs at
`http://localhost:8000/docs`.

> Port already in use? Start the backend on another port (e.g. `--port 8010`) and set `BACKEND_URL=http://localhost:8010` in `.env`.

## 11. Running the frontend

In a second terminal:

```powershell
venv\Scripts\activate
streamlit run frontend/app.py
```

Open `http://localhost:8501`, then:

1. Choose a document type (or type your own, e.g. *Freelance Work Contract*).
2. Enter the parties, e.g. `Jane Doe (Service Provider), TechNova Inc. (Client)`.
3. Enter the terms — one per line or separated by semicolons.
4. Pick the effective date and click **Generate Document**.
5. Review the preview, switch to **Edit Document** to change anything, and fill in highlighted placeholders.
6. Optionally upload your company logo under **Branding & export options**.
7. Click **Download as TXT / DOCX / PDF** — every file contains your edited version.

## 12. Testing

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

The suite covers the API (health, validation, missing/empty fields, invalid types and dates, every AI error
mapping, CORS and security headers), the Gemini integration (request configuration, prompt content, response
cleaning, SDK error translation), the text parser and all three exporters (valid files, edited content present,
footers/page numbers, terms table, logo, disclaimer toggle, page size, font fallback). **Gemini is always
mocked — no API key or network access is required.**

## 13. Export functionality

| Format | Details |
| --- | --- |
| **TXT** | UTF-8 plain text wrapped at 88 columns; title underlined; list items with hanging indents; optional disclaimer at the end |
| **DOCX** | A4/Letter, 1" margins, Times New Roman 12 pt; logo and title on page 1; running header with the document title on later pages; navy headings kept with their text; justified paragraphs; real Word bullet styles; clause numbers with hanging indents; the *Terms and Conditions* section rendered as a numbered table with a repeating header row; placeholders highlighted for completion; signature lines; footer with optional disclaimer and live `Page X of Y` fields; document properties set |
| **PDF** | A4/Letter; logo header and footer on every page; embedded Unicode serif font (Times New Roman on Windows, Liberation/DejaVu Serif on Linux, with a safe built-in fallback); justified body; bold legal lead-ins; bullet-style terms; long words wrap inside margins; headings never stranded at page bottom; signature blocks kept together; `Page X of Y`; metadata set |

File names are derived from the document type, e.g. `freelance_work_contract.pdf`.

## 14. Security notes

- The Gemini API key is read from environment variables by the backend only; it is excluded from `repr()`,
  logs and every API response. The frontend has no access to it.
- All request bodies are validated with Pydantic: unknown fields are rejected, lengths are limited, the date is
  parsed strictly (ambiguous formats such as `10/04/2025` are refused) and terms must contain real content.
- User-supplied text is placed in delimited data blocks in the prompt, and the model is instructed not to follow
  instructions found inside them.
- Preview HTML is built by the backend with every piece of text escaped, so AI output or edits cannot inject markup.
- Uploaded logos are size-limited, verified with Pillow and re-encoded as PNG before being embedded.
- Documents are processed in memory only — nothing is written to disk or a database, and document text is never
  logged (logs contain only metadata such as type, term count and timings).
- API responses carry `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
  `Referrer-Policy: no-referrer`; CORS is restricted to the origins in `CORS_ORIGINS`.
- Streamlit usage statistics are disabled and error details are hidden from end users.
- Generation uses the stateless `generate_content` API, so no conversation state is stored by the AI provider on
  LegalEase's behalf. Inputs are still sent to Google to produce the draft — review Google's data-use terms for
  your API tier before processing confidential information.

## 15. Legal disclaimer

LegalEase provides AI-generated legal document drafts for informational and drafting purposes only. It does not
provide legal advice, and generated documents should be reviewed by a qualified legal professional before use.
LegalEase does not guarantee that any generated document is complete, accurate, legally valid or enforceable in
any jurisdiction, and it is not a substitute for a lawyer. The disclaimer is shown in the app and, by default,
in the footer of exported DOCX/PDF files (it can be switched off under *Branding & export options*).

## 16. Deployment guidance

LegalEase is two processes — the FastAPI backend and the Streamlit frontend — configured through environment
variables.

**Docker (both services):**

```powershell
Copy-Item .env.example .env   # add GEMINI_API_KEY
docker compose up --build
```

The compose file builds one image and runs the backend on port 8000 and the frontend on port 8501 (with
`BACKEND_URL=http://backend:8000`). The image installs Liberation fonts so PDFs embed a Times-compatible serif font.

**Platform-as-a-service:**

- *Backend* (Render, Railway, Fly.io, a VPS…): install `requirements.txt` and start with
  `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` (see `Procfile`). Set `GEMINI_API_KEY`, `GEMINI_MODEL`
  and `CORS_ORIGINS` (your frontend's URL) in the platform's secret settings.
- *Frontend* (Streamlit Community Cloud or the same platform): entry point `frontend/app.py`; set `BACKEND_URL`
  to the public backend URL. The frontend needs no Gemini key.
- Serve both over HTTPS in production, and keep `LOG_LEVEL=INFO` or higher.

## 17. Design decisions and assumptions

Where the specification was ambiguous, the simplest implementation consistent with it was chosen:

- **Model/SDK** — `gemini-3.8-flash` through `google-genai` `models.generate_content` (stateless). Google also
  offers the newer Interactions API, but it stores interaction state server-side by default; for sensitive legal
  inputs the stateless endpoint is the more conservative choice. The generator class isolates this, so switching
  APIs or models is a local change.
- **Rendering in the backend** — the specification calls `format_docx`/`format_pdf` from the Streamlit script;
  here all rendering lives in backend services exposed through `/preview` and `/export`, so the frontend stays a
  thin client and both parts can be deployed separately.
- **Terms table vs. bullets** — the DOCX renders the *Terms and Conditions* section as a table ("terms as table")
  while the PDF keeps "bullet-style terms", exactly as the specification describes each format. Both are derived
  from the *edited* document text, so edits are always reflected.
- **Governing law** — included only when the user supplies a jurisdiction; otherwise omitted rather than invented.
- **Dates** — the UI uses a date picker; the API accepts ISO (`2025-04-15`) or written dates (`April 15, 2025`) and
  rejects ambiguous numeric formats. Documents show the date written out (`April 15, 2025`).
- **Footer** — the sample footer in the specification lists fictional company contact details; LegalEase uses the
  product name, the AI-draft disclaimer and page numbers instead, to avoid fabricated information.
- **Preview theme** — the dark preview card follows the specification; a "paper view" toggle shows a print-like page.

## Future development

The architecture leaves room for: additional templates (one registry entry each), document analysis and
summarisation, clause explanations, multilingual drafting, saved documents and user accounts, legal knowledge
retrieval (RAG), template management and document comparison. None of these are part of the current MVP.
