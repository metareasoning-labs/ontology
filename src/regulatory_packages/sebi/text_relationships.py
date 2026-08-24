"""Infer SEBI regulatory relationships from extracted PDF/text bodies."""

from __future__ import annotations

import re
from typing import Any

from regulatory_packages.sebi.relationships import DocumentIndex, build_relationships

_SUPERSEDES_PATTERNS = [
    re.compile(r"\b(?:hereby\s+)?supersed(?:e|es|ing)\b[^.\n]{0,120}", re.I),
    re.compile(r"\bstands?\s+superseded\b[^.\n]{0,80}", re.I),
    re.compile(r"\bwith\s+immediate\s+effect[^.\n]{0,80}\supersed", re.I),
]
_AMENDS_PATTERNS = [
    re.compile(r"\bamend(?:s|ment|ing)\b[^.\n]{0,120}", re.I),
    re.compile(r"\bpartial(?:ly)?\s+amended\b[^.\n]{0,80}", re.I),
]
_REPEALS_PATTERNS = [
    re.compile(r"\b(?:hereby\s+)?repeal(?:s|ed|ing)?\b[^.\n]{0,120}", re.I),
    re.compile(r"\b(?:hereby\s+)?omitted\b[^.\n]{0,80}", re.I),
    re.compile(r"\b(?:hereby\s+)?deleted\b[^.\n]{0,80}", re.I),
    re.compile(r"\b(?:is|are|shall\s+be)\s+removed\b[^.\n]{0,80}", re.I),
]
_IMPLEMENTS_PATTERNS = [
    re.compile(r"\bimplements?\b[^.\n]{0,120}", re.I),
    re.compile(r"\bpursuant\s+to\b[^.\n]{0,120}", re.I),
    re.compile(r"\bin\s+exercise\s+of\s+the\s+powers\b[^.\n]{0,120}", re.I),
    re.compile(r"\bunder\s+the\s+provisions\s+of\b[^.\n]{0,120}", re.I),
]
_CONSOLIDATES_PATTERNS = [
    re.compile(r"\bconsolidat(?:e|es|ing)\b[^.\n]{0,120}", re.I),
    re.compile(r"\bfor\s+ready\s+reference\b[^.\n]{0,80}", re.I),
    re.compile(r"\bmaster\s+circular\b[^.\n]{0,80}", re.I),
]
_CIRCULAR_REF_RE = re.compile(
    r"(?:Circular|Master Circular|Notification)\s+No\.?\s*:?\s*([A-Z0-9/\-_.]+)",
    re.I,
)
_OFFICIAL_ID_RE = re.compile(r"SEBI/[A-Z0-9/\-_.]+", re.I)


def _snippet(text: str, start: int, width: int = 160) -> str:
    fragment = text[max(0, start - 40) : start + width]
    return re.sub(r"\s+", " ", fragment).strip()


