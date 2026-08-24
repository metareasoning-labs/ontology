"""Generate LLM vocabulary and grammar from SEBI catalog + ontology artifacts."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from regulatory_packages.sebi.taxonomy import (
    ABBREVIATIONS,
    DOCUMENT_STATUSES,
    ENTITY_ALIASES,
    ENTITY_DESCRIPTIONS,
    HIERARCHY_BY_SECTION,
    HIERARCHY_META,
    REGULATION_NICKNAMES,
    RELATIONSHIP_TYPES,
    SEBI_ENTITY_CODES,
    SEBI_ENTITY_LABELS,
    SEBI_TOPICS,
    STATUS_SEMANTICS,
    TOPIC_DESCRIPTIONS,
    TOPIC_KEYWORDS,
    taxonomy_schema,
)

_VOCABULARY_VERSION = 6
_GRAMMAR_VERSION = 6

_REGULATION_TITLE_RE = re.compile(
    r"sebi\s*\(([^)]+)\)\s*regulations?,?\s*(\d{4})",
    re.I,
)

_RELATIONSHIP_SEMANTICS: dict[str, dict[str, Any]] = {
    "implements": {
        "direction": "source → target",
        "meaning": "Source instrument operates under or gives effect to the target (typically circular → regulation).",
        "traverseBeforeCite": True,
        "inverseHint": "Find parent regulation before citing implementing circular.",
        "examples": ["Circular under AIF Regulations → AIF Regulations 2012"],
    },
    "amends": {
        "direction": "source → target",
        "meaning": "Source instrument amends the target; both may remain partially in force.",
        "traverseBeforeCite": True,
        "inverseHint": "Read amendment together with the amended parent.",
        "examples": ["Amendment circular → parent regulation"],
    },
    "supersedes": {
        "direction": "source → target",
        "meaning": "Source replaces the target; target should not be cited as operative.",
        "traverseBeforeCite": True,
        "inverseHint": "Do not cite superseded instruments unless discussing history.",
        "examples": ["New master circular → prior master circular"],
    },
    "superseded_by": {
        "direction": "source → target",
        "meaning": "Source was replaced by target (inverse of supersedes).",
        "traverseBeforeCite": True,
        "inverseHint": "Follow to the replacing instrument.",
        "examples": ["Old circular → superseding circular"],
    },
    "repeals": {
        "direction": "source → target",
        "meaning": "Source repeals, omits, or removes operative provisions in the target.",
        "traverseBeforeCite": True,
        "inverseHint": "Do not cite repealed provisions as operative.",
        "examples": ["Amending circular → prior circular clause"],
    },
    "repealed_by": {
        "direction": "source → target",
        "meaning": "Source provisions were repealed or removed by target (inverse of repeals).",
        "traverseBeforeCite": True,
        "inverseHint": "Follow to the repealing instrument.",
        "examples": ["Old provision → repealing circular"],
    },
    "consolidates": {
        "direction": "source → target",
        "meaning": "Source master circular consolidates operative circulars or regulation guidance.",
        "traverseBeforeCite": True,
        "inverseHint": "Prefer consolidated master circular over individual circulars when in force.",
        "examples": ["Master Circular for AIFs → operative AIF circulars"],
    },
    "applies_to": {
        "direction": "document → entity",
        "meaning": "Document applies to intermediary type or entity class.",
        "traverseBeforeCite": False,
        "inverseHint": "Filter corpus by entity code before deep retrieval.",
        "examples": ["AIF circular → entity:AIF"],
    },
    "cross_references": {
        "direction": "bidirectional",
        "meaning": "Related reference, topic link, Act reference, or hierarchy parent hint.",
        "traverseBeforeCite": False,
        "inverseHint": "Use for context; verify operative status separately.",
        "examples": ["Regulation → SEBI Act", "Document → topic node"],
    },
    "issued_under": {
        "direction": "document → hierarchy hub",
        "meaning": "Document belongs to legal hierarchy branch (Acts, Circulars, etc.).",
        "traverseBeforeCite": False,
        "inverseHint": "Use for section filtering only.",
        "examples": ["Circular → hub:circulars"],
    },
}

_GRAMMAR_RULES: list[dict[str, Any]] = [
    {
        "nonterminal": "RegulatoryAnswer",
        "description": "Top-level structured response for SEBI legal questions.",
        "productions": [
            "ScopeStatement LegalChain PrimaryObligation SupportingInstruments* ConflictResolution? StatusCaveats?",
            "ClarifyingQuestion",
            "AbstainResponse",
        ],
    },
    {
        "nonterminal": "ScopeStatement",
        "description": "Entity, topic, and time scope of the answer.",
        "productions": [
            "'For' EntityRef ( 'on' TopicRef )? ( 'as of' DateRef )?",
            "'Cross-cutting guidance for' EntityRef+",
            "'Under' RegulationNickname ( 'as applicable to' EntityRef )?",
        ],
    },
    {
        "nonterminal": "LegalChain",
        "description": "Authoritative chain from parent Act/Regulation down to operative circular.",
        "productions": [
            "ActRef? RuleRef? RegulationRef MasterCircularRef? CircularRef*",
            "RegulationNickname '→' MasterCircularRef? '→' CircularRef*",
        ],
        "constraints": [
            "Traverse implements/consolidates edges upward before citing leaf circulars.",
            "Order instruments by hierarchy rank (Act < Rule < Regulation < Master Circular < Circular).",
            "When user cites a nickname (LODR, PIT, AIF Regulations), resolve to full regulation title first.",
        ],
    },
    {
        "nonterminal": "ActRef",
        "description": "Reference to parent legislation.",
        "productions": [
            "HierarchyTag ActTitle ( '(' Year ')' )?",
        ],
    },
    {
        "nonterminal": "RuleRef",
        "description": "Reference to SEBI Rules made under an Act.",
        "productions": ["HierarchyTag RuleTitle"],
    },
    {
        "nonterminal": "RegulationRef",
        "description": "Reference to SEBI Regulations.",
        "productions": [
            "HierarchyTag RegulationTitle ( '(' Year ')' )?",
            "RegulationNickname",
        ],
    },
    {
        "nonterminal": "MasterCircularRef",
        "description": "Consolidated operative guidance.",
        "productions": ["HierarchyTag MasterCircularTitle ( '(' Year ')' )?"],
    },
    {
        "nonterminal": "CircularRef",
        "description": "Individual circular citation.",
        "productions": ["HierarchyTag CircularTitle ( '(' DateRef ')' )?"],
    },
    {
        "nonterminal": "RegulationNickname",
        "description": "Short name for well-known regulations.",
        "productions": [
            "'LODR' | 'PIT' | 'AIF Regulations' | 'FPI Regulations' | 'ICDR' | 'SBTS' | "
            "'MF Regulations' | 'PMS Regulations' | 'IA Regulations' | 'RA Regulations' | "
            "'PFUTP' | 'Depository Regulations' | 'INVIT Regulations' | 'REIT Regulations'",
        ],
    },
    {
        "nonterminal": "PrimaryObligation",
        "description": "The main operative requirement answering the user question.",
        "productions": [
            "Citation 'requires' ObligationText",
            "Citation 'permits' ObligationText",
            "Citation 'prohibits' ObligationText",
            "Citation 'defines' DefinitionText",
            "Citation 'clarifies' ObligationText",
        ],
    },
    {
        "nonterminal": "SupportingInstruments",
        "description": "Secondary citations that clarify or qualify the primary obligation.",
        "productions": [
            "Citation ( 'which' QualifierText )?",
            "Citation 'read with' Citation",
        ],
    },
    {
        "nonterminal": "ConflictResolution",
        "description": "When multiple instruments overlap or appear to conflict.",
        "productions": [
            "'Where instruments overlap,' HierarchyPrecedenceRule",
            "'Later amendment' Citation 'modifies' Citation",
        ],
    },
    {
        "nonterminal": "StatusCaveats",
        "description": "Honest limits when corpus metadata is incomplete.",
        "productions": [
            "'Note:' SupersessionWarning",
            "'Note:' MetadataOnlySummary",
            "'Note:' ConsultOfficialPdf",
            "'Note:' PartialAmendmentWarning",
            "'Note:' DraftConsultationWarning",
        ],
    },
    {
        "nonterminal": "ClarifyingQuestion",
        "description": "When entity/topic/regulation cannot be resolved confidently.",
        "productions": [
            "'Which intermediary are you asking about?' EntityChoice+",
            "'Do you mean' RegulationNickname '|' RegulationTitle '?",
            "'Are you asking about' TopicRef '|' TopicRef '?",
        ],
    },
    {
        "nonterminal": "AbstainResponse",
        "description": "When corpus cannot support a compliance-grade answer.",
        "productions": [
            "'I cannot verify operative clause text from metadata alone.' PdfPointer",
            "'No in-force instrument found for' EntityRef TopicRef 'in this corpus slice.'",
        ],
    },
    {
        "nonterminal": "Citation",
        "description": "Reference to a SEBI instrument in the corpus.",
        "productions": [
            "HierarchyTag DocumentTitle ( '(' OfficialId | DateRef ')' )?",
            "DocumentId",
        ],
        "constraints": [
            "Use full document title, not shortTitle.",
            "Include officialId, entryId, sourceUrl, or pdfUrl when available.",
            "Skip documents with status=superseded unless user asks for history.",
            "Always prefix with hierarchy badge (Act, Regulation, Master Circular, Circular).",
        ],
    },
    {
        "nonterminal": "EntityRef",
        "description": "Controlled entity reference.",
        "productions": ["EntityLabel | EntityCode | EntityAlias"],
        "constraints": [
            "Must resolve to a code in entityCodes vocabulary.",
            "If multiple entities match, prefer the most specific; else ask ClarifyingQuestion.",
        ],
    },
    {
        "nonterminal": "TopicRef",
        "description": "Controlled topic reference.",
        "productions": ["TopicLabel | TopicKeyword"],
        "constraints": ["Must resolve to a label in topics vocabulary."],
    },
    {
        "nonterminal": "DateRef",
        "description": "Temporal anchor for as-of queries.",
        "productions": ["ISO-date | 'today' | 'latest in-force' | Year"],
    },
    {
        "nonterminal": "HierarchyTag",
        "description": "Instrument type badge.",
        "productions": [
            "'Act' | 'Rules' | 'Regulation' | 'General Order' | 'Guideline' | "
            "'Master Circular' | 'Circular' | 'Gazette Notification'",
        ],
    },
    {
        "nonterminal": "HierarchyPrecedenceRule",
        "description": "Conflict resolution by legal hierarchy.",
        "productions": [
            "'prefer' RegulationRef 'over' CircularRef",
            "'prefer' MasterCircularRef 'over' CircularRef",
            "'Act/Rules/Regulation prevail over circular guidance'",
        ],
    },
    {
        "nonterminal": "PdfPointer",
        "description": "Pointer to official source when text is required.",
        "productions": ["'See official PDF:' PdfUrl | SourceUrl"],
    },
]

_QUERY_INTENTS: list[dict[str, Any]] = [
    {
        "intent": "find_governing_regulation",
        "examples": [
            "What regulations govern AIFs?",
            "Which SEBI regulation applies to mutual funds on valuation?",
            "Governing regulation for portfolio managers",
        ],
        "start": {"axis": "entity", "then": "topic"},
        "traverse": ["applies_to", "implements", "consolidates"],
        "citePreference": ["regulation", "master_circular"],
    },
    {
        "intent": "list_implementing_circulars",
        "examples": [
            "Which circulars implement the AIF Regulations?",
            "Circulars under LODR",
            "All circulars under PIT Regulations",
        ],
        "start": {"axis": "regulation", "matchBy": "titleOrNickname"},
        "traverse": ["implements", "consolidates"],
        "citePreference": ["master_circular", "circular"],
    },
    {
        "intent": "consolidated_view",
        "examples": [
            "What master circular consolidates mutual fund disclosure rules?",
            "Master circular for stock brokers on risk management",
        ],
        "start": {"axis": "entity", "filterHierarchy": "master_circular"},
        "traverse": ["consolidates", "applies_to"],
        "citePreference": ["master_circular"],
    },
    {
        "intent": "supersession_check",
        "examples": [
            "Is this circular still in force?",
            "What replaced circular XYZ?",
            "Has this master circular been superseded?",
        ],
        "start": {"axis": "document", "matchBy": "titleOrId"},
        "traverse": ["supersedes", "superseded_by", "amends"],
        "citePreference": ["regulation", "master_circular", "circular"],
    },
    {
        "intent": "topic_scan",
        "examples": [
            "SEBI cybersecurity requirements for brokers",
            "KYC rules for portfolio managers",
            "Margin requirements for trading members",
        ],
        "start": {"axis": "topic", "then": "entity"},
        "traverse": ["applies_to", "cross_references"],
        "citePreference": ["regulation", "master_circular"],
    },
    {
        "intent": "compliance_checklist",
        "examples": [
            "Compliance checklist for AIF Category II",
            "What must a mutual fund disclose quarterly?",
            "Registration requirements for research analysts",
        ],
        "start": {"axis": "entity", "then": "topic", "filterStatus": "in_force"},
        "traverse": ["applies_to", "implements", "consolidates"],
        "citePreference": ["regulation", "master_circular", "circular"],
        "answerShape": "PrimaryObligation+",
    },
    {
        "intent": "compare_instruments",
        "examples": [
            "Difference between AIF Category I and III requirements",
            "How do PMS rules differ from investment adviser rules?",
        ],
        "start": {"axis": "entity", "compare": True},
        "traverse": ["applies_to", "cross_references"],
        "citePreference": ["regulation"],
    },
    {
        "intent": "timeline_history",
        "examples": [
            "History of FPI regulations in India",
            "How has LODR evolved since 2015?",
        ],
        "start": {"axis": "regulation", "includeSuperseded": True},
        "traverse": ["supersedes", "superseded_by", "amends"],
        "citePreference": ["regulation", "circular"],
    },
    {
        "intent": "definition_lookup",
        "examples": [
            "How does SEBI define accredited investor for AIFs?",
            "Definition of UPSI under PIT",
        ],
        "start": {"axis": "topic", "matchBy": "definition"},
        "traverse": ["implements", "cross_references"],
        "citePreference": ["regulation"],
        "requiresPdf": True,
    },
    {
        "intent": "penalty_enforcement",
        "examples": [
            "Penalties for insider trading violations",
            "SEBI enforcement actions framework",
        ],
        "start": {"axis": "topic", "topicFilter": "Enforcement & Penalties"},
        "traverse": ["applies_to", "cross_references"],
        "citePreference": ["act", "regulation", "circular"],
    },
]

_TRAVERSAL_RECIPES: list[dict[str, Any]] = [
    {
        "name": "circular_to_parent_regulation",
        "steps": ["Start at circular", "Follow implements (outgoing)", "Stop at regulation or act"],
        "useWhen": "User cites or asks about a specific circular",
    },
    {
        "name": "entity_topic_filter",
        "steps": ["Resolve EntityRef", "Resolve TopicRef", "Filter documents by applies_to + topic tags"],
        "useWhen": "Broad questions like 'rules for brokers on margins'",
    },
    {
        "name": "master_circular_consolidation",
        "steps": ["Find master_circular for entity/topic", "Follow consolidates to member circulars", "Prefer MC as primary cite"],
        "useWhen": "User wants consolidated/current operative view",
    },
    {
        "name": "supersession_walk",
        "steps": ["Check document status", "If superseded follow superseded_by", "If amends read amends target"],
        "useWhen": "User asks if instrument is still in force",
    },
    {
        "name": "text_evidence_chain",
        "steps": [
            "Open document.analysis.crossReferences",
            "Traverse matching relationship edges with evidence snippets",
            "Prefer obligations/definitions tied to user topic",
        ],
        "useWhen": "User asks for operative requirement or defined term in a specific circular/regulation",
    },
]

_RESOLUTION_RULES: list[dict[str, str]] = [
    {"step": "normalize", "rule": "Lowercase, strip punctuation, expand abbreviations via abbreviations map."},
    {"step": "entity", "rule": "Match entityCodes, entityLabels, then entity aliases (longest match wins)."},
    {"step": "topic", "rule": "Match topic labels, then topic keywords (count hits; threshold ≥1)."},
    {"step": "regulation", "rule": "Match regulationNicknames first, then regulation titles in corpus."},
    {"step": "hierarchy", "rule": "If user says 'circular/regulation/act/master circular', set hierarchy filter."},
    {"step": "status", "rule": "Default to in_force unless user asks for history, repealed, or superseded instruments."},
    {"step": "disambiguate", "rule": "If General entity + low topic confidence, emit ClarifyingQuestion."},
]

_NORMALIZATION_RULES: list[dict[str, str]] = [
    {"pattern": "know your customer", "mapsTo": "KYC"},
    {"pattern": "listing obligations", "mapsTo": "LODR"},
    {"pattern": "insider trading", "mapsTo": "PIT topic or PIT Regulations"},
    {"pattern": "alternative investment fund(s)?", "mapsTo": "entity:AIF"},
    {"pattern": "foreign portfolio investor(s)?", "mapsTo": "entity:FPIs"},
    {"pattern": "portfolio management service(s)?", "mapsTo": "entity:Portfolio Managers"},
    {"pattern": "trading member(s)?", "mapsTo": "entity:Stock Brokers"},
]


def _text_derived_grammar_rules(corpus_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for item in corpus_analysis.get("obligationModalities") or []:
        modality = str(item.get("modality") or "").strip()
        if not modality:
            continue
        rules.append(
            {
                "nonterminal": "CorpusObligationModality",
                "description": f"Obligation language observed {item.get('count', 0)} times in analyzed PDF/text.",
                "productions": [f"'{modality}' ObligationText"],
                "constraints": ["Ground in document.analysis.obligations before citing."],
            }
        )
    if corpus_analysis.get("definedTermGlossary"):
        rules.append(
            {
                "nonterminal": "DefinedTermFromText",
                "description": "Terms explicitly defined in analyzed regulation/circular bodies.",
                "productions": ["DefinedTermRef 'means' DefinitionText"],
                "constraints": [
                    "Resolve via vocabulary.definedTermGlossary and per-document analysis.definitions.",
                ],
            }
        )
    return rules


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _count_by_key(documents: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in documents:
        raw = doc.get(key)
        values = raw if isinstance(raw, list) else ([raw] if raw else [])
        for value in values:
            if value:
                counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _regulation_short_name(title: str) -> str | None:
    match = _REGULATION_TITLE_RE.search(title)
    if match:
        return f"SEBI ({match.group(1).strip()}) Regulations, {match.group(2)}"
    return None


def _extract_regulation_year(title: str) -> str | None:
    match = re.search(r"\b(19|20)\d{2}\b", title)
    return match.group(0) if match else None


def _corpus_instruments(documents: list[dict[str, Any]], hierarchy: str, limit: int | None = None) -> list[dict[str, Any]]:
    items = [d for d in documents if d.get("hierarchy") == hierarchy and d.get("title")]
    items.sort(key=lambda d: d.get("title", ""))
    if limit:
        return items[:limit]
    return items


def _build_regulation_index(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for doc in _corpus_instruments(documents, "regulation"):
        title = doc.get("title", "")
        short = _regulation_short_name(title) or title[:120]
        index.append(
            {
                "id": doc["id"],
                "title": title,
                "shortName": short,
                "year": _extract_regulation_year(title),
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "status": doc.get("status", "in_force"),
                "sourceUrl": doc.get("sourceUrl"),
            }
        )
    return index


def _build_master_circular_index(documents: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    seen_titles: set[str] = set()
    index: list[dict[str, Any]] = []
    for doc in _corpus_instruments(documents, "master_circular"):
        title = re.sub(r"\s+", " ", doc.get("title", "").strip())
        key = title.lower()[:80]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        index.append(
            {
                "id": doc["id"],
                "title": title,
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "issuedAt": doc.get("issuedAt"),
                "status": doc.get("status", "in_force"),
            }
        )
        if len(index) >= limit:
            break
    return index


def _build_act_index(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": doc["id"],
            "title": doc.get("title", ""),
            "issuedAt": doc.get("issuedAt"),
            "status": doc.get("status", "in_force"),
            "sourceUrl": doc.get("sourceUrl"),
        }
        for doc in _corpus_instruments(documents, "act")
    ]


def _build_lexical_index(documents: list[dict[str, Any]], top_n: int = 60) -> list[dict[str, Any]]:
    stop = {
        "sebi", "securities", "india", "board", "exchange", "regulations", "regulation",
        "circular", "dated", "order", "under", "with", "from", "that", "this", "shall",
    }
    counter: Counter[str] = Counter()
    for doc in documents:
        for token in re.findall(r"[a-zA-Z]{4,}", doc.get("title", "").lower()):
            if token not in stop:
                counter[token] += 1
    return [{"term": term, "documentFrequency": count} for term, count in counter.most_common(top_n)]


def _build_section_vocabularies(
    documents: list[dict[str, Any]],
    *,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    document_analyses = document_analyses or {}
    slices: list[dict[str, Any]] = []
    for section, hierarchy in HIERARCHY_BY_SECTION.items():
        section_docs = [doc for doc in documents if doc.get("section") == section]
        if not section_docs:
            continue
        entity_counts = Counter()
        topic_counts = Counter()
        for doc in section_docs:
            for e in doc.get("entities") or []:
                entity_counts[str(e)] += 1
            for t in doc.get("topics") or []:
                topic_counts[str(t)] += 1
        analyzed = sum(1 for doc in section_docs if document_analyses.get(doc["id"], {}).get("textAnalyzed"))
        slices.append(
            {
                "section": section,
                "hierarchy": hierarchy,
                "documentCount": len(section_docs),
                "textAnalyzedCount": analyzed,
                "entities": [
                    {"code": code, "label": SEBI_ENTITY_LABELS.get(code, code), "documentCount": entity_counts.get(code, 0)}
                    for code in SEBI_ENTITY_CODES
                    if entity_counts.get(code, 0) > 0
                ],
                "topics": [
                    {"id": _slug(topic), "label": topic, "documentCount": topic_counts.get(topic, 0)}
                    for topic in SEBI_TOPICS
                    if topic_counts.get(topic, 0) > 0
                ],
                "lexicalIndex": _build_lexical_index(section_docs, top_n=40),
                "obligationSamples": (corpus_analysis or {}).get("obligationSamples", [])[:8],
            }
        )
    return slices


def _build_section_grammars(section_slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "section": item["section"],
            "hierarchy": item["hierarchy"],
            "startSymbol": "RegulatoryAnswer",
            "defaultPath": "entity → topic → hierarchy → document",
            "citePreference": [item["hierarchy"]],
            "navigation": {"axes": ["entity", "topic", item["hierarchy"], "section"], "description": f"Navigate SEBI {item['section']} corpus."},
        }
        for item in section_slices
    ]


def build_vocabulary(
    catalog: dict[str, Any],
    ontology: dict[str, Any] | None = None,
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build controlled vocabulary with corpus statistics for LLM consumption."""
    documents = catalog.get("documents") or []
    text_by_id = text_by_id or {}
    document_analyses = document_analyses or {}
    corpus_analysis = corpus_analysis or (ontology or {}).get("stats", {}).get("corpusAnalysis", {})
    text_count = sum(1 for doc in documents if text_by_id.get(doc.get("id", "")))
    analyzed_count = int(corpus_analysis.get("documentsAnalyzed") or 0)
    entity_counts = _count_by_key(documents, "entities")
    topic_counts = _count_by_key(documents, "topics")
    hierarchy_counts = _count_by_key(documents, "hierarchy")
    status_counts = _count_by_key(documents, "status")
    section_counts = _count_by_key(documents, "section")

    priority_entities = (ontology or {}).get("scope", {}).get("entityPriority", [])

    entities = []
    for code in SEBI_ENTITY_CODES:
        label = SEBI_ENTITY_LABELS[code]
        entities.append(
            {
                "code": code,
                "label": label,
                "description": ENTITY_DESCRIPTIONS.get(code, ""),
                "aliases": ENTITY_ALIASES.get(code, [code]),
                "documentCount": entity_counts.get(code, 0),
                "priority": priority_entities.index(label) + 1 if label in priority_entities else None,
            }
        )

    topics = []
    for topic in SEBI_TOPICS:
        topics.append(
            {
                "id": _slug(topic),
                "label": topic,
                "description": TOPIC_DESCRIPTIONS.get(topic, ""),
                "keywords": TOPIC_KEYWORDS.get(topic, []),
                "documentCount": topic_counts.get(topic, 0),
            }
        )

    hierarchies = []
    for meta in HIERARCHY_META:
        hid = str(meta["id"])
        hierarchies.append(
            {
                **meta,
                "documentCount": hierarchy_counts.get(hid, 0),
                "sectionDocumentCount": section_counts.get(str(meta["section"]), 0),
            }
        )

    relationship_stats = (ontology or {}).get("stats", {}).get("relationshipsByType", {})

    nicknames = []
    for nickname, meta in REGULATION_NICKNAMES.items():
        nicknames.append({"nickname": nickname, **meta})

    return {
        "version": _VOCABULARY_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "source": catalog.get("source", "https://www.sebi.gov.in/legal.html"),
        "corpus": {
            "documentCount": len(documents),
            "fetchedAt": catalog.get("fetchedAt"),
            "enrichedAt": catalog.get("enrichedAt"),
            "sections": catalog.get("sections", list(HIERARCHY_BY_SECTION.keys())),
            "sectionStats": catalog.get("sectionStats", {}),
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "textCoverageRatio": round(text_count / len(documents), 4) if documents else 0.0,
            "analysisCoverageRatio": round(analyzed_count / len(documents), 4) if documents else 0.0,
            "pdfBacked": text_count > 0,
            "deepAnalysis": analyzed_count > 0,
            "corpusAnalysis": corpus_analysis,
        },
        "entities": entities,
        "topics": topics,
        "hierarchies": hierarchies,
        "sections": [
            {"label": section, "hierarchy": hierarchy, "documentCount": section_counts.get(section, 0)}
            for section, hierarchy in HIERARCHY_BY_SECTION.items()
        ],
        "sectionVocabularies": _build_section_vocabularies(
            documents, document_analyses=document_analyses, corpus_analysis=corpus_analysis
        ),
        "regulations": _build_regulation_index(documents),
        "acts": _build_act_index(documents),
        "masterCirculars": _build_master_circular_index(documents),
        "regulationNicknames": nicknames,
        "relationshipTypes": [
            {
                "type": rel_type,
                "label": rel_type.replace("_", " ").title(),
                "edgeCount": relationship_stats.get(rel_type, 0),
                **(_RELATIONSHIP_SEMANTICS.get(rel_type, {})),
            }
            for rel_type in RELATIONSHIP_TYPES
        ],
        "statuses": [
            {
                "id": status,
                "documentCount": status_counts.get(status, 0),
                **STATUS_SEMANTICS.get(status, {}),
            }
            for status in DOCUMENT_STATUSES
        ],
        "abbreviations": ABBREVIATIONS,
        "lexicalIndex": _build_lexical_index(documents),
        "lexicalIndexFromText": corpus_analysis.get("lexicalIndexFromText", []),
        "definedTerms": corpus_analysis.get("topDefinedTerms", []),
        "definedTermGlossary": corpus_analysis.get("definedTermGlossary", []),
        "obligationModalities": corpus_analysis.get("obligationModalities", []),
        "obligationSamples": corpus_analysis.get("obligationSamples", []),
        "crossReferenceKinds": corpus_analysis.get("crossReferenceKinds", []),
        "topCrossReferences": corpus_analysis.get("topCrossReferences", []),
        "regulationRefsFromText": corpus_analysis.get("sectionRefsFromText", []),
        "headingIndexFromText": corpus_analysis.get("headingIndexFromText", []),
        "documentAnalysisSchema": {
            "fields": [
                "summaryFromText",
                "definitions",
                "obligations",
                "crossReferences",
                "headings",
                "sectionRefsFromText",
                "effectiveDateHint",
                "statusHints",
                "keyTerms",
                "entitiesFromText",
                "topicsFromText",
            ],
            "documentsWithAnalysis": analyzed_count,
        },
        "resolutionRules": _RESOLUTION_RULES,
        "normalizationRules": _NORMALIZATION_RULES,
        "taxonomy": taxonomy_schema(),
    }


