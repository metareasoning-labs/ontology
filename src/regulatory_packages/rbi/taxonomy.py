"""Controlled vocabulary and title-based tagging for RBI documents."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

LegalHierarchy = Literal[
    "notification",
    "master_direction",
    "master_circular",
    "circular",
    "direction",
    "amendment_direction",
]

RBI_ENTITY_CODES = [
    "Commercial Banks",
    "Small Finance Banks",
    "Payments Banks",
    "Urban Co-operative Banks",
    "Rural Co-operative Banks",
    "Regional Rural Banks",
    "Local Area Banks",
    "NBFC",
    "All India Financial Institutions",
    "Asset Reconstruction Companies",
    "Credit Information Companies",
    "Foreign Exchange",
    "Payment Systems",
    "General",
]

RBI_ENTITY_LABELS: dict[str, str] = {
    "Commercial Banks": "Scheduled Commercial Banks",
    "Small Finance Banks": "Small Finance Banks (SFBs)",
    "Payments Banks": "Payments Banks",
    "Urban Co-operative Banks": "Urban Co-operative Banks (UCBs)",
    "Rural Co-operative Banks": "Rural Co-operative Banks",
    "Regional Rural Banks": "Regional Rural Banks (RRBs)",
    "Local Area Banks": "Local Area Banks (LABs)",
    "NBFC": "Non-Banking Financial Companies",
    "All India Financial Institutions": "All India Financial Institutions (AIFIs)",
    "Asset Reconstruction Companies": "Asset Reconstruction Companies (ARCs)",
    "Credit Information Companies": "Credit Information Companies (CICs)",
    "Foreign Exchange": "Foreign Exchange / FEMA",
    "Payment Systems": "Payment and Settlement Systems",
    "General": "General / cross-cutting",
}

RBI_TOPICS = [
    "Capital Adequacy / Basel",
    "Asset Classification / NPA",
    "Governance / Board",
    "Audit / Concurrent / Statutory",
    "Cybersecurity / IT Risk",
    "Digital Payments / PPI",
    "Fraud Risk Management",
    "KYC / AML / CFT",
    "Interest Rate / Deposits",
    "Credit / Lending",
    "Foreign Exchange / FEMA",
    "Payment Systems / NEFT / RTGS",
    "Supervisory Returns",
    "Liquidity / ALM",
    "Financial Statements / Disclosure",
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

DOCUMENT_STATUSES = ["in_force", "superseded", "partially_amended", "withdrawn"]

PARENT_INSTRUMENT_NICKNAMES: dict[str, dict[str, Any]] = {
    "RBI Act": {
        "fullName": "Reserve Bank of India Act, 1934",
        "entities": ["General", "Commercial Banks"],
        "topics": ["Governance / Board", "Supervisory Returns"],
    },
    "Banking Regulation Act": {
        "fullName": "Banking Regulation Act, 1949",
        "entities": ["Commercial Banks", "Urban Co-operative Banks"],
        "topics": ["Governance / Board", "Asset Classification / NPA"],
    },
    "FEMA": {
        "fullName": "Foreign Exchange Management Act, 1999",
        "entities": ["Foreign Exchange", "Commercial Banks"],
        "topics": ["Foreign Exchange / FEMA"],
    },
}

CANONICAL_PARENT_INSTRUMENTS: list[dict[str, Any]] = [
    {
        "id": "instrument:rbi-act-1934",
        "title": "Reserve Bank of India Act, 1934",
        "shortName": "RBI Act, 1934",
        "year": "1934",
        "hierarchy": "act",
        "entities": ["General", "Commercial Banks"],
        "topics": ["Governance / Board"],
        "status": "in_force",
        "sourceUrl": "https://www.rbi.org.in/",
    },
    {
        "id": "instrument:banking-regulation-act-1949",
        "title": "Banking Regulation Act, 1949",
        "shortName": "Banking Regulation Act, 1949",
        "year": "1949",
        "hierarchy": "act",
        "entities": ["Commercial Banks"],
        "topics": ["Asset Classification / NPA", "Governance / Board"],
        "status": "in_force",
        "sourceUrl": "https://www.rbi.org.in/",
    },
    {
        "id": "instrument:fema-1999",
        "title": "Foreign Exchange Management Act, 1999",
        "shortName": "FEMA, 1999",
        "year": "1999",
        "hierarchy": "act",
        "entities": ["Foreign Exchange"],
        "topics": ["Foreign Exchange / FEMA"],
        "status": "in_force",
        "sourceUrl": "https://www.rbi.org.in/",
    },
]

SECTION_TOPIC_HINTS: dict[str, list[str]] = {
    "17": ["Governance / Board"],
    "35A": ["Governance / Board"],
    "36": ["Audit / Concurrent / Statutory"],
    "46": ["Financial Statements / Disclosure"],
}

HIERARCHY_BY_SECTION: dict[str, LegalHierarchy] = {
    "Notifications": "notification",
    "Master Directions": "master_direction",
    "Master Circulars": "master_circular",
}

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Capital Adequacy / Basel": ("capital adequacy", "basel", "crar", "tier 1", "tier 2"),
    "Asset Classification / NPA": ("income recognition", "asset classification", "npa", "provisioning", "stressed assets"),
    "Governance / Board": ("governance", "board", "fit and proper", "director"),
    "Audit / Concurrent / Statutory": ("statutory audit", "concurrent audit", "internal audit", "auditor"),
    "Cybersecurity / IT Risk": ("cybersecurity", "technology risk", "information technology", "it governance"),
    "Digital Payments / PPI": ("digital payment", "prepaid", "ppi", "wallet", "upi"),
    "Fraud Risk Management": ("fraud risk", "fraud management"),
    "KYC / AML / CFT": ("kyc", "aml", "cft", "uapa", "sanctions", "pmla"),
    "Interest Rate / Deposits": ("interest rate", "deposit"),
    "Credit / Lending": ("credit facilit", "lending", "loan", "priority sector"),
    "Foreign Exchange / FEMA": ("fema", "foreign exchange", "ap dir", "export", "import"),
    "Payment Systems / NEFT / RTGS": ("neft", "rtgs", "payment system", "settlement"),
    "Supervisory Returns": ("supervisory return", "reporting"),
    "Liquidity / ALM": ("asset liability", "liquidity", "lcr", "nsfr"),
    "Financial Statements / Disclosure": ("financial statement", "disclosure", "presentation"),
}

ENTITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Commercial Banks": ("commercial bank",),
    "Small Finance Banks": ("small finance bank",),
    "Payments Banks": ("payments bank",),
    "Urban Co-operative Banks": ("urban co-operative bank", "urban cooperative bank", "ucb"),
    "Rural Co-operative Banks": ("rural co-operative bank", "rural cooperative bank"),
    "Regional Rural Banks": ("regional rural bank", "rrb"),
    "Local Area Banks": ("local area bank",),
    "NBFC": ("non-banking financial", "nbfc"),
    "All India Financial Institutions": ("all india financial institution", "aifi", "exim bank", "nabard", "nhb", "sidbi"),
    "Asset Reconstruction Companies": ("asset reconstruction", "arc"),
    "Credit Information Companies": ("credit information compan", "cic"),
    "Foreign Exchange": ("fema", "foreign exchange"),
    "Payment Systems": ("payment system", "prepaid payment"),
}


def taxonomy_schema() -> dict[str, Any]:
    return {
        "entities": [{"code": code, "label": RBI_ENTITY_LABELS.get(code, code)} for code in RBI_ENTITY_CODES],
        "topics": list(RBI_TOPICS),
        "relationshipTypes": list(RELATIONSHIP_TYPES),
        "documentStatuses": list(DOCUMENT_STATUSES),
        "hierarchies": list(HIERARCHY_BY_SECTION.values()),
    }


def document_id_from_key(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"rbi-{digest}"


def document_id_from_entry(entry_id: str | None, pdf_url: str | None = None) -> str:
    if entry_id:
        return document_id_from_key(f"entry:{entry_id}")
    if pdf_url:
        return document_id_from_key(f"pdf:{pdf_url.lower()}")
    raise ValueError("entry_id or pdf_url required")


def extract_official_id(text: str) -> str | None:
    match = re.search(
        r"(?:Notification|Circular|Master Direction|A\.?\s*P\.?\s*\([^)]+\))\s+No\.?\s*([A-Z0-9/\-_. ]{4,80})",
        text,
        re.I,
    )
    return match.group(1).strip(" :") if match else None


def infer_topics(title: str, summary: str = "") -> list[str]:
    blob = f"{title} {summary}".lower()
    topics = [topic for topic, keywords in TOPIC_KEYWORDS.items() if any(k in blob for k in keywords)]
    return topics or ["Financial Statements / Disclosure"]


def infer_entities(title: str) -> list[str]:
    blob = title.lower()
    entities = [code for code, keywords in ENTITY_KEYWORDS.items() if any(k in blob for k in keywords)]
    return entities or ["General"]


def infer_entities_for_document(doc: dict[str, Any]) -> list[str]:
    blob = " ".join(
        str(doc.get(key) or "")
        for key in ("title", "shortTitle", "summary", "section", "hierarchy")
    )
    return infer_entities(blob)


def tier_for_hierarchy(hierarchy: str) -> str:
    if hierarchy in {"master_direction", "master_circular"}:
        return "A"
    if hierarchy == "notification":
        return "B"
    return "C"


def short_title(title: str, *, max_len: int = 96) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def summarize_from_title(title: str, hierarchy: str, section: str) -> str:
    return (
        f"{section.rstrip('s')} ({hierarchy.replace('_', ' ')}) applicable to "
        f"{', '.join(infer_entities(title))}. Scope covers: {short_title(title, max_len=120)}."
    )