def _match_targets(index: DocumentIndex, text: str, *, source_doc: dict[str, Any]) -> list[tuple[str, str, float]]:
    """Return (target_doc_id, evidence, confidence) candidates from text."""
    hits: list[tuple[str, str, float]] = []
    lower = text.lower()
    source_hierarchy = source_doc.get("hierarchy", "circular")

    reg_id = index.match_regulation(text)
    if reg_id and reg_id != source_doc.get("id"):
        hits.append((reg_id, "Regulation reference in body text", 0.85))

    act_id = index.match_act(text)
    if act_id and act_id != source_doc.get("id"):
        hits.append((act_id, "Act reference in body text", 0.8))

    for match in _CIRCULAR_REF_RE.finditer(text):
        ref = match.group(1).strip()
        for doc in index.by_id.values():
            if doc["id"] == source_doc.get("id"):
                continue
            official = str(doc.get("officialId") or "")
            if ref and ref.lower() in official.lower():
                hits.append((doc["id"], f"Official reference: {ref}", 0.9))
                break

    for match in _OFFICIAL_ID_RE.finditer(text):
        ref = match.group(0)
        for doc in index.by_id.values():
            if doc["id"] == source_doc.get("id"):
                continue
            official = str(doc.get("officialId") or "")
            if official and (ref.lower() in official.lower() or official.lower() in ref.lower()):
                hits.append((doc["id"], f"SEBI file reference: {ref}", 0.88))

    # Title-in-body matches are noisy for long regulations — only for lower instruments.
    if source_hierarchy in {"circular", "master_circular", "guidance_note", "general_order"}:
        title_hits: list[tuple[int, str, str, float]] = []
        for other_id, other in index.by_id.items():
            if other_id == source_doc.get("id"):
                continue
            title = other.get("title", "")
            if len(title) < 30:
                continue
            norm_title = title.lower()
            if norm_title in lower:
                title_hits.append((len(norm_title), other_id, f"Title match in body: {title[:80]}", 0.75))
        title_hits.sort(reverse=True)
        hits.extend((doc_id, evidence, confidence) for _, doc_id, evidence, confidence in title_hits[:5])

    best: dict[str, tuple[str, float]] = {}
    for target_id, evidence, confidence in hits:
        if target_id not in best or confidence > best[target_id][1]:
            best[target_id] = (evidence, confidence)
    return [(target_id, evidence, confidence) for target_id, (evidence, confidence) in best.items()]


def infer_text_relationships(
    documents: list[dict[str, Any]],
    text_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    """Extract amend/supersede/repeal/implements/consolidates edges from PDF text."""
    index = DocumentIndex(documents)
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
        elif rel_type == "repeals":
            add(target_id, source_id, "repealed_by", evidence=evidence, confidence=confidence)

    pattern_map = [
        (_SUPERSEDES_PATTERNS, "supersedes", 0.82),
        (_AMENDS_PATTERNS, "amends", 0.8),
        (_REPEALS_PATTERNS, "repeals", 0.78),
        (_IMPLEMENTS_PATTERNS, "implements", 0.75),
        (_CONSOLIDATES_PATTERNS, "consolidates", 0.72),
    ]
    max_edges_per_doc = 20

    for doc in documents:
        doc_id = doc["id"]
        hierarchy = doc.get("hierarchy", "circular")
        text = text_by_id.get(doc_id, "")
        if not text or len(text) < 40:
            continue

        doc_edge_count = 0
        targets = _match_targets(index, text, source_doc=doc)
        for patterns, rel_type, base_confidence in pattern_map:
            if doc_edge_count >= max_edges_per_doc:
                break
            if rel_type == "implements" and hierarchy in {"act", "regulation", "rule"}:
                continue
            if rel_type == "consolidates" and hierarchy not in {"master_circular", "guidance_note"}:
                continue
            for pattern in patterns:
                match = pattern.search(text)
                if not match:
                    continue
                evidence = _snippet(text, match.start())
                if not targets:
                    reg_id = index.match_regulation(text)
                    act_id = index.match_act(text)
                    fallback = reg_id if reg_id != doc_id else act_id if act_id != doc_id else None
                    if fallback:
                        add(doc_id, fallback, rel_type, evidence=evidence, confidence=base_confidence)
                        doc_edge_count += 1
                    break
                for target_id, target_evidence, target_conf in targets[:8]:
                    if doc_edge_count >= max_edges_per_doc:
                        break
                    confidence = min(0.95, (base_confidence + target_conf) / 2)
                    note = f"{evidence} | {target_evidence}"
                    add(doc_id, target_id, rel_type, evidence=note, confidence=confidence)
                    doc_edge_count += 1
                break

    return edges


def merge_relationships(
    documents: list[dict[str, Any]],
    *,
    text_by_id: dict[str, str] | None = None,
    persisted_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Combine metadata/title edges with text-derived and persisted DB edges."""
    base_edges = build_relationships(documents)
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in base_edges:
        key = (edge["sourceId"], edge["targetId"], edge["type"])
        merged[key] = {**edge, "sourceKind": edge.get("sourceKind", "metadata")}

    if text_by_id:
        for edge in infer_text_relationships(documents, text_by_id):
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
