"""Controlled vocabulary and title-based tagging for GST documents."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

LegalHierarchy = Literal["act", "rule", "circular", "notification", "order", "rate_notification"]

GST_ENTITY_CODES = [
    "Registered Taxpayer",
    "Composition Dealer",
    "Input Service Distributor",
    "E-commerce Operator",
    "TDS/TCS Deductor",
    "SEZ Unit / Developer",
    "Refund Claimant",
    "General",
]

GST_ENTITY_LABELS: dict[str, str] = {
    "Registered Taxpayer": "Normal registered taxpayer (CGST/SGST/IGST)",
    "Composition Dealer": "Composition scheme dealer",
    "Input Service Distributor": "Input Service Distributor (ISD)",
    "E-commerce Operator": "E-commerce operator (TCS/TDS)",
    "TDS/TCS Deductor": "TDS/TCS deductor or collector",
    "SEZ Unit / Developer": "SEZ unit or developer",
    "Refund Claimant": "Refund / export / inverted duty claimant",
    "General": "General / cross-cutting",
}

GST_TOPICS = [
    "Registration",
    "Returns (GSTR-1 / 3B / 9 / 9C)",
    "Input Tax Credit",
    "Refunds",
    "E-invoicing / E-way Bill",
    "Place of Supply",
    "Rate / Classification (HSN/SAC)",
    "Reverse Charge",
    "Composition Scheme",
    "Audit / Assessment / Adjudication",
    "Penalties / Prosecution",
    "SEZ / Export / Zero-rated",
    "Invoice / Documentary Requirements",
    "Transitional / Amnesty (Section 128A)",
]

RELATIONSHIP_TYPES = [
    "implements",
    "amends",
    "supersedes",
    "superseded_by",
    "clarifies",
    "applies_to",
    "cross_references",
    "issued_under",
]

DOCUMENT_STATUSES = ["in_force", "superseded", "partially_amended", "under_consultation"]

HIERARCHY_BY_SECTION: dict[str, LegalHierarchy] = {
    "CGST Circulars": "circular",
}

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Registration": ("registration", "gstin", " enrol", " enrolment", "opt-in", "opt in"),
    "Returns (GSTR-1 / 3B / 9 / 9C)": ("gstr-", "return", "filing", "gstr 9", "gstr 3b", "gstr 1", "gstr-9c"),
    "Input Tax Credit": ("input tax credit", "itc", "credit avail", "rule 36", "rule 37", "rule 42", "rule 43"),
    "Refunds": ("refund", "export", "zero rated", "zero-rated", "unutilised"),
    "E-invoicing / E-way Bill": ("e-invoice", "e invoice", "e-way", "eway", "irn", "e-way bill"),
    "Place of Supply": ("place of supply", "pos ", "inter-state", "intra-state"),
    "Rate / Classification (HSN/SAC)": ("hsn", "sac", "classification", "rate of tax", "gst rate", "schedule"),
    "Reverse Charge": ("reverse charge", "rcm", "section 9"),
    "Composition Scheme": ("composition", "section 10"),
    "Audit / Assessment / Adjudication": ("audit", "assessment", "adjudication", "show cause", "scn", "demand", "appeal"),
    "Penalties / Prosecution": ("penalty", "prosecution", "section 122", "section 132", "late fee"),
    "SEZ / Export / Zero-rated": ("sez", "export", "zero rated", "bond", "lut"),
    "Invoice / Documentary Requirements": ("invoice", "debit note", "credit note", "bill of supply", "document"),
    "Transitional / Amnesty (Section 128A)": ("128a", "128A", "amnesty", "transitional"),
}

# Canonical parent Acts/Rules circulars operate under (not in CGST circular corpus).
PARENT_INSTRUMENT_NICKNAMES: dict[str, dict[str, Any]] = {
    "CGST Act": {
        "fullName": "Central Goods and Services Tax Act, 2017",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Registration", "Input Tax Credit", "Returns (GSTR-1 / 3B / 9 / 9C)"],
    },
    "IGST Act": {
        "fullName": "Integrated Goods and Services Tax Act, 2017",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Place of Supply", "Refunds", "SEZ / Export / Zero-rated"],
    },
    "SGST Act": {
        "fullName": "State Goods and Services Tax Act, 2017 (state enactments)",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Registration", "Returns (GSTR-1 / 3B / 9 / 9C)"],
    },
    "UTGST Act": {
        "fullName": "Union Territory Goods and Services Tax Act, 2017",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Registration", "Returns (GSTR-1 / 3B / 9 / 9C)"],
    },
    "CGST Rules": {
        "fullName": "Central Goods and Services Tax Rules, 2017",
        "entities": ["General"],
        "topics": ["Input Tax Credit", "Invoice / Documentary Requirements", "Returns (GSTR-1 / 3B / 9 / 9C)"],
    },
    "IGST Rules": {
        "fullName": "Integrated Goods and Services Tax Rules, 2017",
        "entities": ["General"],
        "topics": ["Place of Supply", "Refunds"],
    },
    "Compensation Cess Act": {
        "fullName": "Goods and Services Tax (Compensation to States) Act, 2017",
        "entities": ["General"],
        "topics": ["Rate / Classification (HSN/SAC)"],
    },
    "Section 128A": {
        "fullName": "Section 128A — waiver of interest/penalty for specified tax periods (CGST Act)",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Transitional / Amnesty (Section 128A)"],
    },
    "Section 16": {
        "fullName": "Section 16 — eligibility and conditions for taking input tax credit (CGST Act)",
        "entities": ["Registered Taxpayer", "Input Service Distributor"],
        "topics": ["Input Tax Credit"],
    },
}

CANONICAL_PARENT_INSTRUMENTS: list[dict[str, Any]] = [
    {
        "id": "instrument:cgst-act-2017",
        "title": "Central Goods and Services Tax Act, 2017",
        "shortName": "CGST Act, 2017",
        "year": "2017",
        "hierarchy": "act",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Registration", "Input Tax Credit"],
        "status": "in_force",
        "sourceUrl": "https://cbic-gst.gov.in/cgst-act.html",
    },
    {
        "id": "instrument:igst-act-2017",
        "title": "Integrated Goods and Services Tax Act, 2017",
        "shortName": "IGST Act, 2017",
        "year": "2017",
        "hierarchy": "act",
        "entities": ["General", "Registered Taxpayer"],
        "topics": ["Place of Supply", "Refunds"],
        "status": "in_force",
        "sourceUrl": "https://cbic-gst.gov.in/igst-act.html",
    },
    {
        "id": "instrument:cgst-rules-2017",
        "title": "Central Goods and Services Tax Rules, 2017",
        "shortName": "CGST Rules, 2017",
        "year": "2017",
        "hierarchy": "rule",
        "entities": ["General"],
        "topics": ["Input Tax Credit", "Returns (GSTR-1 / 3B / 9 / 9C)"],
        "status": "in_force",
    },
    {
        "id": "instrument:igst-rules-2017",
        "title": "Integrated Goods and Services Tax Rules, 2017",
        "shortName": "IGST Rules, 2017",
        "year": "2017",
        "hierarchy": "rule",
        "entities": ["General"],
        "topics": ["Place of Supply"],
        "status": "in_force",
    },
    {
        "id": "instrument:compensation-cess-act-2017",
        "title": "Goods and Services Tax (Compensation to States) Act, 2017",
        "shortName": "Compensation Cess Act, 2017",
        "year": "2017",
        "hierarchy": "act",
        "entities": ["General"],
        "topics": ["Rate / Classification (HSN/SAC)"],
        "status": "in_force",
    },
    {
        "id": "instrument:notification-12-2017-ct",
        "title": "Notification No. 12/2017-Central Tax (rate schedules / exemptions)",
        "shortName": "Notification 12/2017-CT",
        "year": "2017",
        "hierarchy": "notification",
        "entities": ["General"],
        "topics": ["Rate / Classification (HSN/SAC)"],
        "status": "in_force",
    },
]

# Map frequently cited CGST Act section numbers to topics for the regulation index.
SECTION_TOPIC_HINTS: dict[str, list[str]] = {
    "9": ["Reverse Charge"],
    "10": ["Composition Scheme"],
    "12": ["Place of Supply"],
    "16": ["Input Tax Credit"],
    "17": ["Place of Supply"],
    "25": ["Registration"],
    "31": ["Invoice / Documentary Requirements"],
    "37": ["Input Tax Credit"],
    "39": ["Returns (GSTR-1 / 3B / 9 / 9C)"],
    "49": ["Returns (GSTR-1 / 3B / 9 / 9C)"],
    "54": ["Refunds"],
    "73": ["Audit / Assessment / Adjudication"],
    "74": ["Audit / Assessment / Adjudication"],
    "89": ["Refunds"],
    "122": ["Penalties / Prosecution"],
    "128A": ["Transitional / Amnesty (Section 128A)"],
    "168": ["Audit / Assessment / Adjudication"],
}

ENTITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Composition Dealer": ("composition", "section 10"),
    "Input Service Distributor": ("input service distributor", "isd"),
    "E-commerce Operator": ("e-commerce", "ecommerce", "electronic commerce", "tcs"),
    "TDS/TCS Deductor": ("tds", "tcs", "tax deducted", "tax collected"),
    "SEZ Unit / Developer": ("sez", "special economic zone"),
    "Refund Claimant": ("refund", "export refund"),
}

_CIRCULAR_NO_RE = re.compile(
    r"(\d{1,3}/\d{1,2}/\d{4}-GST|\d{1,3}/\d{2}/\d{4}-GST|\d{1,3}/\d{2}/\d{4})",
    re.I,
)
_SECTION_RE = re.compile(
    r"\bsection\s+(\d+[A-Za-z]*(?:\(\d+\))?(?:\([a-z]\))?)\b",
    re.I,
)


def document_id_from_pdf_url(pdf_url: str) -> str:
    digest = hashlib.sha256(pdf_url.encode()).hexdigest()[:12]
    return f"gst-{digest}"


def extract_official_id(text: str) -> str | None:
    match = _CIRCULAR_NO_RE.search(text or "")
    return match.group(1).upper().replace(" ", "") if match else None


def extract_section_refs(title: str, text: str = "") -> list[str]:
    combined = f"{title} {text}"
    refs = {m.group(1) for m in _SECTION_RE.finditer(combined)}
    return sorted(refs, key=lambda s: (len(s), s))


def infer_topics(title: str, subject: str = "") -> list[str]:
    blob = f"{title} {subject}".lower()
    hits = [topic for topic, keys in TOPIC_KEYWORDS.items() if any(k in blob for k in keys)]
    return hits or ["Audit / Assessment / Adjudication"]


def infer_entities_for_document(doc: dict[str, Any]) -> list[str]:
    blob = f"{doc.get('title', '')} {doc.get('summary', '')}".lower()
    hits = [code for code, keys in ENTITY_KEYWORDS.items() if any(k in blob for k in keys)]
    return hits or ["General"]


def short_title(title: str, *, limit: int = 88) -> str:
    text = re.sub(r"\s+", " ", title).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def summarize_from_title(title: str, hierarchy: str, section: str) -> str:
    return f"{section} · {hierarchy.replace('_', ' ')} — {short_title(title, limit=120)}"


def tier_for_hierarchy(hierarchy: LegalHierarchy) -> str:
    return "A" if hierarchy in {"act", "rule"} else "B"


def taxonomy_schema() -> dict[str, Any]:
    return {
        "entities": GST_ENTITY_CODES,
        "entityLabels": GST_ENTITY_LABELS,
        "topics": GST_TOPICS,
        "legalHierarchy": ["act", "rule", "circular", "notification", "order", "rate_notification"],
        "statuses": DOCUMENT_STATUSES,
        "relationshipTypes": RELATIONSHIP_TYPES,
    }
