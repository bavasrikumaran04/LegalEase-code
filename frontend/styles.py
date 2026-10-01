"""CSS for the LegalEase Streamlit frontend."""

from __future__ import annotations

import base64

GOLD = "#C9A54C"

APP_CSS = f"""
<style>
:root {{
  --le-gold: {GOLD};
  --le-surface: #111A2E;
  --le-surface-2: #0F1729;
  --le-border: #243049;
  --le-text: #E6EAF2;
  --le-muted: #9AA7BD;
}}

/* ---- Page frame ---------------------------------------------------- */
.block-container {{ max-width: 1320px; padding-top: 2.2rem; padding-bottom: 3rem; }}

/* ---- Header -------------------------------------------------------- */
.le-hero {{ text-align: center; margin: 0 auto 1.4rem; max-width: 760px; }}
.le-hero img {{ width: min(300px, 70vw); height: auto; }}
.le-hero h1 {{
  font-size: clamp(1.6rem, 2.6vw, 2.15rem); font-weight: 700; letter-spacing: -0.01em;
  margin: 0.6rem 0 0.35rem; padding: 0; color: var(--le-text);
}}
.le-hero p {{ color: var(--le-muted); font-size: 1.02rem; margin: 0; line-height: 1.55; }}

.le-disclaimer {{
  display: flex; gap: 0.75rem; align-items: flex-start; max-width: 980px; margin: 0 auto 1.8rem;
  padding: 0.8rem 1.1rem; border: 1px solid rgba(201,165,76,0.35); border-radius: 0.6rem;
  background: rgba(201,165,76,0.07); color: #E9DFC3; font-size: 0.9rem; line-height: 1.5;
}}
.le-disclaimer img {{ flex: 0 0 auto; margin-top: 0.1rem; }}

/* ---- Section headings ----------------------------------------------- */
.le-step {{ display: flex; align-items: center; gap: 0.75rem; margin: 0.1rem 0 1rem; }}
.le-step-num {{
  width: 1.9rem; height: 1.9rem; border-radius: 50%; display: inline-flex; align-items: center;
  justify-content: center; font-weight: 700; font-size: 0.95rem; color: #0B1120; background: var(--le-gold);
}}
.le-step-title {{ font-size: 1.12rem; font-weight: 650; color: var(--le-text); line-height: 1.2; }}
.le-step-sub {{ font-size: 0.86rem; color: var(--le-muted); }}

/* ---- Empty state ------------------------------------------------------ */
.le-empty {{ text-align: center; padding: 3.2rem 1.5rem 3rem; color: var(--le-muted); }}
.le-empty-title {{ color: var(--le-text); font-size: 1.15rem; font-weight: 650; margin: 1rem 0 0.4rem; }}
.le-empty p {{ max-width: 460px; margin: 0 auto 1.4rem; line-height: 1.55; }}
.le-empty ol {{
  display: inline-block; text-align: left; margin: 0; padding-left: 1.2rem; line-height: 1.9; font-size: 0.93rem;
}}

/* ---- Document meta ------------------------------------------------------ */
.le-doc-meta-title {{
  font-family: Georgia, "Times New Roman", Times, serif; font-size: 1.3rem; font-weight: 700;
  color: var(--le-text); margin: 0.2rem 0 0.55rem; letter-spacing: 0.01em;
}}
.le-chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.4rem; }}
.le-chip {{
  display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.18rem 0.65rem; border-radius: 999px;
  font-size: 0.8rem; border: 1px solid var(--le-border); color: #C9D2E3; background: #0F1729;
}}
.le-chip-gold {{ border-color: rgba(201,165,76,0.45); color: #F0D995; background: rgba(201,165,76,0.08); }}
.le-chip-blue {{ border-color: rgba(62,111,224,0.55); color: #B9CCFF; background: rgba(62,111,224,0.12); }}
.le-placeholder-list {{ display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; }}
.le-placeholder-list code {{
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.78rem; color: #F4D58D;
  background: rgba(201,165,76,0.12); border: 1px solid rgba(201,165,76,0.3); padding: 0.05rem 0.4rem; border-radius: 4px;
}}

/* ---- Legal document preview ---------------------------------------------- */
.le-preview {{
  --doc-bg: #0F172A; --doc-text: #E2E8F0; --doc-heading: #C8D6F5; --doc-title: #F3EEE2; --doc-rule: {GOLD};
  --doc-muted: #9AA7BD; --doc-mark-bg: rgba(201,165,76,0.20); --doc-mark-text: #F6DA94; --doc-line: #7C8AA5;
  background: var(--doc-bg); color: var(--doc-text); border: 1px solid var(--le-border); border-radius: 0.75rem;
  padding: 2.6rem 3.1rem; max-height: 680px; overflow-y: auto; scroll-behavior: smooth;
  font-family: Georgia, "Times New Roman", Times, serif; font-size: 1.0rem; line-height: 1.7;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
}}
.le-preview.le-paper {{
  --doc-bg: #FDFCF8; --doc-text: #1F2430; --doc-heading: #1B2A4A; --doc-title: #1B2A4A; --doc-rule: #B08A2E;
  --doc-muted: #5B6474; --doc-mark-bg: #FFF1BF; --doc-mark-text: #6B4E00; --doc-line: #3A4150;
  border-color: #E4DFD3; box-shadow: 0 10px 30px rgba(0,0,0,0.35);
}}
.le-preview::-webkit-scrollbar {{ width: 10px; }}
.le-preview::-webkit-scrollbar-thumb {{ background: #2B3753; border-radius: 10px; }}
.le-preview .le-doc {{ max-width: 760px; margin: 0 auto; }}
.le-preview h1.le-title {{
  font-family: inherit; text-align: center; text-transform: uppercase; letter-spacing: 0.08em;
  font-size: 1.32rem; font-weight: 700; color: var(--doc-title); margin: 0 0 1.4rem; padding: 0 0 0.9rem;
  border-bottom: 2px solid var(--doc-rule); line-height: 1.35;
}}
.le-preview h2.le-heading {{
  font-family: inherit; font-size: 1.0rem; font-weight: 700; letter-spacing: 0.04em; color: var(--doc-heading);
  margin: 1.7rem 0 0.4rem; padding: 0; line-height: 1.4;
}}
.le-preview .le-subheading {{ font-weight: 700; margin: 1rem 0 0; }}
.le-preview .le-paragraph {{ margin: 0.8rem 0 0; text-align: justify; hyphens: auto; }}
.le-preview .le-tight {{ margin-top: 0.15rem !important; }}
.le-preview ul.le-list {{ margin: 0.6rem 0 0 1.3rem; padding: 0; }}
.le-preview ul.le-list li {{ margin: 0.3rem 0 0; padding-left: 0.25rem; }}
.le-preview ul.le-level-1 {{ margin-left: 2.6rem; list-style-type: circle; }}
.le-preview ul.le-level-2 {{ margin-left: 3.9rem; list-style-type: square; }}
.le-preview .le-clause {{ display: flex; gap: 0.7rem; margin: 0.65rem 0 0; }}
.le-preview .le-clause.le-level-1 {{ padding-left: 2.2rem; margin-top: 0.35rem; }}
.le-preview .le-clause.le-level-2 {{ padding-left: 4.2rem; margin-top: 0.3rem; }}
.le-preview .le-marker {{ flex: 0 0 auto; min-width: 2.3rem; font-weight: 600; color: var(--doc-heading); }}
.le-preview .le-clause-text {{ flex: 1 1 auto; text-align: justify; }}
.le-preview .le-signature-line {{ width: min(280px, 70%); border-bottom: 1px solid var(--doc-line); margin-top: 2.4rem; }}
.le-preview mark.le-placeholder {{
  background: var(--doc-mark-bg); color: var(--doc-mark-text); padding: 0 0.22em; border-radius: 3px; font-weight: 600;
}}
.le-preview strong {{ font-weight: 700; }}

/* ---- Downloads ------------------------------------------------------------ */
.le-download-caption {{ color: var(--le-muted); font-size: 0.8rem; text-align: center; margin-top: 0.25rem; }}

/* ---- Sidebar ---------------------------------------------------------------- */
.le-status {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; margin: 0.25rem 0; }}
.le-dot {{ width: 0.55rem; height: 0.55rem; border-radius: 50%; display: inline-block; }}
.le-dot-ok {{ background: #3FB27F; box-shadow: 0 0 0 3px rgba(63,178,127,0.18); }}
.le-dot-warn {{ background: #E3A83B; box-shadow: 0 0 0 3px rgba(227,168,59,0.18); }}
.le-dot-bad {{ background: #E5534B; box-shadow: 0 0 0 3px rgba(229,83,75,0.18); }}
.le-side-note {{ color: var(--le-muted); font-size: 0.84rem; line-height: 1.55; }}

/* ---- Footer ------------------------------------------------------------------- */
.le-footer {{
  margin-top: 2.5rem; padding-top: 1.2rem; border-top: 1px solid var(--le-border); text-align: center;
  color: var(--le-muted); font-size: 0.82rem; line-height: 1.6;
}}

@media (max-width: 760px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; padding-top: 1.2rem; }}
  .le-preview {{ padding: 1.5rem 1.2rem; max-height: 560px; font-size: 0.95rem; }}
  .le-preview .le-clause.le-level-1 {{ padding-left: 1rem; }}
}}
</style>
"""

# Inline SVG is stripped by st.html's sanitiser, so icons are embedded as data-URI images.
_SCALES_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#C9A54C" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v18"/><path d="M7 21h10"/>'
    '<path d="M4 7h16"/><path d="M4 7l-3 7a3.5 3.5 0 0 0 6 0z"/><path d="M20 7l-3 7a3.5 3.5 0 0 0 6 0z"/></svg>'
)

_DOCUMENT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="58" height="58" viewBox="0 0 24 24" fill="none" stroke="#C9A54C" stroke-width="1.3" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10'
    'a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h6"/><path d="M9 9h2"/></svg>'
)


def _svg_img(svg: str, size: int, alt: str = "") -> str:
    data = base64.b64encode(svg.encode("utf-8")).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" width="{size}" height="{size}" alt="{alt}">'


SCALES_ICON = _svg_img(_SCALES_SVG, 20)
DOCUMENT_ICON = _svg_img(_DOCUMENT_SVG, 58)
