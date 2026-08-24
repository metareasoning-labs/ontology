"""Infer regulatory relationships between SEBI documents."""

from __future__ import annotations

import re
from typing import Any

from regulatory_packages.sebi.taxonomy import SEBI_ENTITY_LABELS

_REGULATION_TITLE_RE = re.compile(
    r"sebi\s*\(([^)]+)\)\s*regulations?,?\s*(\d{4})",
    re.I,
)
_ACT_RE = re.compile(
    r"(securities and exchange board of india act|securities contracts regulation act|"
    r"depositories act|securities laws amendment act)[^,.]*?(\d{4})?",
    re.I,
)
_SUPERSEDES_RE = re.compile(r"\bsupersed(?:e|es|ing)\b", re.I)
_AMENDS_RE = re.compile(r"\bamend(?:s|ment|ing)\b", re.I)
_MASTER_CIRCULAR_RE = re.compile(r"\bmaster circular\b", re.I)

_HIERARCHY_RANK = {
    "act": 0,
    "rule": 1,
    "regulation": 2,
    "general_order": 3,
    "guidance_note": 3,
    "master_circular": 4,
    "circular": 5,
    "gazette_notification": 5,
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{4,}", _norm(text)) if t not in {"sebi", "board", "india", "regulations", "regulation"}}


def _regulation_core_title(title: str) -> str:
    match = re.search(r"sebi\s*\((.+?)\)\s*regulations?,?\s*(\d{4})", title, re.I)
    if match:
        return _norm(f"sebi ({match.group(1)}) regulations {match.group(2)}")
    return _norm(title[:90])


def _regulation_aliases(title: str) -> list[str]:
    aliases = [_norm(title[:120]), _regulation_core_title(title)]
    match = re.search(r"sebi\s*\((.+?)\)\s*regulations?,?\s*(\d{4})", title, re.I)
    if match:
        subject = _norm(match.group(1))
        year = match.group(2)
        aliases.extend([_norm(f"{subject} {year}"), subject, _norm(f"sebi ({match.group(1)}) regulations {year}")])
    return [a for a in aliases if a and len(a) >= 8]


class DocumentIndex:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.by_id = {doc["id"]: doc for doc in documents}
        self.regulations: list[dict[str, Any]] = []
        self.acts: list[dict[str, Any]] = []
        self.master_circulars: list[dict[str, Any]] = []
        self.by_reg_key: dict[str, str] = {}
        self.by_entry_id: dict[str, str] = {}
        for doc in documents:
            if doc.get("entryId"):
                self.by_entry_id[str(doc["entryId"])] = doc["id"]
            hierarchy = doc.get("hierarchy")
            title = doc.get("title", "")
            if hierarchy == "regulation":
                self.regulations.append(doc)
                for alias in _regulation_aliases(title):
                    self.by_reg_key[alias] = doc["id"]
            elif hierarchy == "act":
                self.acts.append(doc)
            elif hierarchy == "master_circular":
                self.master_circulars.append(doc)

    def match_regulation(self, text: str) -> str | None:
        lower = _norm(text)
        # Explicit SEBI (Subject) Regulations, YYYY references in instrument text.
        for match in _REGULATION_TITLE_RE.finditer(text):
            subject = _norm(match.group(1))
            year = match.group(2)
            for key in (f"{subject} {year}", subject):
                if key in self.by_reg_key:
                    return self.by_reg_key[key]
        best_id: str | None = None
        best_len = 0
        for doc in self.regulations:
            title = _norm(doc.get("title", ""))
            if len(title) < 15:
                continue
            # Prefer longest regulation title contained in source text.
            if title in lower and len(title) > best_len:
                best_id = doc["id"]
                best_len = len(title)
            core = _regulation_core_title(doc.get("title", ""))
            if core and core in lower and len(core) > best_len:
                best_id = doc["id"]
                best_len = len(core)
        return best_id

    def match_act(self, text: str) -> str | None:
        lower = _norm(text)
        for doc in self.acts:
            title = _norm(doc.get("title", ""))
            if len(title) >= 10 and title[:40] in lower:
                return doc["id"]
        match = _ACT_RE.search(text)
        if not match:
            return None
        fragment = _norm(match.group(0))
        for doc in self.acts:
            if fragment[:30] in _norm(doc.get("title", "")):
                return doc["id"]
        return None

    def match_master_circular(self, doc: dict[str, Any]) -> str | None:
        title = doc.get("title", "")
        entities = set(doc.get("entities", []))
        best: tuple[int, str] | None = None
        for mc in self.master_circulars:
            mc_entities = set(mc.get("entities", []))
            overlap = len(entities & mc_entities)
            title_overlap = len(_tokens(title) & _tokens(mc.get("title", "")))
            score = overlap * 3 + title_overlap
            if score > 0 and (best is None or score > best[0]):
                best = (score, mc["id"])
        if best and best[0] >= 3:
            return best[1]
        if _MASTER_CIRCULAR_RE.search(title):
            return best[1] if best else None
        return None

    def match_similar_document(self, doc: dict[str, Any], relation: str) -> str | None:
        """Best-effort link to another document sharing subject matter."""
        source_tokens = _tokens(doc.get("title", ""))
        if len(source_tokens) < 3:
            return None
        candidates: list[tuple[int, str]] = []
        for other in self.by_id.values():
            if other["id"] == doc["id"]:
                continue
            if other.get("hierarchy") != doc.get("hierarchy"):
                continue
            overlap = len(source_tokens & _tokens(other.get("title", "")))
            if overlap >= 4:
                candidates.append((overlap, other["id"]))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]


