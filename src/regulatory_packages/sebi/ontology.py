"""Assemble PRD-aligned ontology graph from enriched catalog."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from regulatory_packages.sebi.document_analysis import aggregate_corpus_signals, analyze_corpus
from regulatory_packages.sebi.relationships import build_relationships
from regulatory_packages.sebi.text_relationships import merge_relationships
from regulatory_packages.sebi.llm_export import attach_llm_artifacts
from regulatory_packages.sebi.taxonomy import SEBI_ENTITY_LABELS, SEBI_TOPICS, taxonomy_schema

_HUB_ID = "hub:sebi-legal-corpus"
_HIERARCHY_HUBS = {
    "act": ("hub:acts", "Acts"),
    "rule": ("hub:rules", "Rules"),
    "regulation": ("hub:regulations", "Regulations"),
    "general_order": ("hub:general-orders", "General Orders"),
    "guidance_note": ("hub:guidelines", "Guidelines"),
    "master_circular": ("hub:master-circulars", "Master Circulars"),
    "circular": ("hub:circulars", "Circulars"),
    "gazette_notification": ("hub:gazette", "Gazette Notifications"),
}


def _parse_sebi_date(raw: str) -> str:
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return raw.strip()


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
            "label": "SEBI Legal Corpus",
            "sublabel": f"{len(documents)} documents · Acts → Regulations → Master Circulars → Circulars",
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
                "label": SEBI_ENTITY_LABELS.get(code, code),
                "entityCode": code,
            }
        )

    for topic in SEBI_TOPICS:
        slug = topic.lower()
        if any(slug == t.lower() for doc in documents for t in doc.get("topics", [])):
            nodes.append({"id": f"topic:{slug}", "kind": "topic", "label": topic})

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
                "entryId": doc.get("entryId"),
                "section": doc.get("section"),
                "hierarchy": doc.get("hierarchy"),
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "summary": summary,
                "status": doc.get("status", "in_force"),
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
                "issuedAt": _parse_sebi_date(doc.get("issuedAt", "")),
                "hierarchy": doc.get("hierarchy"),
                "entities": [SEBI_ENTITY_LABELS.get(c, c) for c in entities],
                "topics": topics,
                "depthTier": "A" if analysis.get("textAnalyzed") else doc.get("depthTier", "B"),
                "status": doc.get("status", "in_force"),
                "summary": summary,
                "section": doc.get("section"),
                "entryId": doc.get("entryId"),
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
                SEBI_ENTITY_LABELS.get("AIF", "AIF"),
                SEBI_ENTITY_LABELS["Mutual Funds"],
                SEBI_ENTITY_LABELS["Stock Brokers"],
            ],
            "timeHorizon": "in_force",
            "defaultDepthTier": "B",
            "outputFormat": "json",
            "verticalSliceEntity": SEBI_ENTITY_LABELS.get("AIF", "AIF"),
        },
        "taxonomy": taxonomy,
        "documents": regulatory_documents,
        "nodes": nodes,
        "edges": edges,
        "batches": [
            {
                "id": "batch-sebi-enriched",
                "label": "Enriched SEBI legal corpus",
                "entityFocus": "All intermediaries",
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
                "Navigate SEBI rules by entity → topic → legal hierarchy. "
                "Use document.analysis (definitions, obligations, crossReferences) when present. "
                "Traverse implements/amends/supersedes/repeals edges before citing leaf circulars. "
                "Prefer in-force Master Circulars and Regulations as parent nodes."
            ),
            "sampleQueries": [
                "What regulations govern AIFs?",
                "Which circulars implement the AIF Regulations?",
                "What master circular consolidates mutual fund disclosure rules?",
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
