"""Infer metadata relationships between RBI documents."""

from __future__ import annotations

import re
from typing import Any

from regulatory_packages.rbi.taxonomy import RBI_ENTITY_LABELS, extract_official_id

_RBI_ACT_RE = re.compile(r"reserve bank of india act,?\s*1934|rbi act,?\s*1934", re.I)
_BR_ACT_RE = re.compile(r"banking regulation act,?\s*1949|br act,?\s*1949", re.I)
_FEMA_RE = re.compile(r"foreign exchange management act,?\s*1999|fema,?\s*1999", re.I)
_SUPERSEDES_RE = re.compile(r"\bsupersed(?:e|es|ing)\b", re.I)
_AMENDS_RE = re.compile(r"\bamend(?:s|ment|ing)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


class DocumentIndex:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.by_id = {doc["id"]: doc for doc in documents}
        self.by_official: dict[str, str] = {}
        self.by_section: dict[str, str] = {}
        for doc in documents:
            official = doc.get("officialId")
            if official:
                self.by_official[_norm(str(official))] = doc["id"]
            for ref in doc.get("sectionRefs") or []:
                self.by_section[str(ref).lower()] = doc["id"]

    def match_official_refs(self, text: str) -> list[tuple[str, str, float]]:
        hits: list[tuple[str, str, float]] = []
        for match in re.finditer(
            r"(?:notification|circular|master direction|direction)\s+no\.?\s*:?\s*([0-9/\-A-Za-z]+)",
            text,
            re.I,
        ):
            key = _norm(match.group(1))
            doc_id = self.by_official.get(key)
            if doc_id:
                hits.append((doc_id, f"Instrument reference: {match.group(1)}", 0.86))
        return hits


def build_relationships(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source_id: str, target_id: str, rel_type: str, *, note: str, confidence: float = 0.7) -> None:
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
                "note": note,
                "evidence": note,
                "confidence": confidence,
                "sourceKind": "metadata",
            }
        )

    index = DocumentIndex(documents)
    act_hub = "hub:rbi-act"
    for doc in documents:
        doc_id = doc["id"]
        title = doc.get("title", "")
        subject = doc.get("summary") or doc.get("shortTitle") or ""
        blob = f"{title} {subject}"
        if _RBI_ACT_RE.search(blob) or doc.get("sectionRefs"):
            add(doc_id, act_hub, "implements", note="References RBI Act, 1934 or its sections", confidence=0.78)
        if _BR_ACT_RE.search(blob):
            add(doc_id, "hub:banking-regulation-act", "implements", note="References Banking Regulation Act, 1949", confidence=0.76)
        if _FEMA_RE.search(blob):
            add(doc_id, "hub:fema", "implements", note="References FEMA, 1999", confidence=0.76)
        if _SUPERSEDES_RE.search(blob):
            for other in documents:
                if other["id"] == doc_id:
                    continue
                other_official = other.get("officialId")
                if other_official and other_official in blob:
                    add(doc_id, other["id"], "supersedes", note=f"Title/subject supersedes {other_official}", confidence=0.72)
        if _AMENDS_RE.search(blob):
            for other in documents:
                if other["id"] == doc_id:
                    continue
                if other.get("officialId") and str(other["officialId"]) in blob:
                    add(doc_id, other["id"], "amends", note=f"Amends/clarifies {other.get('officialId')}", confidence=0.7)
        for target_id, evidence, confidence in index.match_official_refs(blob):
            add(doc_id, target_id, "cross_references", note=evidence, confidence=confidence)
        for entity in doc.get("entities") or []:
            add(doc_id, f"entity:{entity}", "applies_to", note=f"Tagged entity: {RBI_ENTITY_LABELS.get(entity, entity)}", confidence=0.65)

    return edges
