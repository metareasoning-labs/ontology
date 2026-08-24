"""Generate LLM vocabulary and grammar from RBI catalog + ontology artifacts."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from regulatory_packages.rbi.taxonomy import (
    CANONICAL_PARENT_INSTRUMENTS,
    DOCUMENT_STATUSES,
    RBI_ENTITY_CODES,
    RBI_ENTITY_LABELS,
    RBI_TOPICS,
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
        "id": "notification",
        "label": "RBI Notifications",
        "section": "Notifications",
        "rank": 3,
        "depthTier": "B",
    },
    {
        "id": "master_direction",
        "label": "Master Directions",
        "section": "Master Directions",
        "rank": 2,
        "depthTier": "A",
    },
    {
        "id": "master_circular",
        "label": "Master Circulars",
        "section": "Master Circulars",
        "rank": 2,
        "depthTier": "A",
    },
]

ABBREVIATIONS: dict[str, str] = {
    "RBI": "Reserve Bank of India",
    "NBFC": "Non-Banking Financial Company",
    "FEMA": "Foreign Exchange Management Act",
    "KYC": "Know Your Customer",
    "AML": "Anti-Money Laundering",
    "CFT": "Combating the Financing of Terrorism",
    "NPA": "Non-Performing Asset",
    "CRAR": "Capital to Risk-weighted Assets Ratio",
    "ALM": "Asset Liability Management",
    "UCB": "Urban Co-operative Bank",
    "RRB": "Regional Rural Bank",
    "PPI": "Prepaid Payment Instrument",
    "UPI": "Unified Payments Interface",
}

ENTITY_ALIASES: dict[str, list[str]] = {
    "Commercial Banks": ["scheduled commercial bank", "scb", "commercial bank"],
    "Small Finance Banks": ["sfb", "small finance bank"],
    "Payments Banks": ["payments bank"],
    "Urban Co-operative Banks": ["ucb", "urban cooperative bank"],
    "Rural Co-operative Banks": ["rural cooperative bank"],
    "Regional Rural Banks": ["rrb", "regional rural bank"],
    "NBFC": ["nbfc", "non-banking financial company"],
    "Foreign Exchange": ["fema", "foreign exchange"],
    "Payment Systems": ["payment system", "ppi"],
    "General": ["general", "cross-cutting"],
}

TOPIC_DESCRIPTIONS: dict[str, str] = {
    "Capital Adequacy / Basel": "Capital adequacy, CRAR, and Basel norms for regulated entities.",
    "Asset Classification / NPA": "Income recognition, asset classification, provisioning, and stressed assets.",
    "Governance / Board": "Board composition, fit-and-proper criteria, and corporate governance.",
    "KYC / AML / CFT": "Customer due diligence, AML/CFT, and sanctions compliance.",
    "Cybersecurity / IT Risk": "Technology risk, cybersecurity, and IT governance frameworks.",
    "Audit / Concurrent / Statutory": "Statutory, concurrent, and internal audit requirements.",
    "Fraud Risk Management": "Fraud prevention, detection, and reporting frameworks.",
    "Foreign Exchange / FEMA": "Foreign exchange transactions, AP Dir, export/import compliance.",
    "Payment Systems / NEFT / RTGS": "Payment system operators, NEFT, RTGS, and settlement.",
    "Supervisory Returns": "Regulatory reporting and supervisory return submissions.",
    "Liquidity / ALM": "Asset-liability management, LCR, NSFR, and liquidity risk.",
    "Financial Statements / Disclosure": "Financial statement presentation and disclosure norms.",
}

_SECTION_QUERY_INTENTS: dict[str, list[dict[str, Any]]] = {
    "Notifications": [
        {
            "intent": "notification_lookup",
            "examples": [
                "Latest RBI notification on UAPA Section 51A implementation",
                "RBI notification on interest rate on deposits",
            ],
            "citePreference": ["notification"],
        },
    ],
    "Master Directions": [
        {
            "intent": "master_direction_lookup",
            "examples": [
                "Which master direction governs concurrent audit for commercial banks?",
                "RBI cybersecurity framework for scheduled commercial banks",
            ],
            "citePreference": ["master_direction"],
        },
    ],
    "Master Circulars": [
        {
            "intent": "master_circular_consolidation",
            "examples": [
                "Latest master circular on priority sector lending",
                "Consolidated KYC master circular for regulated entities",
            ],
            "citePreference": ["master_circular"],
        },
    ],
}

_QUERY_INTENTS = [
    {
        "intent": "master_direction_lookup",
        "examples": [
            "Which master direction governs concurrent audit for commercial banks?",
            "RBI cybersecurity framework for scheduled commercial banks",
        ],
    },
    {
        "intent": "entity_compliance",
        "examples": [
            "KYC norms applicable to NBFCs",
            "Asset classification norms for urban co-operative banks",
        ],
    },
    {
        "intent": "supersession_chain",
        "examples": [
            "Which notification supersedes earlier fraud risk management circular?",
            "Latest master circular on priority sector lending",
        ],
    },
]

_RELATIONSHIP_SEMANTICS: dict[str, dict[str, Any]] = {
    "implements": {
        "direction": "source → target",
        "meaning": "Notification or direction gives effect to RBI Act, BR Act, or FEMA provisions.",
        "traverseBeforeCite": True,
    },
    "clarifies": {
        "direction": "source → target",
        "meaning": "Instrument clarifies operative provision or earlier circular/direction.",
        "traverseBeforeCite": True,
    },
    "supersedes": {
        "direction": "source → target",
        "meaning": "Source replaces target; do not cite superseded instrument as operative.",
        "traverseBeforeCite": True,
    },
    "amends": {
        "direction": "source → target",
        "meaning": "Source amends guidance in target instrument.",
        "traverseBeforeCite": True,
    },
    "applies_to": {
        "direction": "document → entity",
        "meaning": "Document applies to regulated entity class.",
        "traverseBeforeCite": False,
    },
    "cross_references": {
        "direction": "bidirectional",
        "meaning": "Related notification, circular, or direction reference.",
        "traverseBeforeCite": False,
    },
    "issued_under": {
        "direction": "document → hub",
        "meaning": "Document belongs to RBI notifications or directions corpus.",
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
    stop = {"rbi", "bank", "reserve", "circular", "section", "shall", "direction", "notification", "master"}
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
        topics = SECTION_TOPIC_HINTS.get(base, SECTION_TOPIC_HINTS.get(section, ["Governance / Board"]))
        index.append(
            {
                "id": f"section:rbi-act:{base.lower()}",
                "title": f"Section {section} of the RBI Act, 1934",
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
    """Per-section vocabulary slice (Notifications, Master Directions, Master Circulars)."""
    document_analyses = document_analyses or {}
    section_slices: list[dict[str, Any]] = []
    for section in HIERARCHY_BY_SECTION:
        section_docs = [doc for doc in documents if doc.get("section") == section]
        if not section_docs:
            continue
        entity_counts = _count_by_key(section_docs, "entities")
        topic_counts = _count_by_key(section_docs, "topics")
        analyzed = sum(
            1
            for doc in section_docs
            if document_analyses.get(doc["id"], {}).get("textAnalyzed")
        )
        section_slices.append(
            {
                "section": section,
                "hierarchy": HIERARCHY_BY_SECTION[section],
                "documentCount": len(section_docs),
                "textAnalyzedCount": analyzed,
                "entities": [
                    {
                        "code": code,
                        "label": RBI_ENTITY_LABELS.get(code, code),
                        "documentCount": entity_counts.get(code, 0),
                    }
                    for code in RBI_ENTITY_CODES
                    if entity_counts.get(code, 0) > 0
                ],
                "topics": [
                    {
                        "id": _slug(topic),
                        "label": topic,
                        "documentCount": topic_counts.get(topic, 0),
                    }
                    for topic in RBI_TOPICS
                    if topic_counts.get(topic, 0) > 0
                ],
                "lexicalIndex": _build_lexical_index(section_docs, limit=40),
                "queryIntents": _SECTION_QUERY_INTENTS.get(section, []),
                "obligationSamples": (corpus_analysis or {}).get("obligationSamples", [])[:8],
            }
        )
    return section_slices


def _build_section_grammars(section_slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grammars: list[dict[str, Any]] = []
    for section_vocab in section_slices:
        section = section_vocab["section"]
        hierarchy = section_vocab["hierarchy"]
        grammars.append(
            {
                "section": section,
                "hierarchy": hierarchy,
                "startSymbol": "RegulatoryAnswer",
                "defaultPath": "entity → topic → instrument",
                "citePreference": [hierarchy],
                "navigation": {
                    "axes": ["entity", "topic", hierarchy, "section"],
                    "description": f"Navigate {section} corpus slice on rbi.org.in.",
                },
                "queryIntents": section_vocab.get("queryIntents", []),
            }
        )
    return grammars


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
            "label": RBI_ENTITY_LABELS.get(code, code),
            "description": "",
            "aliases": ENTITY_ALIASES.get(code, [code.lower()]),
            "documentCount": entity_counts.get(code, 0),
            "priority": priority_entities.index(RBI_ENTITY_LABELS.get(code, code)) + 1
            if RBI_ENTITY_LABELS.get(code, code) in priority_entities
            else None,
        }
        for code in RBI_ENTITY_CODES
    ]

    topics = [
        {
            "id": _slug(topic),
            "label": topic,
            "description": TOPIC_DESCRIPTIONS.get(topic, ""),
            "keywords": list(TOPIC_KEYWORDS.get(topic, ())),
            "documentCount": topic_counts.get(topic, 0),
        }
        for topic in RBI_TOPICS
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
        "source": catalog.get("source", "https://www.rbi.org.in/Scripts/NotificationUser.aspx"),
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
            documents,
            document_analyses=document_analyses,
            corpus_analysis=corpus_analysis,
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
    corpus_analysis = corpus_analysis or (ontology or {}).get("stats", {}).get("corpusAnalysis", {})
    text_count = sum(1 for doc in documents if text_by_id.get(doc.get("id", "")))
    analyzed_count = int(corpus_analysis.get("documentsAnalyzed") or 0)
    rel_stats = (ontology or {}).get("stats", {}).get("relationshipsByType", {})

    section_slices = _build_section_vocabularies(
        documents,
        document_analyses=document_analyses,
        corpus_analysis=corpus_analysis,
    )

    return {
        "version": _GRAMMAR_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "startSymbol": "RegulatoryAnswer",
        "systemPrompt": (
            "Navigate Indian RBI prudential and regulatory law using notifications, master directions, "
            "and master circulars from rbi.org.in. Filter by regulated entity class and topic "
            "(KYC, capital adequacy, audit, cybersecurity, fraud risk, payment systems). "
            "Traverse supersedes/clarifies/implements/amends edges before citing leaf instruments. "
            "Prefer in-force master directions and master circulars; cite officialId and section references."
        ),
        "navigation": {
            "axes": ["entity", "topic", "hierarchy", "section", "instrument"],
            "defaultPath": "entity → topic → instrument",
            "alternatePaths": [
                "section → entity → instrument",
                "topic → master_direction → officialId",
                "section → hierarchy → instrument",
            ],
            "description": "Resolve RBI terms to controlled vocabulary, filter by section and hierarchy, traverse relationship edges.",
        },
        "citationRules": {
            "preferHierarchies": ["act", "master_direction", "master_circular", "notification"],
            "avoidStatus": ["superseded"],
            "requireTraversal": ["supersedes", "superseded_by", "clarifies", "amends", "implements"],
            "titleField": "title",
            "fallbackFields": ["officialId", "pdfUrl", "sourceUrl"],
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "disclaimer": "Verify operative language in official RBI/rbidocs PDFs before compliance decisions.",
        },
        "relationshipSemantics": _RELATIONSHIP_SEMANTICS,
        "relationshipStats": rel_stats,
        "productions": [
            {
                "nonterminal": "RegulatoryAnswer",
                "description": "Structured RBI compliance answer.",
                "productions": ["ScopeStatement InstrumentChain PrimaryObligation StatusCaveats?"],
            },
            {
                "nonterminal": "InstrumentChain",
                "description": "Ordered list of operative RBI instruments.",
                "productions": ["InstrumentRef (implements|clarifies|supersedes|amends InstrumentRef)*"],
            },
            {
                "nonterminal": "InstrumentRef",
                "description": "Reference to an RBI notification, master direction, or master circular.",
                "productions": [
                    "HierarchyTag DocumentTitle ( '(' OfficialId | DateRef ')' )?",
                    "DocumentId",
                ],
                "constraints": [
                    "Use full document title from corpus.",
                    "Include officialId, sourceUrl, or pdfUrl when available.",
                    "Skip documents with status=superseded unless user asks for history.",
                ],
            },
            {
                "nonterminal": "HierarchyTag",
                "description": "Instrument type badge.",
                "productions": [
                    "'Notification' | 'Master Direction' | 'Master Circular' | 'Direction' | 'Act'",
                ],
            },
            {
                "nonterminal": "HierarchyPrecedenceRule",
                "description": "Conflict resolution by legal hierarchy.",
                "productions": [
                    "'prefer' MasterDirectionRef 'over' NotificationRef",
                    "'prefer' MasterCircularRef 'over' CircularRef",
                    "'Act provisions prevail over circular/direction guidance'",
                ],
            },
        ],
        "queryIntents": _QUERY_INTENTS,
        "sectionGrammars": _build_section_grammars(section_slices),
        "traversalRecipes": [
            {
                "name": "entity_topic_instrument",
                "useWhen": "User asks about compliance for a regulated entity and topic.",
                "steps": [
                    "Resolve entity code from user query",
                    "Filter topics by keyword match",
                    "List in-force instruments with text analysis",
                    "Traverse supersedes/clarifies/implements edges",
                ],
            },
            {
                "name": "section_master_direction",
                "useWhen": "User asks about master directions for a specific entity class.",
                "steps": [
                    "Filter section=Master Directions",
                    "Match entity from title or entitiesFromText",
                    "Prefer depthTier A documents with analysis.obligations",
                ],
            },
        ],
        "abstentionRules": [
            {
                "when": "No matching in-force instrument after traversal",
                "action": "Abstain and cite missing data explicitly",
            },
            {
                "when": "Conflicting instruments without clear supersession chain",
                "action": "Present both with status caveats; do not merge",
            },
            {
                "when": "Document lacks text analysis and user needs operative clause text",
                "action": "Point to official PDF via pdfUrl; do not invent clause text",
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
        catalog,
        ontology,
        text_by_id=text_by_id,
        document_analyses=document_analyses,
        corpus_analysis=corpus_analysis,
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
