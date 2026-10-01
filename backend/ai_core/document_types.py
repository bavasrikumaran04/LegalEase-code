"""Registry of supported legal document types.

Each entry carries drafting guidance that is injected into the Gemini prompt so
the structure of the generated document depends on its type. The registry is
also served to the frontend (``GET /document-types``) so the select box and the
backend never drift apart. Adding a new template is a single new entry here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentType:
    id: str
    label: str
    description: str
    guidance: str
    keywords: tuple[str, ...] = ()


_COMMON_CONTRACT_TAIL = (
    "Close with boilerplate that is appropriate for the document (for example entire "
    "agreement, amendments, severability, notices, counterparts) and a signature section."
)

DOCUMENT_TYPES: tuple[DocumentType, ...] = (
    DocumentType(
        id="employment_contract",
        label="Employment Contract",
        description="Formal agreement between an employer and an employee.",
        keywords=("employment contract", "employment agreement", "contract of employment", "employee agreement"),
        guidance=(
            "Structure as an employment agreement between an employer and an employee. Typical sections: "
            "parties, position and duties, commencement date and term (include a probation period only if "
            "provided), place of work, working hours, compensation and benefits, leave, confidentiality, "
            "intellectual property, termination and notice, and return of company property. "
            + _COMMON_CONTRACT_TAIL
        ),
    ),
    DocumentType(
        id="offer_letter",
        label="Employment Offer Letter",
        description="Letter offering a position to a candidate, with acceptance section.",
        keywords=("offer letter", "letter of offer", "job offer", "employment offer"),
        guidance=(
            "Write this as a formal business letter, not as a contract. Start with the title line, then the "
            "sender's details ([COMPANY NAME], [COMPANY ADDRESS]), the date, the recipient, a subject line and a "
            "salutation (\"Dear <candidate name>,\"). Cover the position offered, start date, compensation, "
            "benefits, conditions of the offer, and how and by when to accept. Put the offer details the user "
            "supplied in a section headed \"TERMS OF OFFER\". End with a professional closing, the signatory "
            "block for the company, and an \"ACCEPTANCE\" section where the candidate signs and dates."
        ),
    ),
    DocumentType(
        id="nda",
        label="Non-Disclosure Agreement (NDA)",
        description="Protects confidential information shared between parties.",
        keywords=("nda", "non-disclosure", "non disclosure", "nondisclosure", "confidentiality agreement"),
        guidance=(
            "Structure as a non-disclosure agreement. Make it mutual or one-way as the user's inputs indicate; if "
            "that is not clear, draft it as mutual. Typical sections: parties, purpose of disclosure, definition of "
            "Confidential Information, exclusions from confidentiality, obligations of the receiving party, "
            "permitted disclosures, term and duration of the confidentiality obligations, return or destruction "
            "of information, no licence, and remedies. " + _COMMON_CONTRACT_TAIL
        ),
    ),
    DocumentType(
        id="lease_agreement",
        label="Lease Agreement",
        description="Rental of residential or commercial property between landlord and tenant.",
        keywords=("lease", "rental agreement", "tenancy", "rent agreement"),
        guidance=(
            "Structure as a property lease between a landlord and a tenant. Typical sections: parties, premises "
            "(use [PROPERTY ADDRESS] unless provided), lease term, rent and payment, security deposit, use of the "
            "premises, utilities, maintenance and repairs, alterations, landlord's entry, subletting and "
            "assignment, termination and renewal, and surrender of the premises. " + _COMMON_CONTRACT_TAIL
        ),
    ),
    DocumentType(
        id="service_agreement",
        label="Service Agreement",
        description="Terms under which a provider delivers services to a client.",
        keywords=("service agreement", "services agreement", "service contract", "master services"),
        guidance=(
            "Structure as a services agreement between a service provider and a client. Typical sections: "
            "parties, scope of services and deliverables, term, fees and payment, client responsibilities, "
            "service standards, confidentiality, intellectual property, limitation of liability, termination, "
            "and independent contractor relationship. " + _COMMON_CONTRACT_TAIL
        ),
    ),
    DocumentType(
        id="freelance_contract",
        label="Freelance Contract",
        description="Engagement of an independent freelancer for a project.",
        keywords=("freelance", "freelancer", "independent contractor", "contractor agreement", "consulting"),
        guidance=(
            "Structure as a freelance / independent contractor agreement. Typical sections: parties, project "
            "scope and deliverables, timeline and deadlines, fees, invoicing and payment, revisions, intellectual "
            "property ownership, confidentiality, independent contractor status, termination, and "
            "non-solicitation only if requested. " + _COMMON_CONTRACT_TAIL
        ),
    ),
    DocumentType(
        id="general_agreement",
        label="General Agreement",
        description="Flexible agreement for arrangements not covered by other types.",
        keywords=("agreement",),
        guidance=(
            "Structure as a general-purpose agreement. Derive the substantive sections from the purpose and "
            "terms the user supplied; include only clauses that are relevant to them. " + _COMMON_CONTRACT_TAIL
        ),
    ),
    DocumentType(
        id="general_contract",
        label="General Contract",
        description="Flexible contract with obligations and consideration.",
        keywords=("contract",),
        guidance=(
            "Structure as a general-purpose contract setting out each party's obligations and the consideration "
            "exchanged. Derive the substantive sections from the terms the user supplied; include only clauses "
            "that are relevant to them. " + _COMMON_CONTRACT_TAIL
        ),
    ),
)

CUSTOM_GUIDANCE = (
    "This is a custom document type. Use the structure, headings and clauses that are customary for a "
    "document of this type, and include only clauses that are relevant to the user's inputs. If the document "
    "is a letter or notice rather than an agreement, use letter format instead of contract format."
)

_BY_LABEL = {dt.label.casefold(): dt for dt in DOCUMENT_TYPES}
_BY_ID = {dt.id: dt for dt in DOCUMENT_TYPES}


def resolve_document_type(name: str) -> DocumentType | None:
    """Find the best matching template for a (possibly custom) document type name.

    Exact labels/ids match first; otherwise the most specific keyword contained
    in the name wins (e.g. "Freelance Work Contract" -> Freelance Contract).
    Returns ``None`` when nothing matches, meaning generic guidance applies.
    """
    key = re.sub(r"\s+", " ", (name or "").strip()).casefold()
    if not key:
        return None
    if key in _BY_LABEL:
        return _BY_LABEL[key]
    if key.replace(" ", "_") in _BY_ID:
        return _BY_ID[key.replace(" ", "_")]

    best: tuple[int, DocumentType] | None = None
    for dt in DOCUMENT_TYPES:
        for keyword in dt.keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", key):
                score = len(keyword)
                if best is None or score > best[0]:
                    best = (score, dt)
    return best[1] if best else None


def guidance_for(name: str) -> str:
    matched = resolve_document_type(name)
    return matched.guidance if matched else CUSTOM_GUIDANCE
