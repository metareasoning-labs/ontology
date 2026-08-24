"""Controlled vocabulary and title-based tagging for IRDAI insurance corpus."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

LegalHierarchy = Literal[
    "act",
    "rule",
    "regulation",
    "notification",
    "circular",
    "guideline",
    "order",
    "notice",
    "exposure_draft",
    "other",
]

INSURANCE_ENTITY_CODES = [
    "Life Insurer",
    "General Insurer",
    "Health Insurer",
    "Reinsurer",
    "Insurance Broker",
    "Corporate Agent",
    "Insurance Surveyor",
    "TPA",
    "Insurance Marketing Firm",
    "Web Aggregator",
    "Policyholder",
    "General",
]

INSURANCE_ENTITY_LABELS: dict[str, str] = {
    "Life Insurer": "Life insurance company",
    "General Insurer": "General (non-life) insurance company",
    "Health Insurer": "Standalone health insurance company",
    "Reinsurer": "Reinsurance company or FRB",
    "Insurance Broker": "Registered insurance broker",
    "Corporate Agent": "Corporate agent / bancassurance partner",
    "Insurance Surveyor": "Licensed insurance surveyor",
    "TPA": "Third Party Administrator (health claims)",
    "Insurance Marketing Firm": "Insurance Marketing Firm (IMF)",
    "Web Aggregator": "Insurance web aggregator",
    "Policyholder": "Policyholder / insured / consumer",
    "General": "General / cross-cutting",
}

INSURANCE_TOPICS = [
    "Licensing & Registration",
    "Solvency & Capital",
    "Investments",
    "Product Filing / File & Use",
    "Claims & Settlement",
    "Grievance / Ombudsman",
    "Intermediaries & Distribution",
    "Reinsurance",
    "Health Insurance",
    "Motor / Third Party",
    "Microinsurance",
    "Corporate Governance",
    "AML / KYC",
    "Actuarial / Appointed Actuary",
    "Policyholder Protection",
    "Rural / Social Sector",
    "Exposure Draft / Consultation",
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

DOCUMENT_STATUSES = ["in_force", "superseded", "partially_amended", "archived", "under_consultation"]

HIERARCHY_BY_SECTION: dict[str, LegalHierarchy] = {
    "Acts": "act",
    "Rules": "rule",
    "Regulations": "regulation",
    "Consolidated & Gazette Notified Regulations": "regulation",
    "Updated Regulations": "regulation",
    "Notifications": "notification",
    "Circulars": "circular",
    "Guidelines": "guideline",
    "Orders": "order",
    "Notices": "notice",
    "Exposure Drafts": "exposure_draft",
    "Other Communication": "other",
}

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Licensing & Registration": ("licen", "registration", "certificate of registration", "cor "),
    "Solvency & Capital": ("solvency", "capital", "solvency margin", "control level", "trigger"),
    "Investments": ("investment", "portfolio", "nav", "mutual fund", "equity", "debt"),
    "Product Filing / File & Use": ("file and use", "product", "uin", "approval", "file & use"),
    "Claims & Settlement": ("claim", "settlement", "repudiation", "cashless"),
    "Grievance / Ombudsman": ("grievance", "ombudsman", "complaint", "igms", "gro"),
    "Intermediaries & Distribution": ("broker", "agent", "intermediary", "corporate agent", "imf", "posp"),
    "Reinsurance": ("reinsur", "retrocession", "frb", "cross border"),
    "Health Insurance": ("health", "tpa", "hospital", "cashless", "standard health"),
    "Motor / Third Party": ("motor", "third party", "tp ", "misp"),
    "Microinsurance": ("microinsur", "micro insurance"),
    "Corporate Governance": ("corporate governance", "fit and proper", "board", "director"),
    "AML / KYC": ("aml", "anti money", "kyc", "pmla", "cft"),
    "Actuarial / Appointed Actuary": ("actuar", "appointed actuary", "actuary"),
    "Policyholder Protection": ("policyholder", "consumer", "protection", "disclosure"),
    "Rural / Social Sector": ("rural", "social sector", "obligation"),
    "Exposure Draft / Consultation": ("exposure draft", "draft regulation", "comments invited"),
}

PARENT_INSTRUMENT_NICKNAMES: dict[str, dict[str, Any]] = {
    "Insurance Act 1938": {
        "fullName": "Insurance Act, 1938",
        "entities": ["General", "Life Insurer", "General Insurer"],
        "topics": ["Licensing & Registration", "Solvency & Capital"],
    },
    "IRDA Act 1999": {
        "fullName": "Insurance Regulatory and Development Authority Act, 1999",
        "entities": ["General"],
        "topics": ["Licensing & Registration", "Corporate Governance"],
    },
}

_SECTION_REF_RE = re.compile(
    r"\b(?:section|sec\.?|regulation|reg\.?)\s*([0-9]+[A-Za-z]?)\b",
    re.I,
)
_OFFICIAL_ID_RE = re.compile(
    r"\b(?:IRDAI/(?:Life|NL|Health|Reins)/[A-Z]+[-/][0-9/\-]+|"
    r"Ref\.?\s*No\.?\s*[A-Z0-9/\-]+|"
    r"Circular\s*(?:No\.?)?\s*[A-Z0-9/\-]+)\b",
    re.I,
)


def document_id_from_source(irdai_document_id: str, section_slug: str) -> str:
    raw = f"{section_slug}:{irdai_document_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"irdai-{digest}"


def extract_official_id(title: str) -> str | None:
    match = _OFFICIAL_ID_RE.search(title)
    if match:
        return match.group(0).strip()
    return None


def extract_section_refs(title: str) -> list[str]:
    return sorted({m.group(1) for m in _SECTION_REF_RE.finditer(title)})


def infer_entities_for_document(doc: dict[str, Any] | str, *, hierarchy: str = "") -> list[str]:
    if isinstance(doc, dict):
        blob = f"{doc.get('title', '')} {doc.get('summary', '')}".lower()
        hierarchy = hierarchy or str(doc.get("hierarchy", "") or "")
    else:
        blob = doc.lower()
    hits: list[str] = []
    rules = [
        ("Life Insurer", ("life insurer", "life insurance", "irdai/life")),
        ("General Insurer", ("general insurer", "non-life", "non life", "irdai/nl")),
        ("Health Insurer", ("health insurer", "health insurance", "irdai/health")),
        ("Reinsurer", ("reinsur", "frb")),
        ("Insurance Broker", ("broker",)),
        ("Corporate Agent", ("corporate agent", "bancassurance")),
        ("Insurance Surveyor", ("surveyor",)),
        ("TPA", ("tpa", "third party admin")),
        ("Insurance Marketing Firm", ("imf", "insurance marketing firm")),
        ("Web Aggregator", ("web aggregat",)),
        ("Policyholder", ("policyholder", "insured", "consumer")),
    ]
    for entity, keywords in rules:
        if any(kw in blob for kw in keywords):
            hits.append(entity)
    if not hits:
        hits = ["General"]
    return hits[:4]


def infer_topics(title: str, body: str = "") -> list[str]:
    blob = f"{title} {body}".lower()
    hits = [topic for topic, keywords in TOPIC_KEYWORDS.items() if any(kw in blob for kw in keywords)]
    return hits[:5] if hits else ["Policyholder Protection"]


def short_title(title: str, max_len: int = 96) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def summarize_from_title(title: str, *, section: str, hierarchy: str) -> str:
    return f"{section} ({hierarchy}) — {short_title(title, 180)}"


def tier_for_hierarchy(hierarchy: str) -> str:
    if hierarchy in ("act", "rule", "regulation"):
        return "A"
    if hierarchy in ("circular", "guideline", "notification"):
        return "B"
    return "C"


CANONICAL_PARENT_INSTRUMENTS: list[dict[str, Any]] = [
    {
        "id": "instrument:insurance-act-1938",
        "title": "Insurance Act, 1938",
        "shortName": "Insurance Act, 1938",
        "year": "1938",
        "hierarchy": "act",
        "entities": ["General", "Life Insurer", "General Insurer"],
        "topics": ["Licensing & Registration", "Solvency & Capital"],
        "status": "in_force",
        "sourceUrl": "https://irdai.gov.in/acts",
    },
    {
        "id": "instrument:irda-act-1999",
        "title": "Insurance Regulatory and Development Authority Act, 1999",
        "shortName": "IRDA Act, 1999",
        "year": "1999",
        "hierarchy": "act",
        "entities": ["General"],
        "topics": ["Licensing & Registration", "Corporate Governance"],
        "status": "in_force",
        "sourceUrl": "https://irdai.gov.in/acts",
    },
]
SECTION_TOPIC_HINTS: dict[str, list[str]] = {
    "Acts": ["Licensing & Registration", "Policyholder Protection"],
    "Circulars": ["Intermediaries & Distribution", "Claims & Settlement"],
    "Regulations": ["Solvency & Capital", "Investments"],
}


def taxonomy_schema() -> dict[str, Any]:
    return {
        "entities": INSURANCE_ENTITY_CODES,
        "entityLabels": INSURANCE_ENTITY_LABELS,
        "topics": INSURANCE_TOPICS,
        "legalHierarchy": [
            "act",
            "rule",
            "regulation",
            "notification",
            "circular",
            "guideline",
            "order",
            "notice",
            "exposure_draft",
            "other",
        ],
        "statuses": DOCUMENT_STATUSES,
        "relationshipTypes": RELATIONSHIP_TYPES,
    }


def build_taxonomy_hubs() -> list[dict[str, Any]]:
    hubs = [
        {"id": "hub:insurance-act-1938", "label": "Insurance Act, 1938", "section": "Acts", "hierarchy": "act", "rank": 1, "depthTier": "A"},
        {"id": "hub:irda-act-1999", "label": "IRDA Act, 1999", "section": "Acts", "hierarchy": "act", "rank": 2, "depthTier": "A"},
        {"id": "hub:regulations", "label": "IRDAI Regulations", "section": "Regulations", "hierarchy": "regulation", "rank": 3, "depthTier": "A"},
        {"id": "hub:circulars", "label": "IRDAI Circulars", "section": "Circulars", "hierarchy": "circular", "rank": 4, "depthTier": "B"},
        {"id": "hub:guidelines", "label": "IRDAI Guidelines", "section": "Guidelines", "hierarchy": "guideline", "rank": 5, "depthTier": "B"},
    ]
    for index, entity in enumerate(INSURANCE_ENTITY_CODES):
        hubs.append(
            {
                "id": f"entity:{entity}",
                "label": INSURANCE_ENTITY_LABELS.get(entity, entity),
                "section": "Entities",
                "hierarchy": "entity",
                "rank": 10 + index,
                "depthTier": "C",
            }
        )
    return hubs
