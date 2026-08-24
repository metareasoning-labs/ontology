"""Generate LLM vocabulary and grammar for Income Tax Department corpus."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from regulatory_packages.income_tax.sources import HIERARCHY_BY_SECTION
from regulatory_packages.income_tax.taxonomy import (
    ABBREVIATIONS,
    ACT_NICKNAMES,
    DOCUMENT_STATUSES,
    ENTITY_ALIASES,
    ENTITY_DESCRIPTIONS,
    HIERARCHY_META,
    IT_ASSESSEE_CODES,
    IT_ASSESSEE_LABELS,
    IT_TOPICS,
    RELATIONSHIP_TYPES,
    STATUS_SEMANTICS,
    TOPIC_DESCRIPTIONS,
    TOPIC_KEYWORDS,
    extract_section_refs,
    taxonomy_schema,
)

_VOCABULARY_VERSION = 6
_GRAMMAR_VERSION = 6

_FINANCE_ACT_RE = re.compile(r"finance\s+act,?\s*(\d{4})", re.I)

_RELATIONSHIP_SEMANTICS: dict[str, dict[str, Any]] = {
    "implements": {
        "direction": "source → target",
        "meaning": "Source gives effect to or operates under the target (circular → provision/act).",
        "traverseBeforeCite": True,
        "inverseHint": "Traverse to parent provision or Act before citing implementing circular.",
        "examples": ["Circular on Section 194C → Section 194C provision"],
    },
    "amends": {
        "direction": "source → target",
        "meaning": "Source amends the target; read both for operative position.",
        "traverseBeforeCite": True,
        "inverseHint": "Read amendment together with amended provision/notification.",
        "examples": ["Finance Act amendment → Income-tax Act section", "Notification amending Rule"],
    },
    "supersedes": {
        "direction": "source → target",
        "meaning": "Source replaces the target; target should not be cited as operative.",
        "traverseBeforeCite": True,
        "inverseHint": "Do not cite superseded circulars/notifications unless discussing history.",
        "examples": ["New circular → prior circular on same section"],
    },
    "superseded_by": {
        "direction": "source → target",
        "meaning": "Source was replaced by target (inverse of supersedes).",
        "traverseBeforeCite": True,
        "inverseHint": "Follow to the replacing instrument.",
        "examples": ["Old notification → superseding notification"],
    },
    "clarifies": {
        "direction": "source → target",
        "meaning": "Source clarifies interpretation of target provision or circular.",
        "traverseBeforeCite": True,
        "inverseHint": "Cite clarifying circular read with the provision it interprets.",
        "examples": ["CBDT circular → Section 87A rebate provision"],
    },
    "applies_to": {
        "direction": "document → assessee",
        "meaning": "Document applies to assessee type or entity class.",
        "traverseBeforeCite": False,
        "inverseHint": "Filter corpus by assessee code before deep retrieval.",
        "examples": ["TDS circular → Tax Deductor", "NRI FAQ → Non-Resident"],
    },
    "cross_references": {
        "direction": "bidirectional",
        "meaning": "Related section reference, topic link, or hierarchy parent hint.",
        "traverseBeforeCite": False,
        "inverseHint": "Use for context; verify operative status separately.",
        "examples": ["Provision → related Section 206AA", "Circular → Section 194C"],
    },
    "issued_under": {
        "direction": "document → hierarchy hub",
        "meaning": "Document belongs to legal hierarchy branch (Circulars, Notifications, etc.).",
        "traverseBeforeCite": False,
        "inverseHint": "Use for section filtering only.",
        "examples": ["Circular → hub:circulars", "FAQ → hub:faqs"],
    },
}

_GRAMMAR_RULES: list[dict[str, Any]] = [
    {
        "nonterminal": "TaxAnswer",
        "description": "Top-level structured response for Indian income tax queries.",
        "productions": [
            "ScopeStatement LegalChain PrimaryRule SupportingInstruments* ConflictResolution? StatusCaveats?",
            "CalendarAnswer",
            "ClarifyingQuestion",
            "AbstainResponse",
        ],
    },
    {
        "nonterminal": "ScopeStatement",
        "description": "Assessee, topic, assessment year, and temporal scope.",
        "productions": [
            "'For' AssesseeRef ('on' TopicRef)? ('for AY' AssessmentYear)? ('as of' DateRef)?",
            "'International tax query for' AssesseeRef ('under' TreatyRef)?",
            "'Under' SectionRef ('as applicable to' AssesseeRef)?",
            "'Cross-cutting guidance for' AssesseeRef+",
        ],
    },
    {
        "nonterminal": "LegalChain",
        "description": "Authoritative chain from Act/Rules down to operative circular/notification.",
        "productions": [
            "ActRef? RuleRef? ProvisionRef CircularRef* NotificationRef*",
            "ActNickname '→' ProvisionRef '→' CircularRef*",
            "FinanceActRef? '→' ProvisionRef+",
        ],
        "constraints": [
            "Traverse implements/clarifies/amends edges upward before citing leaf circulars.",
            "Order instruments by hierarchy rank (Act < Rules < Provision < Circular/Notification).",
            "When user cites a section (e.g. 194C, 87A), resolve to provision node first.",
        ],
    },
    {
        "nonterminal": "ActRef",
        "description": "Reference to parent legislation.",
        "productions": ["HierarchyTag ActTitle ('(' Year ')')?", "ActNickname"],
    },
    {
        "nonterminal": "RuleRef",
        "description": "Reference to Income-tax Rules made under the Act.",
        "productions": ["HierarchyTag RuleTitle ('(' Year ')')?"],
    },
    {
        "nonterminal": "ProvisionRef",
        "description": "Reference to a section-wise provision of the Income-tax Act.",
        "productions": [
            "HierarchyTag ('Section' SectionNumber) ProvisionTitle?",
            "SectionRef",
        ],
    },
    {
        "nonterminal": "CircularRef",
        "description": "CBDT circular citation.",
        "productions": ["HierarchyTag CircularTitle ('(' DateRef ')')?", "OfficialId"],
    },
    {
        "nonterminal": "NotificationRef",
        "description": "Notification under the Act or Rules.",
        "productions": ["HierarchyTag NotificationTitle ('(' DateRef ')')?", "OfficialId"],
    },
    {
        "nonterminal": "FinanceActRef",
        "description": "Union Finance Act amending the Income-tax Act.",
        "productions": ["HierarchyTag FinanceActTitle ('(' Year ')')?"],
    },
    {
        "nonterminal": "ActNickname",
        "description": "Short name for primary statutes.",
        "productions": [
            "'IT Act 1961' | 'Income-tax Act' | 'I-T Act' | 'Black Money Act' | 'Wealth-tax Act'",
        ],
    },
    {
        "nonterminal": "SectionRef",
        "description": "Section number reference in the Income-tax Act.",
        "productions": [
            "'Section' SectionNumber",
            "'S.' SectionNumber",
            "SectionNumber",
        ],
        "constraints": [
            "Resolve to provision documents via sectionRefs index.",
            "Disambiguate homonymous references using topic and assessee context.",
        ],
    },
    {
        "nonterminal": "PrimaryRule",
        "description": "The main operative requirement answering the user question.",
        "productions": [
            "Citation 'requires' ObligationText",
            "Citation 'permits' ObligationText",
            "Citation 'exempts' ObligationText",
            "Citation 'prescribes rate' RateText",
            "Citation 'prescribes due date' DateText",
            "Citation 'clarifies' ObligationText",
            "Citation 'defines' DefinitionText",
        ],
    },
    {
        "nonterminal": "CalendarAnswer",
        "description": "Due-date or filing-deadline response from Tax Calendar.",
        "productions": [
            "ScopeStatement CalendarEntry+",
            "'Due dates for' AssesseeRef ':' CalendarEntry+",
        ],
    },
    {
        "nonterminal": "CalendarEntry",
        "description": "Single tax calendar due date item.",
        "productions": [
            "Citation DueDateText ('for' FormRef)?",
        ],
    },
    {
        "nonterminal": "SupportingInstruments",
        "description": "Secondary citations that clarify or qualify the primary rule.",
        "productions": [
            "Citation ('which' QualifierText)?",
            "Citation 'read with' Citation",
            "FaqRef",
        ],
    },
    {
        "nonterminal": "ConflictResolution",
        "description": "When circulars, notifications, or Finance Act amendments overlap.",
        "productions": [
            "'Where instruments overlap,' HierarchyPrecedenceRule",
            "'Later amendment' Citation 'modifies' Citation",
            "'Treaty rate applies over' Citation 'unless' LimitationText",
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
            "'Note:' TreatyVsActWarning",
        ],
    },
    {
        "nonterminal": "ClarifyingQuestion",
        "description": "When assessee/topic/section cannot be resolved confidently.",
        "productions": [
            "'Which assessee type are you asking about?' AssesseeChoice+",
            "'Do you mean' SectionRef '|' SectionRef '?",
            "'Are you asking about' TopicRef '|' TopicRef '?",
            "'Which assessment year (AY)?'",
        ],
    },
    {
        "nonterminal": "AbstainResponse",
        "description": "When corpus cannot support a compliance-grade answer.",
        "productions": [
            "'I cannot verify operative clause text from metadata alone.' PdfPointer",
            "'No in-force instrument found for' AssesseeRef TopicRef 'in this corpus slice.'",
            "'Treaty rate requires country-specific DTAA lookup.' TreatyPointer",
        ],
    },
    {
        "nonterminal": "Citation",
        "description": "Reference to an ITD instrument in the corpus.",
        "productions": [
            "HierarchyTag DocumentTitle ('(' OfficialId | DateRef ')')?",
            "DocumentId",
        ],
        "constraints": [
            "Use full document title, not shortTitle.",
            "Include officialId, sectionRefs, sourceUrl, or pdfUrl when available.",
            "Skip documents with status=superseded unless user asks for history.",
            "Prefix with hierarchy badge (Act, Rules, Provision, Circular, Notification).",
        ],
    },
    {
        "nonterminal": "AssesseeRef",
        "description": "Controlled assessee reference.",
        "productions": ["AssesseeLabel | AssesseeCode | AssesseeAlias"],
        "constraints": [
            "Must resolve to a code in entityCodes vocabulary.",
            "If multiple assessees match, prefer the most specific; else ask ClarifyingQuestion.",
        ],
    },
    {
        "nonterminal": "TopicRef",
        "description": "Controlled topic reference.",
        "productions": ["TopicLabel | TopicKeyword"],
        "constraints": ["Must resolve to a label in topics vocabulary."],
    },
    {
        "nonterminal": "HierarchyTag",
        "description": "Instrument type badge.",
        "productions": [
            "'Act' | 'Rules' | 'Provision' | 'Circular' | 'Notification' | "
            "'Finance Act' | 'Finance Bill' | 'FAQ' | 'Tax Calendar' | 'International'",
        ],
    },
    {
        "nonterminal": "HierarchyPrecedenceRule",
        "description": "Conflict resolution by legal hierarchy.",
        "productions": [
            "'prefer' ProvisionRef 'over' CircularRef",
            "'Act/Rules/Provision prevail over circular guidance'",
            "'Finance Act amendment overrides prior provision text'",
            "'DTAA treaty rate applies subject to' SectionRef 'limitation'",
        ],
    },
    {
        "nonterminal": "PdfPointer",
        "description": "Pointer to official source when text is required.",
        "productions": ["'See official PDF:' PdfUrl | SourceUrl"],
    },
    {
        "nonterminal": "TreatyRef",
        "description": "DTAA treaty country or article reference.",
        "productions": ["CountryName 'DTAA' | 'Article' ArticleNumber"],
    },
    {
        "nonterminal": "TreatyPointer",
        "description": "Pointer to international/DTAA corpus slice.",
        "productions": ["'See DTAA corpus for' CountryName TreatyRef"],
    },
]

_QUERY_INTENTS: list[dict[str, Any]] = [
    {
        "intent": "due_date_lookup",
        "examples": [
            "When is ITR due for individuals?",
            "TDS payment due dates for Q4",
            "Advance tax instalment dates",
        ],
        "start": {"axis": "tax_calendar", "then": "assessee"},
        "traverse": ["applies_to", "cross_references"],
        "citePreference": ["tax_calendar", "notification", "circular"],
        "answerShape": "CalendarAnswer",
    },
    {
        "intent": "section_circular_chain",
        "examples": [
            "Circulars on Section 194C",
            "Clarification on Section 87A rebate",
            "Notifications under Section 195",
        ],
        "start": {"axis": "section_ref", "then": "hierarchy"},
        "traverse": ["cross_references", "clarifies", "implements"],
        "citePreference": ["provision", "circular", "notification"],
    },
    {
        "intent": "provision_lookup",
        "examples": [
            "What does Section 80C say?",
            "TDS rate under Section 194J",
            "Capital gains exemption under Section 54",
        ],
        "start": {"axis": "section_ref", "matchBy": "sectionRefs"},
        "traverse": ["cross_references", "amends", "clarifies"],
        "citePreference": ["provision", "circular", "finance_act"],
        "requiresPdf": True,
    },
    {
        "intent": "international_withholding",
        "examples": [
            "DTAA rate for US dividends",
            "Section 195 TDS for non-resident",
            "Form 15CA requirements for remittance",
        ],
        "start": {"axis": "international", "topic": "Withholding Tax"},
        "traverse": ["cross_references", "applies_to", "clarifies"],
        "citePreference": ["international", "provision", "circular"],
    },
    {
        "intent": "transfer_pricing_guidance",
        "examples": [
            "Transfer pricing documentation requirements",
            "Safe harbour rules for related party transactions",
            "APA application process",
        ],
        "start": {"axis": "topic", "topicFilter": "Transfer Pricing"},
        "traverse": ["applies_to", "cross_references", "clarifies"],
        "citePreference": ["circular", "notification", "provision"],
    },
    {
        "intent": "faq_guidance",
        "examples": [
            "How to file revised return?",
            "FAQ on tax audit applicability",
            "How to verify ITR?",
        ],
        "start": {"axis": "faq"},
        "traverse": ["cross_references", "applies_to"],
        "citePreference": ["faq", "circular", "provision"],
    },
    {
        "intent": "budget_update",
        "examples": [
            "Budget 2025 tax slab changes",
            "Finance Act 2025 amendments to Section 115BAC",
            "New TDS sections introduced in Finance Act",
        ],
        "start": {"axis": "whats_new", "then": "finance_act"},
        "traverse": ["amends", "cross_references"],
        "citePreference": ["finance_act", "finance_bill", "whats_new", "provision"],
    },
    {
        "intent": "tds_compliance_checklist",
        "examples": [
            "TDS compliance for contract payments under 194C",
            "Lower deduction certificate requirements",
            "TDS return filing for deductors",
        ],
        "start": {"axis": "assessee", "entityFilter": "Tax Deductor", "topic": "TDS / TCS"},
        "traverse": ["applies_to", "implements", "cross_references"],
        "citePreference": ["provision", "circular", "notification"],
        "answerShape": "PrimaryRule+",
    },
    {
        "intent": "supersession_check",
        "examples": [
            "Is this circular still in force?",
            "What replaced Circular No. 1/2020?",
            "Has this notification been superseded?",
        ],
        "start": {"axis": "document", "matchBy": "titleOrId"},
        "traverse": ["supersedes", "superseded_by", "amends"],
        "citePreference": ["circular", "notification", "provision"],
    },
    {
        "intent": "deduction_eligibility",
        "examples": [
            "Can I claim 80D for parents?",
            "Section 80C limit and eligible investments",
            "Rebate under Section 87A for AY 2025-26",
        ],
        "start": {"axis": "topic", "topicFilter": "Deductions / Exemptions", "then": "assessee"},
        "traverse": ["applies_to", "clarifies", "cross_references"],
        "citePreference": ["provision", "circular", "faq"],
    },
    {
        "intent": "penalty_interest",
        "examples": [
            "Penalty for late filing of ITR",
            "Interest under Section 234B for short payment of advance tax",
            "Prosecution for TDS default",
        ],
        "start": {"axis": "topic", "topicFilter": "Penalties / Prosecution"},
        "traverse": ["cross_references", "applies_to"],
        "citePreference": ["provision", "circular", "notification"],
    },
    {
        "intent": "return_filing_procedure",
        "examples": [
            "Which ITR form for salaried individual?",
            "Documents required for ITR-1",
            "How to report foreign income in ITR",
        ],
        "start": {"axis": "topic", "topicFilter": "Return Filing / Compliance", "then": "assessee"},
        "traverse": ["applies_to", "cross_references"],
        "citePreference": ["faq", "circular", "notification"],
    },
]

_TRAVERSAL_RECIPES: list[dict[str, Any]] = [
    {
        "name": "section_to_provision_chain",
        "steps": [
            "Resolve SectionRef to provision via sectionRefs index",
            "Follow clarifies/implements incoming from circulars",
            "Check amends from Finance Act notifications",
        ],
        "useWhen": "User cites or asks about a specific section number",
    },
    {
        "name": "assessee_topic_filter",
        "steps": [
            "Resolve AssesseeRef",
            "Resolve TopicRef",
            "Filter documents by applies_to + topic tags",
        ],
        "useWhen": "Broad questions like 'TDS rules for individuals on salary'",
    },
    {
        "name": "circular_to_parent_provision",
        "steps": [
            "Start at circular",
            "Follow implements/clarifies (outgoing) to provision",
            "Stop at Act if provision missing",
        ],
        "useWhen": "User cites or asks about a specific circular",
    },
    {
        "name": "supersession_walk",
        "steps": [
            "Check document status",
            "If superseded follow superseded_by",
            "If amends read amends target",
        ],
        "useWhen": "User asks if instrument is still in force",
    },
    {
        "name": "finance_act_amendment",
        "steps": [
            "Find Finance Act for assessment year",
            "Follow amends edges to provisions",
            "Read with pre-amendment circulars if partially_amended",
        ],
        "useWhen": "User asks about Budget/Finance Act changes",
    },
    {
        "name": "dtaa_withholding_lookup",
        "steps": [
            "Resolve country/treaty from international corpus",
            "Cross-reference Section 195/206AA provisions",
            "Apply treaty rate subject to limitation-of-benefits caveats",
        ],
        "useWhen": "User asks about non-resident withholding or DTAA rates",
    },
    {
        "name": "nickname_resolution",
        "steps": [
            "Match ActNickname or abbreviation",
            "Map to fullName in actNicknames",
            "Filter corpus by title or hierarchy=act",
        ],
        "useWhen": "User says IT Act, I-T Act, Black Money Act, etc.",
    },
]

_RESOLUTION_RULES: list[dict[str, str]] = [
    {"step": "normalize", "rule": "Lowercase, strip punctuation, expand abbreviations via abbreviations map."},
    {"step": "assessee", "rule": "Match assesseeCodes, assesseeLabels, then assessee aliases (longest match wins)."},
    {"step": "topic", "rule": "Match topic labels, then topic keywords (count hits; threshold ≥1)."},
    {"step": "section", "rule": "Match sectionRefs index and section patterns (194C, 87A, 80C)."},
    {"step": "act", "rule": "Match actNicknames first, then act titles in corpus."},
    {"step": "hierarchy", "rule": "If user says circular/notification/provision/faq, set hierarchy filter."},
    {"step": "status", "rule": "Default to in_force unless user asks for history, repealed, or superseded instruments."},
    {"step": "disambiguate", "rule": "If General assessee + low topic confidence, emit ClarifyingQuestion."},
]

_NORMALIZATION_RULES: list[dict[str, str]] = [
    {"pattern": "income tax act", "mapsTo": "IT Act 1961"},
    {"pattern": "i-?t act", "mapsTo": "IT Act 1961"},
    {"pattern": "non-?resident indian", "mapsTo": "assessee:Non-Resident"},
    {"pattern": "tax deducted at source", "mapsTo": "topic:TDS / TCS"},
    {"pattern": "chapter vi-?a", "mapsTo": "topic:Deductions / Exemptions"},
    {"pattern": "advance tax", "mapsTo": "topic:Advance Tax / Interest"},
    {"pattern": "double taxation", "mapsTo": "topic:International Tax / DTAA"},
    {"pattern": "assessment year", "mapsTo": "AY"},
]


def _merge_section_ref_index(
    metadata_refs: list[dict[str, Any]],
    text_refs: list[dict[str, Any]],
    *,
    limit: int = 150,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        str(item.get("section")): dict(item) for item in metadata_refs if item.get("section")
    }
    for item in text_refs:
        section = str(item.get("section") or "")
        if not section:
            continue
        existing = merged.get(section)
        if existing:
            existing["textDocumentFrequency"] = item.get("documentFrequency", 0)
            existing["documentCount"] = max(int(existing.get("documentCount") or 0), int(item.get("documentFrequency") or 0))
        else:
            merged[section] = {
                "section": section,
                "documentCount": item.get("documentFrequency", 0),
                "textDocumentFrequency": item.get("documentFrequency", 0),
                "sampleTitle": "",
                "source": "text",
            }
    return sorted(merged.values(), key=lambda row: int(row.get("documentCount") or 0), reverse=True)[:limit]


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
                "description": "Terms explicitly defined in analyzed instrument bodies.",
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


def _corpus_instruments(documents: list[dict[str, Any]], hierarchy: str, limit: int | None = None) -> list[dict[str, Any]]:
    items = [d for d in documents if d.get("hierarchy") == hierarchy and d.get("title")]
    items.sort(key=lambda d: d.get("title", ""))
    if limit:
        return items[:limit]
    return items


def _extract_year(title: str) -> str | None:
    match = re.search(r"\b(19|20)\d{2}\b", title)
    return match.group(0) if match else None


def _build_act_index(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for doc in _corpus_instruments(documents, "act"):
        title = doc.get("title", "")
        index.append(
            {
                "id": doc["id"],
                "title": title,
                "year": _extract_year(title),
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "status": doc.get("status", "in_force"),
                "sourceUrl": doc.get("sourceUrl"),
            }
        )
    return index


def _build_finance_act_index(documents: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    seen: set[str] = set()
    index: list[dict[str, Any]] = []
    for doc in _corpus_instruments(documents, "finance_act"):
        title = re.sub(r"\s+", " ", doc.get("title", "").strip())
        key = title.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        year_match = _FINANCE_ACT_RE.search(title)
        index.append(
            {
                "id": doc["id"],
                "title": title,
                "year": year_match.group(1) if year_match else _extract_year(title),
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "status": doc.get("status", "in_force"),
                "sourceUrl": doc.get("sourceUrl"),
            }
        )
        if len(index) >= limit:
            break
    return index


def _build_section_ref_index(documents: list[dict[str, Any]], top_n: int = 100) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    sample_titles: dict[str, str] = {}
    for doc in documents:
        refs = doc.get("sectionRefs") or extract_section_refs(
            " ".join(filter(None, [doc.get("title", ""), doc.get("summary", "")]))
        )
        for ref in refs:
            counter[ref] += 1
            if ref not in sample_titles:
                sample_titles[ref] = doc.get("title", "")[:120]
    return [
        {
            "section": section,
            "documentCount": count,
            "sampleTitle": sample_titles.get(section, ""),
        }
        for section, count in counter.most_common(top_n)
    ]


def _build_circular_index(documents: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for doc in _corpus_instruments(documents, "circular", limit):
        index.append(
            {
                "id": doc["id"],
                "title": doc.get("title", ""),
                "officialId": doc.get("officialId"),
                "sectionRefs": doc.get("sectionRefs", []),
                "entities": doc.get("entities", []),
                "topics": doc.get("topics", []),
                "issuedAt": doc.get("issuedAt"),
                "status": doc.get("status", "in_force"),
            }
        )
    return index


def _build_lexical_index(documents: list[dict[str, Any]], top_n: int = 60) -> list[dict[str, Any]]:
    stop = {
        "income", "tax", "india", "section", "circular", "notification", "dated",
        "under", "with", "from", "that", "this", "shall", "department", "government",
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
        entity_counts = _count_by_key(section_docs, "entities")
        topic_counts = _count_by_key(section_docs, "topics")
        analyzed = sum(1 for doc in section_docs if document_analyses.get(doc["id"], {}).get("textAnalyzed"))
        slices.append(
            {
                "section": section,
                "hierarchy": hierarchy,
                "documentCount": len(section_docs),
                "textAnalyzedCount": analyzed,
                "entities": [
                    {"code": code, "label": IT_ASSESSEE_LABELS.get(code, code), "documentCount": entity_counts.get(code, 0)}
                    for code in IT_ASSESSEE_CODES
                    if entity_counts.get(code, 0) > 0
                ],
                "topics": [
                    {"id": _slug(topic), "label": topic, "documentCount": topic_counts.get(topic, 0)}
                    for topic in IT_TOPICS
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
            "navigation": {"axes": ["entity", "topic", item["hierarchy"], "section"], "description": f"Navigate Income Tax {item['section']} corpus."},
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

    priority_assessees = (ontology or {}).get("scope", {}).get("entityPriority", [])

    entities = []
    for code in IT_ASSESSEE_CODES:
        label = IT_ASSESSEE_LABELS[code]
        entities.append(
            {
                "code": code,
                "label": label,
                "description": ENTITY_DESCRIPTIONS.get(code, ""),
                "aliases": ENTITY_ALIASES.get(code, [code]),
                "documentCount": entity_counts.get(code, 0),
                "priority": priority_assessees.index(label) + 1 if label in priority_assessees else None,
            }
        )

    topics = []
    for topic in IT_TOPICS:
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

    nicknames = [{"nickname": nickname, **meta} for nickname, meta in ACT_NICKNAMES.items()]

    return {
        "version": _VOCABULARY_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "source": catalog.get("source", "https://www.incometaxindia.gov.in"),
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
        "acts": _build_act_index(documents),
        "financeActs": _build_finance_act_index(documents),
        "sectionRefs": _merge_section_ref_index(
            _build_section_ref_index(documents),
            corpus_analysis.get("sectionRefsFromText", []),
        ),
        "circulars": _build_circular_index(documents),
        "actNicknames": nicknames,
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
        "headingIndexFromText": corpus_analysis.get("headingIndexFromText", []),
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
    """Build query/citation grammar for LLM navigation of the ITD corpus."""
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
        "startSymbol": "TaxAnswer",
        "navigation": {
            "axes": ["assessee", "topic", "hierarchy", "section_ref", "document"],
            "defaultPath": "assessee → topic → hierarchy → document",
            "alternatePaths": [
                "section_ref → provision → circular → notification",
                "actNickname → act → provision → circular",
                "topic → assessee → faq",
                "document → implements/clarifies → provision",
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
            "preferHierarchies": ["act", "rule", "provision", "finance_act"],
            "avoidStatus": ["superseded"],
            "requireTraversal": ["implements", "clarifies", "supersedes", "superseded_by", "amends"],
            "chainOrder": [meta["id"] for meta in HIERARCHY_META],
            "titleField": "title",
            "fallbackFields": ["officialId", "sectionRefs", "sourceUrl", "pdfUrl"],
            "calendarHierarchy": "tax_calendar",
            "faqHierarchy": "faq",
            "internationalHierarchy": "international",
            "metadataOnlySummaries": metadata_only,
            "textExtractedCount": text_count,
            "textAnalyzedCount": analyzed_count,
            "useDocumentAnalysis": analyzed_count > 0,
            "multiCitationOrder": "parent_before_child",
            "disclaimer": (
                "When textAnalyzedCount > 0, use document.analysis summaries, obligations, and crossReferences. "
                "Traverse implements/clarifies/amends/supersedes edges before citing leaf instruments. "
                "Verify operative language in official ITD PDFs before compliance decisions."
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
        "resolutionRules": _RESOLUTION_RULES,
        "normalizationRules": _NORMALIZATION_RULES,
        "answerTemplates": [
            {
                "name": "operative_requirement",
                "template": "For {assessee} on {topic}: {legal_chain}. {primary_rule}. {caveats}",
            },
            {
                "name": "due_date_list",
                "template": "Due dates for {assessee} (AY {assessment_year}): {calendar_entries}.",
            },
            {
                "name": "section_guidance",
                "template": "Section {section}: {provision_citation}. Clarifications: {circular_list}.",
            },
            {
                "name": "supersession_status",
                "template": "{document} is {status}. {supersession_chain}. Operative replacement: {replacement_citation}.",
            },
        ],
        "systemPrompt": (
            f"You navigate the Income Tax Department corpus ({len(documents):,} public items from "
            "incometaxindia.gov.in). "
            f"{analyzed_count:,} documents have deep PDF/text analysis "
            f"({corpus_analysis.get('totalDefinitions', 0):,} definitions, "
            f"{corpus_analysis.get('totalObligations', 0):,} obligations extracted). "
            "Resolve assessee type, topic, and section references using the controlled vocabulary; "
            "use vocabulary.definedTermGlossary and document.analysis for terms found in body text. "
            "Traverse Act/Rules/Provision → Circular/Notification edges "
            "(implements, clarifies, amends) before citing leaf instruments. Use Tax Calendar for "
            "due dates, FAQs for procedural guidance, International/DTAA slice for treaty and "
            "withholding queries, Finance Acts for Budget amendments. Structure answers as TaxAnswer "
            "with LegalChain, PrimaryRule, and StatusCaveats. Default to in_force instruments; "
            "follow superseded_by when status is superseded. Metadata summaries are not operative "
            "legal text — point to official PDFs when clause-level certainty is required."
        ),
    }


def attach_llm_artifacts(
    ontology: dict[str, Any],
    catalog: dict[str, Any],
    *,
    text_by_id: dict[str, str] | None = None,
    document_analyses: dict[str, dict[str, Any]] | None = None,
    corpus_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    out = dict(ontology)
    out["llm"] = llm
    return out
