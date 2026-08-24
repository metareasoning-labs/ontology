"""Shared helpers for deep regulatory corpus text analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_DEEP_HIERARCHIES = frozenset(
    {
        "act",
        "rule",
        "provision",
        "regulation",
        "master_circular",
        "master_direction",
        "circular",
        "notification",
        "direction",
        "finance_act",
        "guideline",
        "general_order",
    }
)

_MEDIUM_HIERARCHIES = frozenset({"faq", "whats_new", "international", "gazette_notification"})


def analysis_text_segments(text: str, *, chunk_size: int = 50_000, overlap: int = 8_000) -> str:
    """Join overlapping chunks so regex passes cover long PDF extracts."""
    if len(text) <= chunk_size:
        return text
    parts: list[str] = []
    start = 0
    while start < len(text):
        parts.append(text[start : start + chunk_size])
        if start + chunk_size >= len(text):
            break
        start += chunk_size - overlap
    return "\n".join(parts)


def analysis_limits_for_hierarchy(hierarchy: str) -> dict[str, int]:
    if hierarchy in _DEEP_HIERARCHIES:
        return {
            "max_definitions": 20,
            "max_obligations": 25,
            "max_cross_refs": 15,
            "max_headings": 15,
        }
    if hierarchy in _MEDIUM_HIERARCHIES:
        return {
            "max_definitions": 12,
            "max_obligations": 15,
            "max_cross_refs": 12,
            "max_headings": 10,
        }
    return {
        "max_definitions": 8,
        "max_obligations": 10,
        "max_cross_refs": 8,
        "max_headings": 8,
    }


def extract_section_refs_from_text(text: str, *, limit: int = 30) -> list[str]:
    """Pull section/regulation numbers cited in body text."""
    patterns = [
        re.compile(r"\b[Ss]ection\s+(\d+[A-Za-z]?(?:\([a-z0-9]+\))*)", re.I),
        re.compile(r"\b[Rr]egulation\s+(\d+[A-Za-z]?(?:\([a-z0-9]+\))*)", re.I),
        re.compile(r"\b[Rr]ule\s+(\d+[A-Za-z]?(?:\([a-z0-9]+\))*)", re.I),
    ]
    seen: set[str] = set()
    refs: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            ref = match.group(1).strip()
            key = ref.lower()
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
            if len(refs) >= limit:
                return refs
    return refs


def aggregate_corpus_signals_deep(
    analyses: dict[str, dict[str, Any]],
    *,
    top_defined_terms: int = 200,
    top_lexical: int = 300,
    top_sections: int = 150,
    top_obligations: int = 40,
    top_definitions: int = 80,
) -> dict[str, Any]:
    defined_terms: Counter[str] = Counter()
    defined_term_samples: dict[str, str] = {}
    obligation_modalities: Counter[str] = Counter()
    obligation_samples: list[dict[str, str]] = []
    cross_ref_kinds: Counter[str] = Counter()
    cross_ref_values: Counter[str] = Counter()
    lexical: Counter[str] = Counter()
    section_refs: Counter[str] = Counter()
    headings: Counter[str] = Counter()
    total_definitions = total_obligations = total_cross_refs = 0
    seen_ob_samples: set[str] = set()

    for analysis in analyses.values():
        if not analysis.get("textAnalyzed"):
            continue
        total_definitions += int(analysis.get("definitionCount") or 0)
        total_obligations += int(analysis.get("obligationCount") or 0)
        total_cross_refs += int(analysis.get("crossReferenceCount") or 0)
        for item in analysis.get("definitions") or []:
            term = (item.get("term") or "").strip()
            if not term:
                continue
            key = term.lower()
            defined_terms[key] += 1
            if key not in defined_term_samples and item.get("definition"):
                defined_term_samples[key] = str(item["definition"])[:220]
        for item in analysis.get("obligations") or []:
            modality = item.get("modality", "shall")
            obligation_modalities[modality] += 1
            snippet = (item.get("text") or item.get("snippet") or "").strip()
            key = snippet.lower()[:100]
            if snippet and key not in seen_ob_samples and len(obligation_samples) < top_obligations:
                seen_ob_samples.add(key)
                obligation_samples.append({"modality": modality, "text": snippet[:220]})
        for item in analysis.get("crossReferences") or []:
            cross_ref_kinds[item.get("kind", "instrument")] += 1
            ref = (item.get("ref") or "").strip()
            if ref:
                cross_ref_values[ref.lower()] += 1
        for term in analysis.get("keyTerms") or []:
            lexical[term] += 1
        for ref in analysis.get("sectionRefsFromText") or []:
            section_refs[str(ref)] += 1
        for item in analysis.get("headings") or []:
            title = (item.get("title") or item.get("label") or "").strip()
            if title:
                headings[title.lower()] += 1

    return {
        "documentsAnalyzed": sum(1 for a in analyses.values() if a.get("textAnalyzed")),
        "totalDefinitions": total_definitions,
        "totalObligations": total_obligations,
        "totalCrossReferences": total_cross_refs,
        "topDefinedTerms": [
            {"term": term, "documentFrequency": count}
            for term, count in defined_terms.most_common(top_defined_terms)
            if term
        ],
        "definedTermGlossary": [
            {
                "term": term,
                "documentFrequency": defined_terms[term],
                "sampleDefinition": defined_term_samples.get(term, ""),
            }
            for term, _ in defined_terms.most_common(top_definitions)
            if term
        ],
        "obligationModalities": [
            {"modality": mod, "count": count} for mod, count in obligation_modalities.most_common()
        ],
        "obligationSamples": obligation_samples,
        "crossReferenceKinds": [
            {"kind": kind, "count": count} for kind, count in cross_ref_kinds.most_common()
        ],
        "topCrossReferences": [
            {"ref": ref, "documentFrequency": count}
            for ref, count in cross_ref_values.most_common(100)
            if ref
        ],
        "lexicalIndexFromText": [
            {"term": term, "documentFrequency": count} for term, count in lexical.most_common(top_lexical)
        ],
        "sectionRefsFromText": [
            {"section": section, "documentFrequency": count}
            for section, count in section_refs.most_common(top_sections)
            if section
        ],
        "headingIndexFromText": [
            {"heading": heading, "documentFrequency": count}
            for heading, count in headings.most_common(60)
            if heading
        ],
    }
