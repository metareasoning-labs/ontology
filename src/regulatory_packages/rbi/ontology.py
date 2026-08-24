"""Assemble RBI ontology graph from catalog and corpus analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from regulatory_packages.rbi.document_analysis import aggregate_corpus_signals, analyze_corpus
from regulatory_packages.rbi.llm_export import attach_llm_artifacts
from regulatory_packages.rbi.relationships import build_relationships
from regulatory_packages.rbi.text_relationships import merge_relationships
from regulatory_packages.rbi.taxonomy import RBI_ENTITY_LABELS, taxonomy_schema

_HUB_ID = "hub:rbi-notifications-corpus"
_RBI_ACT_HUB = "hub:rbi-act"


def _parse_rbi_date(raw: str) -> str:
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%b %d, %Y"):
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
            "label": "RBI Notifications & Directions",
            "sublabel": f"{len(documents)} instruments · rbi.org.in",
        },
        {
            "id": "hub:notifications",
            "kind": "hierarchy",
            "label": "Notifications",
            "sublabel": f"{sum(1 for d in documents if d.get('hierarchy') == 'notification')} documents",
            "hierarchy": "notification",
        },
        {
            "id": _RBI_ACT_HUB,
            "kind": "act",
            "label": "RBI Act, 1934",
            "sublabel": "Reserve Bank of India Act, 1934",
        },
    ]

    entity_codes = sorted({code for doc in documents for code in doc.get("entities", [])})
    for code in entity_codes:
        nodes.append(
            {
                "id": f"entity:{code}",
                "kind": "entity",
                "label": RBI_ENTITY_LABELS.get(code, code),
                "entityCode": code,
            }
        )

    for topic in taxonomy.get("topics", []):
        if any(topic in doc.get("topics", []) for doc in documents):
            nodes.append({"id": f"topic:{topic.lower()}", "kind": "topic", "label": topic})

    for doc in documents:
        text = (text_by_id or {}).get(doc["id"], "")
        analysis = document_analyses.get(doc["id"], {})
        summary = analysis.get("narrativeSummary") or analysis.get("summaryFromText") or doc.get("summary")
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
                "textExtracted": bool(text),
                "textCharCount": len(text) if text else 0,
                "textAnalyzed": bool(analysis.get("textAnalyzed")),
                "obligationCount": analysis.get("obligationCount"),
                "definitionCount": analysis.get("definitionCount"),
            }
        )
        edges.append(
            {
                "id": f"member:{doc['id']}:{_HUB_ID}",
                "type": "issued_under",
                "sourceId": doc["id"],
                "targetId": _HUB_ID,
                "note": doc.get("section"),
            }
        )

    regulatory_documents = []
    for doc in documents:
        analysis = document_analyses.get(doc["id"], {})
        summary = analysis.get("narrativeSummary") or analysis.get("summaryFromText") or doc.get("summary", "")
        entities = list(doc.get("entities", []))
        topics = list(doc.get("topics", []))
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
                "issuedAt": _parse_rbi_date(doc.get("issuedAt", "")),
                "hierarchy": doc.get("hierarchy"),
                "entities": [RBI_ENTITY_LABELS.get(c, c) for c in entities],
                "topics": topics,
                "depthTier": "A" if analysis.get("textAnalyzed") else doc.get("depthTier", "B"),
                "status": doc.get("status", "in_force"),
                "summary": summary,
                "section": doc.get("section"),
                "sectionRefs": doc.get("sectionRefs") or analysis.get("sectionRefsFromText") or [],
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
    corpus_analysis = aggregate_corpus_signals(document_analyses) if document_analyses else {}

    ontology: dict[str, Any] = {
        "version": 5 if analyzed_count else (3 if text_count else 2),
        "builtAt": now,
        "scope": {
            "consumerMode": "hybrid",
            "entityPriority": [
                RBI_ENTITY_LABELS["Commercial Banks"],
                RBI_ENTITY_LABELS["NBFC"],
            ],
            "timeHorizon": "in_force",
            "defaultDepthTier": "B",
            "outputFormat": "json",
            "verticalSliceEntity": RBI_ENTITY_LABELS["Commercial Banks"],
        },
        "taxonomy": taxonomy,
        "documents": regulatory_documents,
        "nodes": nodes,
        "edges": edges,
        "batches": [
            {
                "id": "batch-rbi-notifications",
                "label": "RBI Notifications & Master Directions",
                "entityFocus": "All regulated entities",
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
                "Navigate RBI prudential and regulatory law via notifications, master directions, "
                "and master circulars from rbi.org.in. Use document.analysis (definitions, obligations, "
                "crossReferences) when present. Traverse supersedes/clarifies/implements edges; cite officialId."
            ),
            "sampleQueries": [
                "Which master direction governs concurrent audit for commercial banks?",
                "RBI KYC norms for NBFCs",
                "Cybersecurity framework directions for scheduled commercial banks",
            ],
        },
        "maintenance": {
            "refreshCadence": "monthly",
            "lastRefreshAt": catalog.get("fetchedAt") or now,
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
