"""Controlled vocabulary and tagging for Income Tax Department corpus."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

LegalHierarchy = Literal[
    "act",
    "rule",
    "provision",
    "circular",
    "notification",
    "finance_act",
    "finance_bill",
    "whats_new",
    "tax_calendar",
    "faq",
    "international",
    "guidance",
]

IT_ASSESSEE_CODES = [
    "Individual",
    "HUF",
    "Firm",
    "LLP",
    "AOP/BOI",
    "Domestic Company",
    "Foreign Company",
    "Trust",
    "Non-Resident",
    "Tax Deductor",
    "Tax Collector",
    "General",
]

IT_ASSESSEE_LABELS: dict[str, str] = {
    "Individual": "Individual assessee",
    "HUF": "Hindu Undivided Family (HUF)",
    "Firm": "Firm",
    "LLP": "Limited Liability Partnership (LLP)",
    "AOP/BOI": "Association of Persons / Body of Individuals",
    "Domestic Company": "Domestic company",
    "Foreign Company": "Foreign company",
    "Trust": "Trust / institution",
    "Non-Resident": "Non-resident / foreign assessee",
    "Tax Deductor": "Tax deductor (TDS)",
    "Tax Collector": "Tax collector (TCS)",
    "General": "General / cross-cutting",
}

IT_TOPICS = [
    "Salary / Pension",
    "House Property",
    "Business / Profession",
    "Capital Gains",
    "Other Sources",
    "TDS / TCS",
    "Return Filing / Compliance",
    "Deductions / Exemptions",
    "Advance Tax / Interest",
    "International Tax / DTAA",
    "Transfer Pricing",
    "Withholding Tax",
    "Penalties / Prosecution",
    "Faceless / e-Assessment",
    "Budget / Finance Act amendments",
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

ENTITY_ALIASES: dict[str, list[str]] = {
    "Individual": ["individual", "salaried", "pensioner", "resident individual", "taxpayer"],
    "HUF": ["huf", "hindu undivided family"],
    "Firm": ["firm", "partnership firm"],
    "LLP": ["llp", "limited liability partnership"],
    "AOP/BOI": ["aop", "boi", "association of persons", "body of individuals"],
    "Domestic Company": ["domestic company", "domestic corporate", "company assessee"],
    "Foreign Company": ["foreign company"],
    "Trust": ["trust", "charitable trust", "religious trust", "institution"],
    "Non-Resident": ["non-resident", "nri", "foreign assessee", "non resident"],
    "Tax Deductor": ["tds", "tax deductor", "deductor", "withholding agent"],
    "Tax Collector": ["tcs", "tax collector", "e-commerce operator"],
    "General": ["general", "all assessees", "cross-cutting"],
}

ENTITY_DESCRIPTIONS: dict[str, str] = {
    "Individual": "Resident or non-resident individual taxpayer; salaried, pension, and personal income.",
    "HUF": "Hindu Undivided Family assessed as a separate entity.",
    "Firm": "Partnership firm (excluding LLP) assessed as a firm.",
    "LLP": "Limited Liability Partnership registered under LLP Act.",
    "AOP/BOI": "Association of Persons or Body of Individuals.",
    "Domestic Company": "Company incorporated in India or deemed domestic under the Act.",
    "Foreign Company": "Company incorporated outside India with Indian tax presence.",
    "Trust": "Trust, institution, or fund claiming exemption or assessed as AOP/Trust.",
    "Non-Resident": "Non-resident assessee, including NRIs and foreign entities without PE.",
    "Tax Deductor": "Person responsible for deducting tax at source (TDS) under Chapter XVII.",
    "Tax Collector": "Person responsible for collecting tax at source (TCS).",
    "General": "Cross-cutting guidance not limited to one assessee class.",
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Salary / Pension": ["salary", "pension", "perquisite", "gratuity", "standard deduction", "form 16"],
    "House Property": ["house property", "rental", "let out", "self-occupied", "24b", "interest on housing loan"],
    "Business / Profession": ["business", "profession", "presumptive", "44ad", "44ada", "44ae", "books of account"],
    "Capital Gains": ["capital gain", "stcg", "ltcg", "111a", "112a", "indexation", "54", "54f"],
    "Other Sources": ["other sources", "dividend", "interest income", "lottery", "family pension"],
    "TDS / TCS": ["tds", "tcs", "194", "195", "206", "form 26q", "form 24q", "lower deduction certificate"],
    "Return Filing / Compliance": ["return", "itr", "filing", "due date", "compliance", "aadhaar pan", "e-verification"],
    "Deductions / Exemptions": ["deduction", "exemption", "80c", "80d", "87a", "chapter vi-a", "rebate"],
    "Advance Tax / Interest": ["advance tax", "234a", "234b", "234c", "interest", "self-assessment tax"],
    "International Tax / DTAA": ["dtaa", "double taxation", "treaty", "fatca", "crs", "eoir", "aeoi", "form 67"],
    "Transfer Pricing": ["transfer pricing", "arm's length", "apa", "safe harbour", "form 3ceb", "form 3cd"],
    "Withholding Tax": ["withholding", "section 195", "non-resident taxation", "form 15ca", "form 15cb"],
    "Penalties / Prosecution": ["penalty", "prosecution", "compounding", "271", "276", "234f"],
    "Faceless / e-Assessment": ["faceless", "e-assessment", "e-proceeding", "e-verification", "din"],
    "Budget / Finance Act amendments": ["finance act", "finance bill", "budget", "union budget", "amendment act"],
}

TOPIC_DESCRIPTIONS: dict[str, str] = {
    "Salary / Pension": "Income from salary, perquisites, allowances, and pension.",
    "House Property": "Income from house property, rental, and interest on borrowed capital.",
    "Business / Profession": "Profits and gains from business or profession, including presumptive schemes.",
    "Capital Gains": "Short-term and long-term capital gains on transfer of capital assets.",
    "Other Sources": "Residual heads such as interest, dividends, and winnings.",
    "TDS / TCS": "Tax deducted or collected at source, certificates, and compliance.",
    "Return Filing / Compliance": "ITR forms, due dates, verification, and procedural compliance.",
    "Deductions / Exemptions": "Chapter VI-A deductions, exemptions, and rebates.",
    "Advance Tax / Interest": "Advance tax instalments and interest under sections 234A–234C.",
    "International Tax / DTAA": "Treaty relief, residency, and cross-border reporting.",
    "Transfer Pricing": "Arm's-length pricing, APA, and documentation for related-party transactions.",
    "Withholding Tax": "TDS on payments to non-residents and treaty rates.",
    "Penalties / Prosecution": "Penalties, prosecution, and compounding under the Act.",
    "Faceless / e-Assessment": "Faceless assessment, e-proceedings, and digital compliance.",
    "Budget / Finance Act amendments": "Union Budget changes and Finance Act/Bill amendments.",
}

ABBREVIATIONS: dict[str, str] = {
    "IT Act": "Income-tax Act, 1961",
    "I-T Act": "Income-tax Act, 1961",
    "ITR": "Income Tax Return",
    "AY": "Assessment Year",
    "FY": "Financial Year",
    "TDS": "Tax Deducted at Source",
    "TCS": "Tax Collected at Source",
    "NRI": "Non-Resident Indian",
    "NR": "Non-Resident",
    "DTAA": "Double Taxation Avoidance Agreement",
    "PE": "Permanent Establishment",
    "HUF": "Hindu Undivided Family",
    "LLP": "Limited Liability Partnership",
    "STCG": "Short-Term Capital Gains",
    "LTCG": "Long-Term Capital Gains",
    "PAN": "Permanent Account Number",
    "CPC": "Centralized Processing Centre",
    "AO": "Assessing Officer",
    "CIT(A)": "Commissioner of Income Tax (Appeals)",
    "ITAT": "Income Tax Appellate Tribunal",
    "APA": "Advance Pricing Agreement",
    "FATCA": "Foreign Account Tax Compliance Act",
    "CRS": "Common Reporting Standard",
}

ACT_NICKNAMES: dict[str, dict[str, str]] = {
    "IT Act 1961": {
        "fullName": "Income-tax Act, 1961",
        "aliases": ["Income Tax Act", "I-T Act", "IT Act", "Act of 1961"],
        "hierarchy": "act",
    },
    "Wealth-tax Act": {
        "fullName": "Wealth-tax Act, 1957",
        "aliases": ["Wealth Tax Act"],
        "hierarchy": "act",
    },
    "Black Money Act": {
        "fullName": "Black Money (Undisclosed Foreign Income and Assets) and Imposition of Tax Act, 2015",
        "aliases": ["BM Act", "Undisclosed Foreign Income Act"],
        "hierarchy": "act",
    },
}

STATUS_SEMANTICS: dict[str, dict[str, str]] = {
    "in_force": {
        "label": "In force",
        "meaning": "Operative instrument; safe default for citation unless superseded edges exist.",
        "citePolicy": "prefer",
    },
    "superseded": {
        "label": "Superseded",
        "meaning": "Replaced by a later instrument; cite only for historical context.",
        "citePolicy": "avoid",
    },
    "partially_amended": {
        "label": "Partially amended",
        "meaning": "Some provisions amended; read with amending circular/notification/Finance Act.",
        "citePolicy": "read_with_amendments",
    },
    "under_consultation": {
        "label": "Under consultation",
        "meaning": "Draft or proposed; not operative law.",
        "citePolicy": "draft_only",
    },
}

HIERARCHY_META: list[dict[str, str | int]] = [
    {"id": "act", "label": "Act", "rank": 1, "section": "Income-tax Act"},
    {"id": "finance_act", "label": "Finance Act", "rank": 2, "section": "Finance Acts (search index)"},
    {"id": "finance_bill", "label": "Finance Bill", "rank": 2, "section": "Finance Bills"},
    {"id": "rule", "label": "Rules", "rank": 3, "section": "Income-tax Rules"},
    {"id": "provision", "label": "Provision", "rank": 4, "section": "Provisions (Section-wise)"},
    {"id": "circular", "label": "Circular", "rank": 5, "section": "Circulars"},
    {"id": "notification", "label": "Notification", "rank": 5, "section": "Notifications"},
    {"id": "international", "label": "International", "rank": 5, "section": "International — DTAA"},
    {"id": "faq", "label": "FAQ", "rank": 6, "section": "FAQs"},
    {"id": "tax_calendar", "label": "Tax Calendar", "rank": 6, "section": "Tax Calendar"},
    {"id": "whats_new", "label": "Press Release", "rank": 7, "section": "What's New (Press Releases)"},
    {"id": "guidance", "label": "Guidance", "rank": 7, "section": "Budget & Finance Bills"},
]

_ASSESSEE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Individual", re.compile(r"\b(individual|salaried|pensioner|resident individual)\b", re.I)),
    ("HUF", re.compile(r"\b(huf|hindu undivided family)\b", re.I)),
    ("Firm", re.compile(r"\b(\bfirm\b|partnership firm)\b", re.I)),
    ("LLP", re.compile(r"\b(llp|limited liability partnership)\b", re.I)),
    ("AOP/BOI", re.compile(r"\b(aop|boi|association of persons|body of individuals)\b", re.I)),
    ("Domestic Company", re.compile(r"\b(domestic compan|domestic corporate)\b", re.I)),
    ("Foreign Company", re.compile(r"\b(foreign compan)\b", re.I)),
    ("Trust", re.compile(r"\b(trust|charitable|religious trust|institution)\b", re.I)),
    ("Non-Resident", re.compile(r"\b(non-?resident|nri|foreign assessee|non resident)\b", re.I)),
    ("Tax Deductor", re.compile(r"\b(tds|tax deductor|deductor|withholding)\b", re.I)),
    ("Tax Collector", re.compile(r"\b(tcs|tax collector|collector of tax)\b", re.I)),
]

_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Salary / Pension", re.compile(r"\b(salary|pension|perquisite|gratuity)\b", re.I)),
    ("House Property", re.compile(r"\b(house property|rental|let out|self-occupied)\b", re.I)),
    ("Business / Profession", re.compile(r"\b(business|profession|presumptive|44ad|44ada)\b", re.I)),
    ("Capital Gains", re.compile(r"\b(capital gain|stcg|ltcg|111a|112a)\b", re.I)),
    ("Other Sources", re.compile(r"\b(other sources|dividend|interest income|lottery)\b", re.I)),
    ("TDS / TCS", re.compile(r"\b(tds|tcs|tax deducted|tax collected|194|195|206)\b", re.I)),
    ("Return Filing / Compliance", re.compile(r"\b(return|itr|filing|due date|compliance|aadhaar pan linking)\b", re.I)),
    ("Deductions / Exemptions", re.compile(r"\b(deduction|exemption|80c|80d|87a|chapter vi-a)\b", re.I)),
    ("Advance Tax / Interest", re.compile(r"\b(advance tax|234a|234b|234c|interest)\b", re.I)),
    ("International Tax / DTAA", re.compile(r"\b(dtaa|double taxation|treaty|fatca|crs|eoir|aeoi)\b", re.I)),
    ("Transfer Pricing", re.compile(r"\b(transfer pricing|arm'?s length|apa|safe harbour|form 3ceb)\b", re.I)),
    ("Withholding Tax", re.compile(r"\b(withholding|section 195|non-resident taxation)\b", re.I)),
    ("Penalties / Prosecution", re.compile(r"\b(penalty|prosecution|compounding|271|276)\b", re.I)),
    ("Faceless / e-Assessment", re.compile(r"\b(faceless|e-assessment|e-proceeding|e-verification)\b", re.I)),
    ("Budget / Finance Act amendments", re.compile(r"\b(finance act|finance bill|budget|union budget)\b", re.I)),
]

_SECTION_REF_RE = re.compile(r"\bsection\s+(\d+[A-Za-z]?)\b", re.I)
_CIRCULAR_NO_RE = re.compile(r"\bcircular\s*(?:no\.?)?\s*([\d/\-]+)", re.I)
_NOTIFICATION_NO_RE = re.compile(r"\bnotification\s*(?:no\.?)?\s*([\d/\-A-Za-z]+)", re.I)


def taxonomy_schema() -> dict:
    return {
        "entities": [IT_ASSESSEE_LABELS[c] for c in IT_ASSESSEE_CODES],
        "entityCodes": IT_ASSESSEE_CODES,
        "entityLabels": IT_ASSESSEE_LABELS,
        "topics": list(IT_TOPICS),
        "legalHierarchy": [
            "act", "rule", "provision", "circular", "notification",
            "finance_act", "finance_bill", "whats_new", "tax_calendar", "faq", "international",
        ],
        "statuses": list(DOCUMENT_STATUSES),
        "relationshipTypes": list(RELATIONSHIP_TYPES),
    }


def short_title(title: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"\s+", " ", title.strip())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def document_id_from_url(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"itd-{digest}"


def _ordered_unique(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen and code in IT_ASSESSEE_CODES:
            seen.add(code)
            out.append(code)
    return out


def infer_assessees_from_text(*texts: str | None) -> list[str]:
    combined = " ".join(t.strip() for t in texts if t and t.strip())
    if not combined:
        return ["General"]
    hits = [code for code, pattern in _ASSESSEE_PATTERNS if pattern.search(combined)]
    hits = _ordered_unique(hits)
    return hits or ["General"]


def infer_assessees(title: str) -> list[str]:
    return infer_assessees_from_text(title)


def infer_assessees_for_document(doc: dict) -> list[str]:
    section = doc.get("section", "")
    hierarchy = doc.get("hierarchy", "")
    extra = ""
    if hierarchy == "international" or section.startswith("International"):
        extra = "non-resident DTAA withholding transfer pricing"
    if hierarchy == "faq":
        extra = "return filing computation"
    return infer_assessees_from_text(doc.get("title", ""), doc.get("summary", ""), extra)


def infer_topics(title: str) -> list[str]:
    hits = [topic for topic, pattern in _TOPIC_PATTERNS if pattern.search(title)]
    return hits or ["Return Filing / Compliance"]


def infer_topics_for_document(doc: dict) -> list[str]:
    text = " ".join(
        filter(None, [doc.get("title", ""), doc.get("summary", ""), doc.get("section", "")])
    )
    hits = [topic for topic, pattern in _TOPIC_PATTERNS if pattern.search(text)]
    return hits or infer_topics(doc.get("title", ""))


def extract_section_refs(text: str) -> list[str]:
    return sorted({m.group(1) for m in _SECTION_REF_RE.finditer(text)}, key=lambda s: (len(s), s))


def extract_official_id(title: str, hierarchy: str) -> str | None:
    if hierarchy == "circular":
        m = _CIRCULAR_NO_RE.search(title)
        return f"Circular No. {m.group(1)}" if m else None
    if hierarchy == "notification":
        m = _NOTIFICATION_NO_RE.search(title)
        return f"Notification No. {m.group(1)}" if m else None
    refs = extract_section_refs(title)
    if refs:
        return f"Section {refs[0]}"
    return None


def tier_for_hierarchy(hierarchy: str) -> str:
    if hierarchy in ("act", "rule", "provision", "finance_act"):
        return "C"
    if hierarchy in ("circular", "notification", "international", "faq"):
        return "B"
    return "A"


def summarize_from_title(title: str, hierarchy: str, section: str) -> str:
    assessee_hint = ", ".join(infer_assessees(title)[:2])
    topic_hint = infer_topics(title)[0]
    kind = hierarchy.replace("_", " ").title()
    return (
        f"ITD {kind} ({section}) on {topic_hint.lower()} applicable to {assessee_hint}. "
        f"Scope: {title}. Metadata-only summary for graph indexing."
    )
