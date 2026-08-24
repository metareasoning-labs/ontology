"""Deep structured analysis of GST instrument text for ontology and LLM export."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from regulatory_packages.shared.corpus_text import sanitize_corpus_text
from regulatory_packages.gst.taxonomy import infer_entities_for_document, infer_topics
from regulatory_packages.shared.deep_corpus_analysis import (
    aggregate_corpus_signals_deep,
    analysis_limits_for_hierarchy,
    analysis_text_segments,
    extract_section_refs_from_text,
)

_DEFINITION_RE = re.compile(
    r"(?:^|[\.\n]\s*)[\"“']?([A-Z][A-Za-z0-9 \-/&()]{2,60})[\"”']?\s+(?:means|shall mean|has the meaning|refers to)\s+([^.\n]{15,220})",
    re.M,
)
_OBLIGATION_RE = re.compile(
    r"\b(shall not|must not|shall|must|required to|is required to|are required to|prohibited from|may not)\b[^.\n;]{8,220}",
    re.I,
)
_CROSS_REF_RE = re.compile(
    r"(?:Circular|Notification|Order)s?\s+(?:No\.?|:)\s*([0-9/\-A-Za-z]+)|"
    r"(?:CGST|IGST|SGST|UTGST)\s+Act,?\s*2017|"
    r"(?:Central Goods and Services Tax Act)|"
    r"(?:section|rule|notification|clause)\s+(\d+[A-Za-z]?(?:\([a-z0-9]+\))?)",
    re.I,
)
_EFFECTIVE_DATE_RE = re.compile(
    r"(?:with effect from|w\.e\.f\.|effective from|with immediate effect from)\s+([A-Za-z0-9 ,\-/]+)",
    re.I,
)
_STATUS_HINT_RE = re.compile(
    r"\b(supersed(?:e|es|ed|ing)|partially amended|repealed|omitted|stands withdrawn|rescinded)\b[^.\n]{0,100}",
    re.I,
)
_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:CHAPTER|Chapter|PART|Part|Rule|RULE)\s+([IVXLC\d]+)[:\.\-\s]+([^\n]{5,120})",
    re.M,
)
_SENTENCE_RE = re.compile(r"[.!?]\s+")


def _clip(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _top_terms(text: str, limit: int = 20) -> list[str]:
    stop = {
        "goods", "services", "gst", "tax", "circular", "government", "india",
        "shall", "that", "this", "with", "from", "under", "which", "such",
        "cbic", "council", "registered", "taxpayer",
    }
    counter: Counter[str] = Counter()
    for token in re.findall(r"[A-Za-z]{5,}", text.lower()):
        if token not in stop:
            counter[token] += 1
    return [term for term, _ in counter.most_common(limit)]


def _text_summary(title: str, text: str) -> str:
    body = re.sub(r"Page \d+ of \d+", " ", text)
    body = re.sub(r"\s+", " ", body).strip()
    start = 0
    lower_title = title.lower()[:40]
    if lower_title and body.lower().startswith(lower_title[:20]):
        start = min(len(body), len(title) + 20)
    chunk = body[start : start + 1400]
    sentences = _SENTENCE_RE.split(chunk)
    lead_parts = [s.strip() for s in sentences[:4] if len(s.strip()) > 30]
    lead = ". ".join(lead_parts)
    if lead and not lead.endswith("."):
        lead += "."
    return _clip(lead, 900)


def _narrative_summary(
    doc: dict[str, Any],
    *,
    lead: str,
    obligations: list[dict[str, str]],
    definitions: list[dict[str, str]],
    cross_refs: list[dict[str, str]],
    status_hints: list[str],
    effective: str | None,
) -> str:
    paragraphs: list[str] = []
    if lead:
        paragraphs.append(lead)
    if obligations:
        bullets = [f"• {ob['text']}" for ob in obligations[:4]]
        paragraphs.append("Operative requirements identified in the circular text:\n" + "\n".join(bullets))
    if definitions:
        defs = [f"• {d['term']}: {d['definition']}" for d in definitions[:3]]
        paragraphs.append("Key definitions:\n" + "\n".join(defs))
    if cross_refs:
        refs = [f"• {ref['kind'].title()}: {ref['ref']}" for ref in cross_refs[:5]]
        paragraphs.append("Cross-references in body text:\n" + "\n".join(refs))
    meta_bits: list[str] = []
    if effective:
        meta_bits.append(f"Effective from {effective}.")
    if status_hints:
        meta_bits.append(f"Status signals: {'; '.join(status_hints[:2])}.")
    entities = doc.get("entities") or []
    topics = doc.get("topics") or []
    if entities:
        meta_bits.append(f"Applies to {', '.join(entities[:4])}.")
    if topics:
        meta_bits.append(f"Topics: {', '.join(topics[:3])}.")
    if meta_bits:
        paragraphs.append(" ".join(meta_bits))
    return "\n\n".join(paragraphs).strip()


def analyze_document(
    doc: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    text = sanitize_corpus_text(text or "")
    if len(text) < 80:
        return {"summaryFromText": doc.get("summary") or "", "textAnalyzed": False, "charCount": len(text)}

    limits = analysis_limits_for_hierarchy(str(doc.get("hierarchy") or "circular"))
    joined = analysis_text_segments(text)

    definitions: list[dict[str, str]] = []
    seen_defs: set[str] = set()
    for match in _DEFINITION_RE.finditer(joined):
        term = match.group(1).strip()
        key = term.lower()
        if key in seen_defs:
            continue
        seen_defs.add(key)
        definitions.append(
            {"term": term, "definition": _clip(match.group(2).strip(), 180), "snippet": _clip(match.group(0), 200)}
        )
        if len(definitions) >= limits["max_definitions"]:
            break

    obligations: list[dict[str, str]] = []
    seen_ob: set[str] = set()
    for match in _OBLIGATION_RE.finditer(joined):
        phrase = _clip(match.group(0).strip(), 200)
        key = phrase.lower()[:80]
        if key in seen_ob:
            continue
        seen_ob.add(key)
        obligations.append({"modality": match.group(1).lower(), "text": phrase, "snippet": phrase})
        if len(obligations) >= limits["max_obligations"]:
            break

    cross_refs: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for match in _CROSS_REF_RE.finditer(joined):
        ref = next((g for g in match.groups() if g), match.group(0))
        ref = ref.strip()
        key = ref.lower()
        if key in seen_refs:
            continue
        seen_refs.add(key)
        lower = ref.lower()
        if "act" in lower:
            kind = "act"
        elif ref[:1].isdigit():
            kind = "section"
        else:
            kind = "circular"
        cross_refs.append({"kind": kind, "ref": ref, "snippet": _clip(match.group(0), 160)})
        if len(cross_refs) >= limits["max_cross_refs"]:
            break

    headings: list[dict[str, str]] = []
    for match in _HEADING_RE.finditer(joined):
        headings.append({"label": match.group(1).strip(), "title": _clip(match.group(2).strip(), 100)})
        if len(headings) >= limits["max_headings"]:
            break

    effective = _clip(m.group(1).strip(), 80) if (m := _EFFECTIVE_DATE_RE.search(joined)) else None
    status_hints = [_clip(m.group(0), 120) for m in _STATUS_HINT_RE.finditer(joined)][:4]
    title = doc.get("title", "")
    summary = _text_summary(title, text)
    narrative = _narrative_summary(
        doc, lead=summary, obligations=obligations, definitions=definitions,
        cross_refs=cross_refs, status_hints=status_hints, effective=effective,
    )

    return {
        "textAnalyzed": True,
        "charCount": len(text),
        "textCharCount": len(text),
        "summaryFromText": summary,
        "narrativeSummary": narrative,
        "definitions": definitions,
        "definitionCount": len(definitions),
        "obligations": obligations,
        "obligationCount": len(obligations),
        "crossReferences": cross_refs,
        "crossReferenceCount": len(cross_refs),
        "headings": headings,
        "sectionRefsFromText": extract_section_refs_from_text(joined),
        "effectiveDateHint": effective,
        "statusHints": status_hints,
        "keyTerms": _top_terms(joined),
        "entitiesFromText": infer_entities_for_document({**doc, "summary": text[:25000]})[:8],
        "topicsFromText": infer_topics(f"{title} {summary} {text[:20000]}")[:6],
        "segmentCount": len(headings) or 1,
    }


def analyze_corpus(
    documents: list[dict[str, Any]],
    text_by_id: dict[str, str],
) -> dict[str, dict[str, Any]]:
    analyses: dict[str, dict[str, Any]] = {}
    for doc in documents:
        doc_id = doc["id"]
        text = text_by_id.get(doc_id, "")
        if not text:
            continue
        analyses[doc_id] = analyze_document(doc, text)
    return analyses


def aggregate_corpus_signals(document_analyses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return aggregate_corpus_signals_deep(document_analyses)