def build_relationships(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = DocumentIndex(documents)
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

    for doc in documents:
        doc_id = doc["id"]
        title = doc.get("title", "")
        hierarchy = doc.get("hierarchy", "circular")

        for code in doc.get("entities", []):
            add(doc_id, f"entity:{code}", "applies_to", SEBI_ENTITY_LABELS.get(code, code))

        for topic in doc.get("topics", []):
            add(doc_id, f"topic:{topic.lower()}", "cross_references", topic)

        reg_id = index.match_regulation(title)
        if reg_id and hierarchy in {"circular", "master_circular", "guidance_note", "general_order"}:
            add(doc_id, reg_id, "implements", "Implements or operates under regulation referenced in title")

        act_id = index.match_act(title)
        if act_id and hierarchy in {"regulation", "rule", "circular", "master_circular"}:
            add(doc_id, act_id, "cross_references", "References underlying Act")

        if hierarchy == "regulation":
            act_id = index.match_act(title)
            if act_id:
                add(doc_id, act_id, "implements", "Regulation issued under Act framework")

        mc_id = index.match_master_circular(doc)
        if mc_id and hierarchy == "circular":
            add(doc_id, mc_id, "cross_references", "Related master circular for same intermediary domain")

        if hierarchy == "master_circular":
            reg_id = index.match_regulation(title)
            if reg_id:
                add(doc_id, reg_id, "consolidates", "Master circular consolidates circulars under this regulation")
            # Link to a bounded set of same-entity circulars (avoid n^2 blow-up).
            linked = 0
            for other in documents:
                if linked >= 15:
                    break
                if other["id"] == doc_id or other.get("hierarchy") != "circular":
                    continue
                if not (set(doc.get("entities", [])) & set(other.get("entities", []))):
                    continue
                if len(_tokens(title) & _tokens(other.get("title", ""))) >= 2:
                    add(doc_id, other["id"], "consolidates", "Consolidates operative circular in this domain")
                    linked += 1

        if _SUPERSEDES_RE.search(title):
            prior = index.match_similar_document(doc, "supersedes")
            if prior:
                add(doc_id, prior, "supersedes", "Title indicates supersession")
                add(prior, doc_id, "superseded_by", "Superseded by later instrument")

        if _AMENDS_RE.search(title):
            prior = index.match_regulation(title) or index.match_similar_document(doc, "amends")
            if prior and prior != doc_id:
                add(doc_id, prior, "amends", "Title indicates amendment")

        # Hierarchy ordering edges (upper instrument -> lower instrument)
        rank = _HIERARCHY_RANK.get(hierarchy, 99)
        if reg_id and rank > _HIERARCHY_RANK["regulation"]:
            add(reg_id, doc_id, "cross_references", "Hierarchy: regulation parent")

    return edges
