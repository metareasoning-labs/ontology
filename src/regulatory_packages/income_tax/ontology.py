"""Assemble Income Tax ontology graph from enriched catalog."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from regulatory_packages.income_tax.document_analysis import aggregate_corpus_signals, analyze_corpus
from regulatory_packages.income_tax.llm_export import attach_llm_artifacts
from regulatory_packages.income_tax.relationships import build_relationships
from regulatory_packages.income_tax.sources import CATALOG_SECTIONS
from regulatory_packages.income_tax.taxonomy import IT_ASSESSEE_LABELS, IT_TOPICS, taxonomy_schema
from regulatory_packages.income_tax.text_relationships import merge_relationships

_HUB_ID = "hub:itd-corpus"
_HIERARCHY_HUBS = {
    "act": ("hub:acts", "Acts"),
    "rule": ("hub:rules", "Rules"),
    "provision": ("hub:provisions", "Provisions"),
    "circular": ("hub:circulars", "Circulars"),
    "notification": ("hub:notifications", "Notifications"),
    "finance_act": ("hub:finance-acts", "Finance Acts"),
    "finance_bill": ("hub:finance-bills", "Finance Bills"),
    "whats_new": ("hub:whats-new", "What's New"),
    "tax_calendar": ("hub:tax-calendar", "Tax Calendar"),
    "faq": ("hub:faqs", "FAQs"),
    "international": ("hub:international", "International Taxation"),
}


def build_ontology(
    catalog: dict[str, Any],
    *,
    text_by_id: dict[str, str] | None = None,
    edges: list[dict[str, Any]] | None = None,
    corpus_stats: dict[str, int] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    documents = [doc for doc in catalog.get("documents", []) if doc.get("title")]
    taxonomy = taxonomy_schema()
    if document_analyses is None and text_by_id:
        document_analyses = analyze_corpus(documents, text_by_id)
    document_analyses = document_analyses or {}
    if edges is None:
        edges = merge_relationships(documents, text_by_id=text_by_id) if text_by_id else build_relationships(documents)

    nodes: list[dict[str, Any]] = [
        {
            "id": _HUB_ID,
            "kind": "hub",
            "label": "Income Tax Department Corpus",
            "sublabel": f"{len(documents)} documents · incometaxindia.gov.in",
        }
    ]

    for hierarchy, (hub_id, label) in _HIERARCHY_HUBS.items():
        count = sum(1 for doc in documents if doc.get("hierarchy") == hierarchy)
        if not count:
            continue
        nodes.append(
            {
                "id": hub_id,
                "kind": "hierarchy",
                "label": label,
                "sublabel": f"{count} documents",
                "hierarchy": hierarchy,
            }
        )
        edges.append(
            {
                "id": f"issued_under:{hub_id}",
                "type": "issued_under",
                "sourceId": hub_id,
                "targetId": _HUB_ID,
                "note": "Legal hierarchy branch",
            }
        )

    entity_codes = sorted({code for doc in documents for code in doc.get("entities", [])})
    for code in entity_codes:
        nodes.append(
            {
                "id": f"entity:{code}",
                "kind": "entity",
                "label": IT_ASSESSEE_LABELS.get(code, code),
                "entityCode": code,
            }
        )

    for topic in IT_TOPICS:
        if any(topic in doc.get("topics", []) for doc in documents):
            nodes.append({"id": f"topic:{topic.lower()}", "kind": "topic", "label": topic})

    for doc in documents:
        text = (text_by_id or {}).get(doc["id"], "")
        analysis = document_analyses.get(doc["id"], {})
        summary = analysis.get("summaryFromText") or doc.get("summary")
        nodes.append(
            {
                "id": doc["id"],
                "kind": "document",
                "label": doc.get("shortTitle") or doc.get("title", ""),
                "title": doc.get("title"),
                "date": doc.get("issuedAt"),
                "url": doc.get("sourceUrl"),
                "pdfUrl": doc.get("pdfUrl"),
                "officialId": doc.get("officialId"),
                "section": doc.get("section"),
                "hierarchy": doc.get("hierarchy"),
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "summary": summary,
                "status": doc.get("status", "in_force"),
                "sectionRefs": doc.get("sectionRefs", []),
                "textExtracted": bool(text),
                "textCharCount": len(text) if text else 0,
                "textAnalyzed": bool(analysis.get("textAnalyzed")),
                "obligationCount": analysis.get("obligationCount"),
                "definitionCount": analysis.get("definitionCount"),
            }
        )
        hub = _HIERARCHY_HUBS.get(doc.get("hierarchy", "circular"))
        if hub:
            hub_id, _ = hub
            edges.append(
                {
                    "id": f"member:{doc['id']}:{hub_id}",
                    "type": "issued_under",
                    "sourceId": doc["id"],
                    "targetId": hub_id,
                    "note": doc.get("section"),
                }
            )

    regulatory_documents = []
    for doc in documents:
        analysis = document_analyses.get(doc["id"], {})
        summary = analysis.get("narrativeSummary") or analysis.get("summaryFromText") or doc.get("summary", "")
        entities = doc.get("entities", [])
        topics = doc.get("topics", [])
        if analysis.get("entitiesFromText"):
            entities = sorted(set(entities) | set(analysis["entitiesFromText"]))
        if analysis.get("topicsFromText"):
            topics = sorted(set(topics) | set(analysis["topicsFromText"]), key=str.lower)
        regulatory_documents.append(
            {
                "id": doc["id"],
                "title": doc["title"],
                "officialId": doc.get("officialId"),
                "sourceUrl": doc.get("sourceUrl"),
                "pdfUrl": doc.get("pdfUrl"),
                "issuedAt": doc.get("issuedAt", ""),
                "hierarchy": doc.get("hierarchy"),
                "entities": [IT_ASSESSEE_LABELS.get(c, c) for c in entities],
                "topics": topics,
                "depthTier": "A" if analysis.get("textAnalyzed") else doc.get("depthTier", "B"),
                "status": doc.get("status", "in_force"),
                "summary": summary,
                "section": doc.get("section"),
                "sectionRefs": doc.get("sectionRefs", []),
                "textExtracted": bool((text_by_id or {}).get(doc["id"])),
                "textCharCount": len((text_by_id or {}).get(doc["id"], "")),
                "analysis": analysis if analysis.get("textAnalyzed") else None,
            }
        )

    now = datetime.now(timezone.utc).isoformat()
    rel_counts: dict[str, int] = {}
    for edge in edges:
        rel_counts[edge["type"]] = rel_counts.get(edge["type"], 0) + 1

    text_count = sum(1 for doc in documents if (text_by_id or {}).get(doc["id"]))
    analyzed_count = sum(1 for a in document_analyses.values() if a.get("textAnalyzed"))
    ontology_version = 4 if analyzed_count else (3 if text_count else 2)
    corpus_analysis = aggregate_corpus_signals(document_analyses) if document_analyses else {}

    ontology: dict[str, Any] = {
        "version": ontology_version,
        "builtAt": now,
        "scope": {
            "consumerMode": "hybrid",
            "entityPriority": [
                IT_ASSESSEE_LABELS["Individual"],
                IT_ASSESSEE_LABELS["Domestic Company"],
                IT_ASSESSEE_LABELS["Non-Resident"],
            ],
            "timeHorizon": "in_force",
            "defaultDepthTier": "B",
            "outputFormat": "json",
            "verticalSliceEntity": IT_ASSESSEE_LABELS["Individual"],
        },
        "taxonomy": taxonomy,
        "documents": regulatory_documents,
        "nodes": nodes,
        "edges": edges,
        "batches": [
            {
                "id": "batch-itd-corpus",
                "label": "Income Tax Department public corpus",
                "entityFocus": "All assessee types",
                "documentCount": len(documents),
                "depthTier": "B",
                "status": "complete",
                "createdAt": now,
            }
        ],
        "llm": {
            "chunkSummariesOnly": analyzed_count == 0,
            "metadataPrefilter": analyzed_count == 0,
            "textAnalyzedCount": analyzed_count,
            "systemPromptMap": (
                "Navigate Indian income tax law by assessee type → topic → hierarchy "
                "(Act/Rule/Provision → Circular/Notification → FAQ/Calendar). "
                "Use document.analysis when present for obligations, definitions, and cross-references."
            ),
            "sampleQueries": [
                "What are TDS due dates for FY 2025-26?",
                "Which circular clarifies Section 194C?",
                "DTAA withholding rates for US investors",
            ],
        },
        "maintenance": {
            "refreshCadence": "monthly",
            "lastRefreshAt": catalog.get("enrichedAt") or catalog.get("fetchedAt") or now,
            "supersessionTracking": True,
        },
        "stats": {
            "documents": len(documents),
            "nodes": len(nodes),
            "edges": len(edges),
            "entities": len(entity_codes),
            "topics": len({t for doc in documents for t in doc.get("topics", [])}),
            "relationshipsByType": rel_counts,
            "sections": catalog.get("sectionStats", {}),
            "catalogSections": [s.name for s in CATALOG_SECTIONS],
            "textExtracted": text_count,
            "textAnalyzed": analyzed_count,
            "corpusAnalysis": corpus_analysis,
            "corpus": corpus_stats or {},
        },
    }
    return attach_llm_artifacts(
        ontology,
        catalog,
        text_by_id=text_by_id,
        document_analyses=document_analyses,
        corpus_analysis=corpus_analysis,
    )
