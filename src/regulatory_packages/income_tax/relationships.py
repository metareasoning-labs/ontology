"""Infer relationships between Income Tax corpus documents."""

from __future__ import annotations

import re
from typing import Any

from regulatory_packages.income_tax.taxonomy import IT_ASSESSEE_LABELS, extract_section_refs

_SECTION_EDGE_RE = re.compile(r"\bsection\s+(\d+[A-Za-z]?)\b", re.I)


def build_relationships(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {doc["id"]: doc for doc in documents}
    section_index: dict[str, list[str]] = {}
    for doc in documents:
        if doc.get("hierarchy") == "provision":
            for ref in doc.get("sectionRefs") or extract_section_refs(doc.get("title", "")):
                section_index.setdefault(ref.lower(), []).append(doc["id"])

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source_id: str, target_id: str, rel_type: str, note: str = "") -> None:
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
                "note": note or None,
            }
        )

    act_ids = [d["id"] for d in documents if d.get("hierarchy") == "act"]
    primary_act = act_ids[0] if act_ids else None

    for doc in documents:
        doc_id = doc["id"]
        title = doc.get("title", "")
        hierarchy = doc.get("hierarchy", "circular")

        for code in doc.get("entities", []):
            add(doc_id, f"entity:{code}", "applies_to", IT_ASSESSEE_LABELS.get(code, code))

        for topic in doc.get("topics", []):
            add(doc_id, f"topic:{topic.lower()}", "cross_references", topic)

        for ref in extract_section_refs(title):
            for prov_id in section_index.get(ref.lower(), []):
                add(doc_id, prov_id, "cross_references", f"References Section {ref}")
            if primary_act and hierarchy in {"circular", "notification", "faq", "whats_new"}:
                add(doc_id, primary_act, "implements", f"Mentions Section {ref}")

        if _SECTION_EDGE_RE.search(title) and hierarchy in {"circular", "notification", "whats_new"}:
            add(doc_id, primary_act, "clarifies", "Clarifies Act provisions") if primary_act else None

        if re.search(r"\bamend", title, re.I):
            for other in documents:
                if other["id"] == doc_id:
                    continue
                if other.get("hierarchy") == hierarchy and other.get("section") == doc.get("section"):
                    if len(set(title.lower().split()) & set(other.get("title", "").lower().split())) >= 4:
                        add(doc_id, other["id"], "amends", "Title indicates amendment")

        if re.search(r"\bsupersed", title, re.I):
            for other in documents:
                if other["id"] == doc_id or other.get("hierarchy") != hierarchy:
                    continue
                if doc.get("section") == other.get("section"):
                    add(doc_id, other["id"], "supersedes", "Title indicates supersession")

    return edges


_ACT_TITLE_RE = re.compile(r"income[- ]tax act,?\s*1961", re.I)
_FINANCE_ACT_RE = re.compile(r"finance act,?\s*(\d{4})", re.I)
_SECTION_REF_RE = re.compile(r"\bsection\s+(\d+[A-Za-z]?)\b", re.I)
_CIRCULAR_REF_RE = re.compile(
    r"(?:Circular|Notification|Order)\s+No\.?\s*:?\s*([A-Z0-9/\-_.]+)",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


class DocumentIndex:
    """Lookup index for matching ITD instrument references in body text."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.by_id = {doc["id"]: doc for doc in documents}
        self.acts: list[dict[str, Any]] = []
        self.provisions: list[dict[str, Any]] = []
        self.by_section: dict[str, str] = {}
        self.by_official: dict[str, str] = {}
        for doc in documents:
            hierarchy = doc.get("hierarchy")
            title = doc.get("title", "")
            if hierarchy == "act" and _ACT_TITLE_RE.search(title):
                self.acts.append(doc)
            elif hierarchy == "provision":
                self.provisions.append(doc)
                for ref in doc.get("sectionRefs") or extract_section_refs(title):
                    self.by_section[ref.lower()] = doc["id"]
            official = doc.get("officialId")
            if official:
                self.by_official[_norm(str(official))] = doc["id"]

    def match_act(self, text: str) -> str | None:
        if not _ACT_TITLE_RE.search(text):
            return None
        return self.acts[0]["id"] if self.acts else None

    def match_finance_act(self, text: str) -> str | None:
        match = _FINANCE_ACT_RE.search(text)
        if not match:
            return None
        year = match.group(1)
        for doc in self.by_id.values():
            if doc.get("hierarchy") != "finance_act":
                continue
            if year in doc.get("title", ""):
                return doc["id"]
        return None

    def match_sections(self, text: str) -> list[str]:
        hits: list[str] = []
        seen: set[str] = set()
        for match in _SECTION_REF_RE.finditer(text):
            ref = match.group(1).lower()
            prov_id = self.by_section.get(ref)
            if prov_id and prov_id not in seen:
                seen.add(prov_id)
                hits.append(prov_id)
        return hits

    def match_official_refs(self, text: str) -> list[tuple[str, str, float]]:
        hits: list[tuple[str, str, float]] = []
        for match in _CIRCULAR_REF_RE.finditer(text):
            ref = match.group(1).strip()
            for doc in self.by_id.values():
                official = str(doc.get("officialId") or "")
                if ref and official and ref.lower() in official.lower():
                    hits.append((doc["id"], f"Official reference: {ref}", 0.9))
                    break
        return hits