def build_grammar(
    catalog: dict[str, Any],
    ontology: dict[str, Any] | None = None,
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build query/citation grammar for LLM navigation of the SEBI corpus."""
    documents = catalog.get("documents") or []
    text_by_id = text_by_id or {}
    document_analyses = document_analyses or {}
    corpus_analysis = corpus_analysis or (ontology or {}).get("stats", {}).get("corpusAnalysis", {})
    text_count = sum(1 for doc in documents if text_by_id.get(doc.get("id", "")))
    analyzed_count = int(corpus_analysis.get("documentsAnalyzed") or 0)
    metadata_only = analyzed_count == 0 and (text_count == 0 or text_count < max(1, len(documents) // 2))
    rel_stats = (ontology or {}).get("stats", {}).get("relationshipsByType", {})
    section_slices = _build_section_vocabularies(
        documents, document_analyses=document_analyses, corpus_analysis=corpus_analysis
    )

    return {
        "version": _GRAMMAR_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "startSymbol": "RegulatoryAnswer",
        "navigation": {
            "axes": ["entity", "topic", "hierarchy", "regulation", "document"],
            "defaultPath": "entity → topic → hierarchy → document",
            "alternatePaths": [
                "regulationNickname → regulation → master_circular → circular",
                "topic → entity → regulation",
                "document → implements → regulation",
            ],
            "description": (
                "Resolve user terms to controlled vocabulary, filter documents, "
                "then traverse relationship edges before citing leaf instruments."
            ),
        },
        "hierarchyPrecedence": [
            {
                "id": meta["id"],
                "label": meta["label"],
                "rank": meta["rank"],
                "citeWeight": 10 - int(meta["rank"]),
            }
            for meta in HIERARCHY_META
        ],
        "citationRules": {
            "preferHierarchies": ["act", "regulation", "master_circular"],
            "avoidStatus": ["superseded"],
            "requireTraversal": [
                "implements",
                "consolidates",
                "supersedes",
                "superseded_by",
                "amends",
                "repeals",
                "repealed_by",
            ],
            "chainOrder": [meta["id"] for meta in HIERARCHY_META],
            "titleField": "title",
            "fallbackFields": ["officialId", "entryId", "sourceUrl", "pdfUrl"],
            "metadataOnlySummaries": metadata_only,
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "useDocumentAnalysis": analyzed_count > 0,
            "multiCitationOrder": "parent_before_child",
            "disclaimer": (
                "When textAnalyzedCount > 0, use document.analysis summaries, obligations, and crossReferences. "
                "Traverse relationship edges with evidence snippets before citing leaf instruments. "
                "Verify operative language in official SEBI PDFs before compliance decisions."
            ),
        },
        "relationshipSemantics": _RELATIONSHIP_SEMANTICS,
        "relationshipStats": rel_stats,
        "productions": _GRAMMAR_RULES + _text_derived_grammar_rules(corpus_analysis),
        "queryIntents": _QUERY_INTENTS,
        "sectionGrammars": _build_section_grammars(section_slices),
        "traversalRecipes": _TRAVERSAL_RECIPES,
        "corpusAnalysis": corpus_analysis,
        "corpusObligationSamples": corpus_analysis.get("obligationSamples", []),
        "analysisProductions": [
            {
                "nonterminal": "DefinitionLookup",
                "description": "Resolve a defined term using document.analysis.definitions.",
                "productions": [
                    "DocumentRef '.definitions[]' where term matches user phrase",
                    "RegulationRef '.definitions[]' for parent regulation terms",
                ],
            },
            {
                "nonterminal": "ObligationExtraction",
                "description": "Extract operative requirement from analyzed text.",
                "productions": [
                    "DocumentRef '.obligations[]' where modality in {shall, must, shall not, must not}",
                    "PrimaryObligation backed by obligation snippet + LegalChain",
                ],
            },
            {
                "nonterminal": "EvidenceSnippet",
                "description": "Quote or paraphrase from relationship edge evidence or analysis snippet.",
                "productions": [
                    "RelationshipEdge.evidence",
                    "DocumentRef '.obligations[].snippet'",
                    "DocumentRef '.crossReferences[].snippet'",
                ],
            },
        ],
        "resolutionRules": _RESOLUTION_RULES,
        "normalizationRules": _NORMALIZATION_RULES,
        "answerTemplates": [
            {
                "name": "operative_requirement",
                "template": "For {entity} on {topic}: {legal_chain}. {primary_obligation}. {caveats}",
            },
            {
                "name": "instrument_list",
                "template": "Instruments for {entity}/{topic}: {citation_list} ordered by hierarchy precedence.",
            },
            {
                "name": "supersession_status",
                "template": "{document} is {status}. {supersession_chain}. Operative replacement: {replacement_citation}.",
            },
        ],
        "abstentionRules": [
            {
                "when": "document.status == 'superseded'",
                "action": "Do not cite as operative; follow superseded_by edge or state historical context only.",
            },
            {
                "when": "no implements/consolidates path to parent regulation",
                "action": "State that legal chain is incomplete in metadata; cite document with caveat.",
            },
            {
                "when": "question requires verbatim clause text",
                "action": "Abstain from paraphrasing; direct user to pdfUrl/sourceUrl.",
            },
            {
                "when": "entity resolves to General with low topic match",
                "action": "Ask clarifying question on intermediary type before deep retrieval.",
            },
            {
                "when": "multiple regulations match with similar scores",
                "action": "Present top 2-3 regulation candidates and ask user to confirm.",
            },
            {
                "when": "user asks for legal advice or filing decision",
                "action": "Provide instrument map only; disclaim that this is not legal advice.",
            },
            {
                "when": "document.status == 'under_consultation'",
                "action": "Label as draft/consultation only; do not describe as enforceable.",
            },
            {
                "when": "document.status == 'partially_amended'",
                "action": "Cite with note to read alongside amending instruments.",
            },
        ],
        "systemPrompt": _build_system_prompt(documents, analyzed_count=analyzed_count, corpus_analysis=corpus_analysis),
    }


def _build_system_prompt(
    documents: list[dict[str, Any]],
    *,
    analyzed_count: int = 0,
    corpus_analysis: dict[str, Any] | None = None,
) -> str:
    corpus_analysis = corpus_analysis or {}
    doc_count = len(documents)
    reg_count = sum(1 for d in documents if d.get("hierarchy") == "regulation")
    mc_count = sum(1 for d in documents if d.get("hierarchy") == "master_circular")
    nickname_list = ", ".join(REGULATION_NICKNAMES.keys())
    analysis_clause = (
        f" {analyzed_count} documents include deep PDF/text analysis "
        f"({corpus_analysis.get('totalDefinitions', 0):,} definitions, "
        f"{corpus_analysis.get('totalObligations', 0):,} obligations extracted)."
        if analyzed_count
        else ""
    )
    return (
        f"You are navigating the SEBI legal corpus ({doc_count} instruments: "
        f"{reg_count} regulations, {mc_count} master circulars).{analysis_clause} "
        "Step 1 — Normalize user text and resolve to controlled vocabulary "
        "(entities, topics, regulation nicknames); use vocabulary.definedTermGlossary for terms from body text. "
        f"Known regulation nicknames: {nickname_list}. "
        "Step 2 — Filter documents by entity/topic/hierarchy/status (default in_force). "
        "Step 3 — For analyzed documents, read analysis.obligations and analysis.definitions before citing. "
        "Step 4 — Traverse implements → consolidates → amends → supersedes → repeals before citing leaf circulars. "
        "Step 5 — Structure answers per grammar symbol RegulatoryAnswer with EvidenceSnippet where available."
    )


def attach_llm_artifacts(
    ontology: dict[str, Any],
    catalog: dict[str, Any],
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge vocabulary + grammar into ontology llm block."""
    vocabulary = build_vocabulary(
        catalog,
        ontology,
        text_by_id=text_by_id,
        document_analyses=document_analyses,
        corpus_analysis=corpus_analysis,
    )
    grammar = build_grammar(
        catalog,
        ontology,
        text_by_id=text_by_id,
        document_analyses=document_analyses,
        corpus_analysis=corpus_analysis,
    )
    llm = dict(ontology.get("llm") or {})
    llm.update(
        {
            "vocabularyVersion": vocabulary["version"],
            "grammarVersion": grammar["version"],
            "systemPromptMap": grammar["systemPrompt"],
            "vocabulary": vocabulary,
            "grammar": grammar,
        }
    )
    ontology = dict(ontology)
    ontology["llm"] = llm
    return ontology
