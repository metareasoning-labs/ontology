"""Generate LLM vocabulary and grammar from IRDAI catalog + ontology artifacts."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from regulatory_packages.insurance.taxonomy import (
    CANONICAL_PARENT_INSTRUMENTS,
    DOCUMENT_STATUSES,
    INSURANCE_ENTITY_CODES,
    INSURANCE_ENTITY_LABELS,
    INSURANCE_TOPICS,
    HIERARCHY_BY_SECTION,
    PARENT_INSTRUMENT_NICKNAMES,
    RELATIONSHIP_TYPES,
    SECTION_TOPIC_HINTS,
    TOPIC_KEYWORDS,
    taxonomy_schema,
)

_VOCABULARY_VERSION = 6
_GRAMMAR_VERSION = 6

HIERARCHY_META: list[dict[str, Any]] = [
    {"id": "act", "label": "Acts", "section": "Acts", "rank": 1, "depthTier": "A"},
    {"id": "rule", "label": "Rules", "section": "Rules", "rank": 2, "depthTier": "A"},
    {"id": "regulation", "label": "Regulations", "section": "Regulations", "rank": 3, "depthTier": "A"},
    {"id": "circular", "label": "Circulars", "section": "Circulars", "rank": 4, "depthTier": "B"},
    {"id": "guideline", "label": "Guidelines", "section": "Guidelines", "rank": 5, "depthTier": "B"},
    {"id": "notification", "label": "Notifications", "section": "Notifications", "rank": 5, "depthTier": "B"},
    {"id": "order", "label": "Orders", "section": "Orders", "rank": 6, "depthTier": "B"},
    {"id": "exposure_draft", "label": "Exposure Drafts", "section": "Exposure Drafts", "rank": 7, "depthTier": "C"},
]

ABBREVIATIONS: dict[str, str] = {
    "IRDAI": "Insurance Regulatory and Development Authority of India",
    "IRDA": "Insurance Regulatory and Development Authority",
    "TPA": "Third Party Administrator",
    "IMF": "Insurance Marketing Firm",
    "COR": "Certificate of Registration",
    "UIN": "Unique Identification Number",
    "FRB": "Foreign Reinsurance Branch",
    "GRO": "Grievance Redressal Officer",
    "IGMS": "Integrated Grievance Management System",
    "AML": "Anti-Money Laundering",
    "KYC": "Know Your Customer",
    "POSP": "Point of Sales Person",
}

ENTITY_ALIASES: dict[str, list[str]] = {
    "Life Insurer": ["life insurance company", "life insurer", "irdai/life"],
    "General Insurer": ["general insurer", "non-life insurer", "irdai/nl"],
    "Health Insurer": ["health insurer", "standalone health", "irdai/health"],
    "Reinsurer": ["reinsurer", "reinsurance company", "frb"],
    "Insurance Broker": ["insurance broker", "broker"],
    "Corporate Agent": ["corporate agent", "bancassurance"],
    "Insurance Surveyor": ["surveyor", "insurance surveyor"],
    "TPA": ["tpa", "third party administrator"],
    "Insurance Marketing Firm": ["imf", "insurance marketing firm"],
    "Web Aggregator": ["web aggregator", "insurance aggregator"],
    "Policyholder": ["policyholder", "insured", "consumer"],
    "General": ["general", "cross-cutting"],
}

TOPIC_DESCRIPTIONS: dict[str, str] = {
    "Licensing & Registration": "Certificate of registration, licensing, and fit-and-proper norms.",
    "Solvency & Capital": "Solvency margin, control level, and capital adequacy for insurers.",
    "Investments": "Investment regulations and portfolio norms for insurance funds.",
    "Product Filing / File & Use": "Product approval, UIN, and file-and-use procedures.",
    "Claims & Settlement": "Claims handling, repudiation, and settlement timelines.",
    "Grievance / Ombudsman": "GRO, IGMS, and policyholder grievance redressal.",
    "Intermediaries & Distribution": "Brokers, agents, POSP, IMF, and distribution channels.",
    "Health Insurance": "Health products, TPAs, and cashless hospital networks.",
    "AML / KYC": "Anti-money laundering and customer due diligence for insurers.",
    "Policyholder Protection": "Disclosure, unfair contract terms, and consumer protection.",
}

_SECTION_QUERY_INTENTS: dict[str, list[dict[str, Any]]] = {
    "Acts": [{"intent": "parent_act_lookup", "examples": ["Insurance Act 1938 licensing provisions"], "citePreference": ["act"]}],
    "Regulations": [{"intent": "regulation_lookup", "examples": ["IRDAI solvency regulations for life insurers"], "citePreference": ["regulation"]}],
    "Circulars": [{"intent": "circular_clarification", "examples": ["Latest IRDAI circular on health insurance claims"], "citePreference": ["circular"]}],
    "Guidelines": [{"intent": "guideline_compliance", "examples": ["IRDAI guidelines on corporate governance"], "citePreference": ["guideline"]}],
    "Exposure Drafts": [{"intent": "draft_consultation", "examples": ["Exposure draft on insurance brokers"], "citePreference": ["exposure_draft"]}],
}

_QUERY_INTENTS = [
    {"intent": "regulation_lookup", "examples": ["Which IRDAI regulation governs solvency margin for life insurers?"]},
    {"intent": "intermediary_compliance", "examples": ["Broker registration requirements under IRDAI"]},
    {"intent": "supersession_chain", "examples": ["Which circular supersedes earlier health insurance guidelines?"]},
]

_RELATIONSHIP_SEMANTICS: dict[str, dict[str, Any]] = {
    "implements": {"direction": "source → target", "meaning": "Instrument gives effect to Insurance Act or IRDA Act provisions.", "traverseBeforeCite": True},
    "clarifies": {"direction": "source → target", "meaning": "Instrument clarifies operative provision or earlier circular.", "traverseBeforeCite": True},
    "supersedes": {"direction": "source → target", "meaning": "Source replaces target; do not cite superseded instrument.", "traverseBeforeCite": True},
    "amends": {"direction": "source → target", "meaning": "Source amends guidance in target instrument.", "traverseBeforeCite": True},
    "applies_to": {"direction": "document → entity", "meaning": "Document applies to insurer or intermediary class.", "traverseBeforeCite": False},
    "cross_references": {"direction": "bidirectional", "meaning": "Related regulation, circular, or section reference.", "traverseBeforeCite": False},
    "issued_under": {"direction": "document → hub", "meaning": "Document belongs to IRDAI legal corpus.", "traverseBeforeCite": False},
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _count_by_key(documents: list[dict[str, Any]], key: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for doc in documents:
        value = doc.get(key)
        if isinstance(value, list):
            for item in value:
                counter[str(item)] += 1
        elif value:
            counter[str(value)] += 1
    return counter


def _build_lexical_index(documents: list[dict[str, Any]], *, limit: int = 80) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    stop = {"irdai", "insurance", "insurer", "regulation", "circular", "section", "shall", "policy", "general"}
    for doc in documents:
        blob = f"{doc.get('title', '')} {doc.get('summary', '')}".lower()
        for token in re.findall(r"[a-z]{5,}", blob):
            if token not in stop:
                counter[token] += 1
    return [{"term": term, "documentFrequency": count} for term, count in counter.most_common(limit)]


def _section_base(section: str) -> str:
    return re.sub(r"\(.*\)$", "", section.strip()).upper()


def _build_section_regulation_index(corpus_analysis: dict[str, Any], *, limit: int = 40) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in corpus_analysis.get("sectionRefsFromText", []):
        section = str(item.get("section", "")).strip()
        if not section or not re.match(r"^\d", section):
            continue
        base = _section_base(section)
        if base in seen:
            continue
        seen.add(base)
        topics = SECTION_TOPIC_HINTS.get("Regulations", ["Licensing & Registration"])
        index.append(
            {
                "id": f"section:insurance-act:{base.lower()}",
                "title": f"Section {section} of the Insurance Act, 1938",
                "shortName": f"Section {section}",
                "year": "1938",
                "hierarchy": "regulation",
                "entities": ["General"],
                "topics": topics,
                "status": "in_force",
                "circularRefCount": int(item.get("documentFrequency") or 0),
            }
        )
        if len(index) >= limit:
            break
    return index


def _build_regulation_index(documents: list[dict[str, Any]], corpus_analysis: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = [dict(item) for item in CANONICAL_PARENT_INSTRUMENTS]
    for doc in documents:
        if doc.get("hierarchy") in {"act", "rule", "regulation", "notification", "circular", "guideline"} and doc.get("title"):
            index.append(
                {
                    "id": doc["id"],
                    "title": doc["title"],
                    "shortName": doc.get("shortTitle") or doc.get("officialId") or doc["title"][:120],
                    "year": (doc.get("issuedAt") or "")[:4] or None,
                    "hierarchy": doc.get("hierarchy", "regulation"),
                    "entities": doc.get("entities", []),
                    "topics": doc.get("topics", []),
                    "status": doc.get("status", "in_force"),
                    "sourceUrl": doc.get("sourceUrl"),
                }
            )
    index.extend(_build_section_regulation_index(corpus_analysis or {}, limit=40))
    return index


def _build_section_vocabularies(
    documents: list[dict[str, Any]],
    *,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    document_analyses = document_analyses or {}
    slices: list[dict[str, Any]] = []
    for section, hierarchy in HIERARCHY_BY_SECTION.items():
        section_docs = [doc for doc in documents if doc.get("section") == section]
        if not section_docs:
            continue
        entity_counts = _count_by_key(section_docs, "entities")
        topic_counts = _count_by_key(section_docs, "topics")
        analyzed = sum(1 for doc in section_docs if document_analyses.get(doc["id"], {}).get("textAnalyzed"))
        slices.append(
            {
                "section": section,
                "hierarchy": hierarchy,
                "documentCount": len(section_docs),
                "textAnalyzedCount": analyzed,
                "entities": [
                    {"code": code, "label": INSURANCE_ENTITY_LABELS.get(code, code), "documentCount": entity_counts.get(code, 0)}
                    for code in INSURANCE_ENTITY_CODES
                    if entity_counts.get(code, 0) > 0
                ],
                "topics": [
                    {"id": _slug(topic), "label": topic, "documentCount": topic_counts.get(topic, 0)}
                    for topic in INSURANCE_TOPICS
                    if topic_counts.get(topic, 0) > 0
                ],
                "lexicalIndex": _build_lexical_index(section_docs, limit=40),
                "queryIntents": _SECTION_QUERY_INTENTS.get(section, []),
                "obligationSamples": (corpus_analysis or {}).get("obligationSamples", [])[:8],
            }
        )
    return slices


def _build_section_grammars(section_slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section": item["section"],
            "hierarchy": item["hierarchy"],
            "startSymbol": "RegulatoryAnswer",
            "defaultPath": "entity → topic → instrument",
            "citePreference": [item["hierarchy"]],
            "navigation": {"axes": ["entity", "topic", item["hierarchy"], "section"], "description": f"Navigate IRDAI {item['section']} corpus."},
            "queryIntents": item.get("queryIntents", []),
        }
        for item in section_slices
    ]


def build_vocabulary(
    catalog: dict[str, Any],
    ontology: dict[str, Any] | None = None,
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    documents = catalog.get("documents") or []
    text_by_id = text_by_id or {}
    document_analyses = document_analyses or {}
    corpus_analysis = corpus_analysis or (ontology or {}).get("stats", {}).get("corpusAnalysis", {})
    text_count = sum(1 for doc in documents if text_by_id.get(doc.get("id", "")))
    analyzed_count = sum(1 for a in document_analyses.values() if a.get("textAnalyzed"))
    entity_counts = _count_by_key(documents, "entities")
    topic_counts = _count_by_key(documents, "topics")
    hierarchy_counts = _count_by_key(documents, "hierarchy")
    status_counts = _count_by_key(documents, "status")
    section_counts = _count_by_key(documents, "section")
    relationship_stats = (ontology or {}).get("stats", {}).get("relationshipsByType", {})
    priority_entities = (ontology or {}).get("scope", {}).get("entityPriority", [])

    entities = [
        {
            "code": code,
            "label": INSURANCE_ENTITY_LABELS.get(code, code),
            "description": "",
            "aliases": ENTITY_ALIASES.get(code, [code.lower()]),
            "documentCount": entity_counts.get(code, 0),
            "priority": priority_entities.index(INSURANCE_ENTITY_LABELS.get(code, code)) + 1
            if INSURANCE_ENTITY_LABELS.get(code, code) in priority_entities
            else None,
        }
        for code in INSURANCE_ENTITY_CODES
    ]

    topics = [
        {
            "id": _slug(topic),
            "label": topic,
            "description": TOPIC_DESCRIPTIONS.get(topic, ""),
            "keywords": list(TOPIC_KEYWORDS.get(topic, ())),
            "documentCount": topic_counts.get(topic, 0),
        }
        for topic in INSURANCE_TOPICS
    ]

    hierarchies = [
        {**meta, "documentCount": hierarchy_counts.get(str(meta["id"]), 0), "sectionDocumentCount": section_counts.get(str(meta["section"]), 0)}
        for meta in HIERARCHY_META
    ]

    return {
        "version": _VOCABULARY_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "source": catalog.get("source", "https://irdai.gov.in"),
        "corpus": {
            "documentCount": len(documents),
            "fetchedAt": catalog.get("fetchedAt"),
            "sections": catalog.get("sections", list(HIERARCHY_BY_SECTION.keys())),
            "sectionStats": catalog.get("sectionStats", {}),
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "textCoverageRatio": round(text_count / len(documents), 4) if documents else 0.0,
            "analysisCoverageRatio": round(analyzed_count / len(documents), 4) if documents else 0.0,
            "pdfBacked": text_count > 0,
            "deepAnalysis": analyzed_count > 0,
            "corpusAnalysis": corpus_analysis,
        },
        "entities": entities,
        "topics": topics,
        "hierarchies": hierarchies,
        "sections": [
            {"label": section, "hierarchy": hierarchy, "documentCount": section_counts.get(section, 0)}
            for section, hierarchy in HIERARCHY_BY_SECTION.items()
        ],
        "sectionVocabularies": _build_section_vocabularies(documents, document_analyses=document_analyses, corpus_analysis=corpus_analysis),
        "regulations": _build_regulation_index(documents, corpus_analysis),
        "regulationNicknames": [{"nickname": nickname, **meta} for nickname, meta in PARENT_INSTRUMENT_NICKNAMES.items()],
        "relationshipTypes": [
            {"type": rel_type, "label": rel_type.replace("_", " ").title(), "edgeCount": relationship_stats.get(rel_type, 0), **(_RELATIONSHIP_SEMANTICS.get(rel_type, {}))}
            for rel_type in RELATIONSHIP_TYPES
        ],
        "statuses": [{"id": status, "documentCount": status_counts.get(status, 0)} for status in DOCUMENT_STATUSES],
        "abbreviations": ABBREVIATIONS,
        "lexicalIndex": _build_lexical_index(documents),
        "lexicalIndexFromText": corpus_analysis.get("lexicalIndexFromText", []),
        "definedTermGlossary": corpus_analysis.get("definedTermGlossary", []),
        "obligationSamples": corpus_analysis.get("obligationSamples", []),
        "sectionRefsFromText": corpus_analysis.get("sectionRefsFromText", []),
        "officialIds": sorted({str(d.get("officialId")) for d in documents if d.get("officialId")}),
        "documentAnalysisSchema": {"documentsWithAnalysis": analyzed_count},
        "taxonomy": taxonomy_schema(),
    }


def build_grammar(
    catalog: dict[str, Any],
    ontology: dict[str, Any] | None = None,
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    documents = catalog.get("documents") or []
    text_by_id = text_by_id or {}
    document_analyses = document_analyses or {}
    corpus_analysis = corpus_analysis or (ontology or {}).get("stats", {}).get("corpusAnalysis", {})
    text_count = sum(1 for doc in documents if text_by_id.get(doc.get("id", "")))
    analyzed_count = int(corpus_analysis.get("documentsAnalyzed") or 0)
    rel_stats = (ontology or {}).get("stats", {}).get("relationshipsByType", {})
    section_slices = _build_section_vocabularies(documents, document_analyses=document_analyses, corpus_analysis=corpus_analysis)

    return {
        "version": _GRAMMAR_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "startSymbol": "RegulatoryAnswer",
        "systemPrompt": (
            "Navigate Indian insurance law using IRDAI acts, regulations, circulars, and guidelines from irdai.gov.in. "
            "Filter by insurer/intermediary entity and topic (solvency, claims, licensing, AML/KYC). "
            "Traverse supersedes/clarifies/implements edges before citing leaf instruments. "
            "Prefer in-force regulations and circulars; cite officialId and section references."
        ),
        "navigation": {
            "axes": ["entity", "topic", "hierarchy", "section", "instrument"],
            "defaultPath": "entity → topic → instrument",
            "alternatePaths": ["section → entity → instrument", "topic → regulation → officialId"],
            "description": "Resolve IRDAI terms to controlled vocabulary, filter by section, traverse relationship edges.",
        },
        "citationRules": {
            "preferHierarchies": ["act", "regulation", "circular", "guideline"],
            "avoidStatus": ["superseded", "archived"],
            "requireTraversal": ["supersedes", "superseded_by", "clarifies", "amends", "implements"],
            "titleField": "title",
            "fallbackFields": ["officialId", "pdfUrl", "sourceUrl"],
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "disclaimer": "Verify operative language in official IRDAI PDFs before compliance decisions.",
        },
        "relationshipSemantics": _RELATIONSHIP_SEMANTICS,
        "relationshipStats": rel_stats,
        "productions": [
            {"nonterminal": "RegulatoryAnswer", "description": "Structured IRDAI compliance answer.", "productions": ["ScopeStatement InstrumentChain PrimaryObligation StatusCaveats?"]},
            {"nonterminal": "InstrumentChain", "description": "Ordered list of operative IRDAI instruments.", "productions": ["InstrumentRef (implements|clarifies|supersedes|amends InstrumentRef)*"]},
            {"nonterminal": "HierarchyPrecedenceRule", "description": "Conflict resolution.", "productions": ["'prefer' RegulationRef 'over' CircularRef", "'Act provisions prevail over circular guidance'"]},
        ],
        "queryIntents": _QUERY_INTENTS,
        "sectionGrammars": _build_section_grammars(section_slices),
        "traversalRecipes": [
            {"name": "entity_topic_instrument", "useWhen": "User asks about compliance for an insurer type and topic.", "steps": ["Resolve entity", "Filter topics", "List in-force instruments", "Traverse supersession edges"]},
        ],
        "abstentionRules": [
            {"when": "No matching in-force instrument after traversal", "action": "Abstain and cite missing data explicitly"},
            {"when": "Document lacks text analysis and user needs operative clause text", "action": "Point to official PDF; do not invent clause text"},
        ],
        "corpusAnalysis": corpus_analysis,
    }


def attach_llm_artifacts(
    ontology: dict[str, Any],
    catalog: dict[str, Any],
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vocabulary = build_vocabulary(catalog, ontology, text_by_id=text_by_id, document_analyses=document_analyses, corpus_analysis=corpus_analysis)
    grammar = build_grammar(catalog, ontology, text_by_id=text_by_id, document_analyses=document_analyses, corpus_analysis=corpus_analysis)
    llm = dict(ontology.get("llm") or {})
    llm.update({"vocabularyVersion": vocabulary["version"], "grammarVersion": grammar["version"], "systemPromptMap": grammar["systemPrompt"], "vocabulary": vocabulary, "grammar": grammar})
    result = dict(ontology)
    result["llm"] = llm
    return result
