"""Infer GST regulatory relationships from extracted PDF/text bodies."""

from __future__ import annotations

import re
from typing import Any

from regulatory_packages.gst.relationships import DocumentIndex, build_relationships

_SUPERSEDES_PATTERNS = [
    re.compile(r"\b(?:hereby\s+)?supersed(?:e|es|ing)\b[^.\n]{0,120}", re.I),
]
_AMENDS_PATTERNS = [
    re.compile(r"\bamend(?:s|ment|ing)\b[^.\n]{0,120}", re.I),
]
_CLARIFIES_PATTERNS = [
    re.compile(r"\bclarif(?:y|ies|ied|ication)\b[^.\n]{0,120}", re.I),
    re.compile(r"\bfor\s+removal\s+of\s+doubts\b[^.\n]{0,80}", re.I),
]
_IMPLEMENTS_PATTERNS = [
    re.compile(r"\bpursuant\s+to\b[^.\n]{0,120}", re.I),
    re.compile(r"\bunder\s+the\s+provisions\s+of\b[^.\n]{0,120}", re.I),
    re.compile(r"\bsection\s+\d+[A-Za-z()0-9]*\s+of\s+the\s+(?:CGST|IGST|SGST|UTGST)\s+Act\b", re.I),
]
_CIRCULAR_REF_RE = re.compile(r"circular\s+no\.?\s*:?\s*([0-9/\-A-Za-z]+)", re.I)
_SECTION_REF_RE = re.compile(r"\bsection\s+(\d+[A-Za-z]*(?:\(\d+\))?(?:\([a-z]\))?)\b", re.I)


def _snippet(text: str, start: int, width: int = 160) -> str:
    fragment = text[max(0, start - 40) : start + width]
    return re.sub(r"\s+", " ", fragment).strip()


def _match_targets(index: DocumentIndex, text: str, *, source_doc: dict[str, Any]) -> list[tuple[str, str, float]]:
    hits: list[tuple[str, str, float]] = []
    source_id = source_doc.get("id")
    hits.extend(index.match_official_refs(text))
    for match in _SECTION_REF_RE.finditer(text):
        ref = match.group(1).lower()
        target = index.by_section.get(ref)
        if target and target != source_id:
            hits.append((target, f"Section {match.group(1)} reference", 0.84))
    best: dict[str, tuple[str, float]] = {}
    for target_id, evidence, confidence in hits:
        if target_id not in best or confidence > best[target_id][1]:
            best[target_id] = (evidence, confidence)
    return [(target_id, evidence, confidence) for target_id, (evidence, confidence) in best.items()]


def infer_text_relationships(
    documents: list[dict[str, Any]],
    text_by_id: dict[str, str],
    *,
    index: DocumentIndex | None = None,
) -> list[dict[str, Any]]:
    lookup = index or DocumentIndex(documents)
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(
        source_id: str,
        target_id: str,
        rel_type: str,
        *,
        evidence: str,
        confidence: float,
    ) -> None:
        if source_id == target_id:
            return
        key = (source_id, target_id, rel_type)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "id": f"{rel_type}:{source_id}:{target_id}",
                "type": rel_type,
                "sourceId": source_id,
                "targetId": target_id,
                "note": evidence,
                "evidence": evidence,
                "confidence": confidence,
                "sourceKind": "text",
            }
        )
        if rel_type == "supersedes":
            add(target_id, source_id, "superseded_by", evidence=evidence, confidence=confidence)

    pattern_map = [
        (_SUPERSEDES_PATTERNS, "supersedes", 0.82),
        (_AMENDS_PATTERNS, "amends", 0.8),
        (_CLARIFIES_PATTERNS, "clarifies", 0.76),
        (_IMPLEMENTS_PATTERNS, "implements", 0.74),
    ]

    for doc in documents:
        doc_id = doc["id"]
        text = text_by_id.get(doc_id, "")
        if not text or len(text) < 40:
            continue
        targets = _match_targets(lookup, text, source_doc=doc)
        for patterns, rel_type, base_confidence in pattern_map:
            for pattern in patterns:
                match = pattern.search(text)
                if not match:
                    continue
                evidence = _snippet(text, match.start())
                if not targets:
                    break
                for target_id, target_evidence, target_conf in targets[:6]:
                    confidence = min(0.95, (base_confidence + target_conf) / 2)
                    add(doc_id, target_id, rel_type, evidence=f"{evidence} | {target_evidence}", confidence=confidence)
                break
    return edges


def merge_relationships(
    documents: list[dict[str, Any]],
    *,
    text_by_id: dict[str, str] | None = None,
    persisted_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in build_relationships(documents):
        key = (edge["sourceId"], edge["targetId"], edge["type"])
        merged[key] = edge
    if text_by_id:
        lookup = DocumentIndex(documents)
        for edge in infer_text_relationships(documents, text_by_id, index=lookup):
            key = (edge["sourceId"], edge["targetId"], edge["type"])
            existing = merged.get(key)
            if existing and existing.get("sourceKind") == "text":
                continue
            merged[key] = edge
    if persisted_edges:
        for edge in persisted_edges:
            key = (edge["sourceId"], edge["targetId"], edge["type"])
            merged[key] = edge
    return list(merged.values())
