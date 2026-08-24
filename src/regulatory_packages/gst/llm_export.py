"""Generate LLM vocabulary and grammar from GST catalog + ontology artifacts."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from regulatory_packages.gst.taxonomy import (
    CANONICAL_PARENT_INSTRUMENTS,
    DOCUMENT_STATUSES,
    GST_ENTITY_CODES,
    GST_ENTITY_LABELS,
    GST_TOPICS,
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
    {
        "id": "circular",
        "label": "CGST Circulars",
        "section": "CGST Circulars",
        "rank": 3,
        "depthTier": "B",
    },
]

ABBREVIATIONS: dict[str, str] = {
    "CGST": "Central Goods and Services Tax",
    "SGST": "State Goods and Services Tax",
    "IGST": "Integrated Goods and Services Tax",
    "UTGST": "Union Territory Goods and Services Tax",
    "ITC": "Input Tax Credit",
    "ISD": "Input Service Distributor",
    "RCM": "Reverse Charge Mechanism",
    "GSTR": "GST Return",
    "HSN": "Harmonized System of Nomenclature",
    "SAC": "Services Accounting Code",
    "POS": "Place of Supply",
    "CBIC": "Central Board of Indirect Taxes and Customs",
    "DIN": "Document Identification Number",
    "SEZ": "Special Economic Zone",
}

ENTITY_ALIASES: dict[str, list[str]] = {
    "Registered Taxpayer": ["taxpayer", "registered dealer", "normal taxpayer"],
    "Composition Dealer": ["composition scheme", "composition taxpayer"],
    "Input Service Distributor": ["isd", "input service distributor"],
    "E-commerce Operator": ["e-commerce operator", "eco", "tcs operator"],
    "TDS/TCS Deductor": ["tds", "tcs", "deductor"],
    "SEZ Unit / Developer": ["sez", "special economic zone"],
    "Refund Claimant": ["refund", "export refund"],
    "General": ["general", "cross-cutting"],
}

TOPIC_DESCRIPTIONS: dict[str, str] = {
    "Registration": "GSTIN registration, amendments, and cancellation.",
    "Returns (GSTR-1 / 3B / 9 / 9C)": "Periodic and annual return filing obligations.",
    "Input Tax Credit": "Availing, reversal, and matching of input tax credit.",
    "Refunds": "Export, inverted duty structure, and other refund claims.",
    "Transitional / Amnesty (Section 128A)": "Section 128A waiver and transitional compliance.",
}

_QUERY_INTENTS = [
    {
        "intent": "clarify_section",
        "examples": [
            "Which circular clarifies Section 128A?",
            "GST treatment under Section 16 ITC rules",
        ],
    },
    {
        "intent": "return_compliance",
        "examples": [
            "GSTR-9C late fee applicability",
            "Due dates for GSTR-3B filing",
        ],
    },
    {
        "intent": "rate_classification",
        "examples": [
            "GST rate on restaurant services",
            "HSN classification for software services",
        ],
    },
]

_RELATIONSHIP_SEMANTICS: dict[str, dict[str, Any]] = {
    "implements": {
        "direction": "source → target",
        "meaning": "Circular gives effect to or operates under CGST/IGST Act provisions.",
        "traverseBeforeCite": True,
    },
    "clarifies": {
        "direction": "source → target",
        "meaning": "Circular clarifies operative provision, rule, or earlier circular.",
        "traverseBeforeCite": True,
    },
    "supersedes": {
        "direction": "source → target",
        "meaning": "Source replaces target; do not cite superseded circular as operative.",
        "traverseBeforeCite": True,
    },
    "amends": {
        "direction": "source → target",
        "meaning": "Source amends guidance in target instrument.",
        "traverseBeforeCite": True,
    },
    "applies_to": {
        "direction": "document → entity",
        "meaning": "Document applies to taxpayer class or operational role.",
        "traverseBeforeCite": False,
    },
    "cross_references": {
        "direction": "bidirectional",
        "meaning": "Related circular, section, or notification reference.",
        "traverseBeforeCite": False,
    },
    "issued_under": {
        "direction": "document → hub",
        "meaning": "Document belongs to CGST circulars branch.",
        "traverseBeforeCite": False,
    },
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
    stop = {"gst", "goods", "services", "tax", "circular", "section", "shall", "cbic", "government"}
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
        topics = SECTION_TOPIC_HINTS.get(base, SECTION_TOPIC_HINTS.get(section, ["Audit / Assessment / Adjudication"]))
        index.append(
            {
                "id": f"section:cgst:{base.lower()}",
                "title": f"Section {section} of the CGST Act, 2017",
                "shortName": f"Section {section}",
                "year": "2017",
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


def _build_regulation_index(
    documents: list[dict[str, Any]],
    corpus_analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = [dict(item) for item in CANONICAL_PARENT_INSTRUMENTS]
    for doc in documents:
        if doc.get("hierarchy") in {"act", "rule", "regulation", "notification"} and doc.get("title"):
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
                    {"code": code, "label": GST_ENTITY_LABELS.get(code, code), "documentCount": entity_counts.get(code, 0)}
                    for code in GST_ENTITY_CODES
                    if entity_counts.get(code, 0) > 0
                ],
                "topics": [
                    {"id": _slug(topic), "label": topic, "documentCount": topic_counts.get(topic, 0)}
                    for topic in GST_TOPICS
                    if topic_counts.get(topic, 0) > 0
                ],
                "lexicalIndex": _build_lexical_index(section_docs, limit=40),
                "queryIntents": _QUERY_INTENTS,
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
            "defaultPath": "entity → topic → circular",
            "citePreference": [item["hierarchy"]],
            "navigation": {"axes": ["entity", "topic", item["hierarchy"], "section"], "description": f"Navigate GST {item['section']} corpus."},
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
    corpus_analysis = corpus_analysis or (ontology or {}).get("stats", {}).get("corpusAnalysis", {})
    text_count = sum(1 for doc in documents if text_by_id.get(doc.get("id", "")))
    analyzed_count = sum(1 for a in (document_analyses or {}).values() if a.get("textAnalyzed"))
    entity_counts = _count_by_key(documents, "entities")
    topic_counts = _count_by_key(documents, "topics")
    hierarchy_counts = _count_by_key(documents, "hierarchy")
    status_counts = _count_by_key(documents, "status")
    section_counts = _count_by_key(documents, "section")
    relationship_stats = (ontology or {}).get("stats", {}).get("relationshipsByType", {})
    priority_entities = (ontology or {}).get("scope", {}).get("entityPriority", [])
    nicknames = [{"nickname": nickname, **meta} for nickname, meta in PARENT_INSTRUMENT_NICKNAMES.items()]

    entities = [
        {
            "code": code,
            "label": GST_ENTITY_LABELS.get(code, code),
            "description": "",
            "aliases": ENTITY_ALIASES.get(code, [code.lower()]),
            "documentCount": entity_counts.get(code, 0),
            "priority": priority_entities.index(GST_ENTITY_LABELS.get(code, code)) + 1
            if GST_ENTITY_LABELS.get(code, code) in priority_entities
            else None,
        }
        for code in GST_ENTITY_CODES
    ]

    topics = [
        {
            "id": _slug(topic),
            "label": topic,
            "description": TOPIC_DESCRIPTIONS.get(topic, ""),
            "keywords": list(TOPIC_KEYWORDS.get(topic, ())),
            "documentCount": topic_counts.get(topic, 0),
        }
        for topic in GST_TOPICS
    ]

    hierarchies = [
        {
            **meta,
            "documentCount": hierarchy_counts.get(str(meta["id"]), 0),
            "sectionDocumentCount": section_counts.get(str(meta["section"]), 0),
        }
        for meta in HIERARCHY_META
    ]

    return {
        "version": _VOCABULARY_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "source": catalog.get("source", "https://gstcouncil.gov.in/cgst-circulars"),
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
        "sectionVocabularies": _build_section_vocabularies(
            documents, document_analyses=document_analyses, corpus_analysis=corpus_analysis
        ),
        "regulations": _build_regulation_index(documents, corpus_analysis),
        "regulationNicknames": nicknames,
        "relationshipTypes": [
            {
                "type": rel_type,
                "label": rel_type.replace("_", " ").title(),
                "edgeCount": relationship_stats.get(rel_type, 0),
                **(_RELATIONSHIP_SEMANTICS.get(rel_type, {})),
            }
            for rel_type in RELATIONSHIP_TYPES
        ],
        "statuses": [
            {"id": status, "documentCount": status_counts.get(status, 0)}
            for status in DOCUMENT_STATUSES
        ],
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
    section_slices = _build_section_vocabularies(
        documents, document_analyses=document_analyses, corpus_analysis=corpus_analysis
    )

    return {
        "version": _GRAMMAR_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "startSymbol": "RegulatoryAnswer",
        "systemPrompt": (
            "Navigate Indian GST law using CGST circulars from gstcouncil.gov.in. "
            "Filter by taxpayer entity and topic (ITC, returns, refunds, place of supply). "
            "Traverse supersedes/clarifies/implements edges before citing leaf circulars. "
            "Prefer in-force circulars; cite officialId and section references when available."
        ),
        "navigation": {
            "axes": ["entity", "topic", "hierarchy", "circular", "section"],
            "defaultPath": "entity → topic → circular",
            "alternatePaths": [
                "section → circular → entity",
                "topic → circular → officialId",
            ],
            "description": "Resolve GST terms to controlled vocabulary, filter CGST circulars, traverse relationship edges.",
        },
        "citationRules": {
            "preferHierarchies": ["act", "rule", "circular"],
            "avoidStatus": ["superseded"],
            "requireTraversal": ["supersedes", "superseded_by", "clarifies", "amends"],
            "titleField": "title",
            "fallbackFields": ["officialId", "pdfUrl", "sourceUrl"],
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "disclaimer": "Verify operative language in official CBIC/GST Council PDFs before compliance decisions.",
        },
        "relationshipSemantics": _RELATIONSHIP_SEMANTICS,
        "relationshipStats": rel_stats,
        "productions": [
            {
                "nonterminal": "RegulatoryAnswer",
                "description": "Structured GST compliance answer.",
                "productions": ["ScopeStatement CircularChain PrimaryObligation StatusCaveats?"],
            },
            {
                "nonterminal": "CircularChain",
                "description": "Ordered list of operative CGST circulars.",
                "productions": ["CircularRef (implements|clarifies|supersedes CircularRef)*"],
            },
        ],
        "queryIntents": _QUERY_INTENTS,
        "sectionGrammars": _build_section_grammars(section_slices),
        "traversalRecipes": [
            {
                "name": "entity_topic_circular",
                "useWhen": "User asks about compliance for a taxpayer type and topic.",
                "steps": [
                    "Resolve entity code from user query",
                    "Filter topics by keyword match",
                    "List in-force circulars with text analysis",
                    "Traverse supersedes/clarifies edges",
                ],
            },
        ],
        "abstentionRules": [
            {
                "when": "No matching in-force circular after traversal",
                "action": "Abstain and cite missing data explicitly",
            },
            {
                "when": "Conflicting circulars without clear supersession chain",
                "action": "Present both with status caveats; do not merge",
            },
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
    vocabulary = build_vocabulary(
        catalog,
        ontology,
        text_by_id=text_by_id,
        document_analyses=document_analyses,
        corpus_analysis=corpus_analysis,
    )
    grammar = build_grammar(
        catalog, ontology, text_by_id=text_by_id, document_analyses=document_analyses, corpus_analysis=corpus_analysis
    )
    llm = dict(ontology.get("llm") or {})
    llm.update(
        {
            "vocabularyVersion": vocabulary["version"],
            "grammarVersion": grammar["version"],
            "systemPromptMap": grammar["systemPrompt"],
            "vocabulary": vocabulary,
            "grammar": grammar,
        }
    )
    result = dict(ontology)
    result["llm"] = llm
    return result
