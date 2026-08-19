"""Generate Semantica ontologies from regulatory source text (Postgres + PDFs).

Does NOT use pre-built multicatalyst ontology.json / vocabulary / grammar.
Serious pipeline:
  1. Read instrument metadata + extracted text from Postgres
  2. Semantica ML NER (spaCy) + regulatory obligation/definition patterns
  3. Optional LLM triplet + TBox refinement when ANTHROPIC_API_KEY / OPENAI_API_KEY is set
  4. Semantica OntologyGenerator → OWL classes/properties
  5. Materialize ABox + sync Oxigraph / Turtle exports
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import psycopg
from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef
from semantica.ontology import OntologyEngine, OntologyGenerator
from semantica.semantic_extract.ner_extractor import NERExtractor
from semantica.semantic_extract.triplet_extractor import TripletExtractor
from semantica.semantic_extract.types import Triplet
from semantica.triplet_store import TripletStore

from ontology_lib.config import REPO_ROOT

CORPORA = ("sebi", "rbi", "gst", "insurance", "income_tax")
REG_NS = Namespace("https://ontology.metareasoning.ai/regulatory#")
CORE_NS = Namespace("https://ontology.metareasoning.ai/core#")

# Income Tax alone has ~57k instruments; default serious runs use a rich subset unless --full.
DEFAULT_DOC_LIMITS = {
    "gst": None,
    "rbi": None,
    "insurance": None,
    "sebi": None,
    "income_tax": 3000,
}

NER_LABEL_TO_CLASS = {
    "ORG": "Organization",
    "PERSON": "Person",
    "GPE": "Jurisdiction",
    "LOC": "Location",
    "DATE": "Date",
    "MONEY": "MonetaryAmount",
    "LAW": "LegalInstrument",
    "PRODUCT": "Product",
    "EVENT": "Event",
    "NORP": "Group",
    "FAC": "Facility",
    "PERCENT": "Percentage",
    "CARDINAL": "Quantity",
    "ORDINAL": "Ordinal",
    "TIME": "Time",
    "WORK_OF_ART": "Work",
    "LANGUAGE": "Language",
}

OBLIGATION_RE = re.compile(
    r"(?P<sent>[^.!?\n]{20,400}?\b(?:shall|must|is required to|are required to|liable to|ought to)\b[^.!?\n]{10,400}[.!?])",
    re.IGNORECASE,
)
DEFINITION_RE = re.compile(
    r"(?P<sent>[^.!?\n]{10,300}?\b(?:means|shall mean|is defined as|refers to)\b[^.!?\n]{10,300}[.!?])",
    re.IGNORECASE,
)
CROSS_REF_RE = re.compile(
    r"\b(?:section|rule|regulation|circular|notification|clause|schedule)\s+"
    r"([A-Za-z0-9()./\-]+)",
    re.IGNORECASE,
)


def _slug(value: str, *, max_len: int = 120) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", (value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return (text or "unnamed")[:max_len]


def _iri(base: str, *parts: str) -> str:
    joined = "/".join(quote(p, safe=":_-.") for p in parts if p)
    return f"{base.rstrip('/')}/{joined}"


def _database_url() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://ontology:ontology_dev_password@127.0.0.1:5432/ontology",
    )
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
    )


def pdf_path_for(corpus: str, doc_id: str) -> Path:
    return REPO_ROOT / "corpus" / "regulatory" / "files" / corpus / "documents" / doc_id / "source.pdf"


def detect_llm_provider() -> tuple[str | None, str | None]:
    """Return (provider, model) when an API key is available in the environment."""
    explicit = (os.environ.get("SEMANTICA_LLM_PROVIDER") or "").strip().lower() or None
    model = (os.environ.get("SEMANTICA_LLM_MODEL") or "").strip() or None
    if os.environ.get("ANTHROPIC_API_KEY"):
        return explicit or "anthropic", model or "claude-sonnet-4-20250514"
    if os.environ.get("OPENAI_API_KEY"):
        return explicit or "openai", model or "gpt-4o-mini"
    return None, None


@dataclass
class SourceDocument:
    doc_id: str
    title: str
    hierarchy: str
    status: str
    official_id: str | None
    source_url: str | None
    pdf_url: str | None
    issued_at: str | None
    text: str
    char_count: int
    page_count: int


@dataclass
class ExtractionBundle:
    corpus: str
    documents: list[SourceDocument] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def fetch_source_documents(corpus: str, *, limit: int | None = None) -> list[SourceDocument]:
    """Load regulatory instruments + extracted text, richest text first."""
    sql = """
        SELECT d.doc_id, d.title, d.hierarchy, d.status, d.official_id,
               d.source_url, d.pdf_url, d.issued_at,
               coalesce(t.text, ''), coalesce(t.char_count, 0), coalesce(t.page_count, 0)
        FROM mc_regulatory_corpus_documents d
        LEFT JOIN mc_regulatory_corpus_text t ON t.document_id = d.id
        WHERE d.corpus = %s
        ORDER BY coalesce(t.char_count, 0) DESC, d.doc_id
    """
    params: list[Any] = [corpus]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with psycopg.connect(_database_url()) as conn:
        rows = conn.execute(sql, params).fetchall()

    docs: list[SourceDocument] = []
    for row in rows:
        docs.append(
            SourceDocument(
                doc_id=row[0],
                title=row[1] or row[0],
                hierarchy=row[2] or "instrument",
                status=row[3] or "in_force",
                official_id=row[4],
                source_url=row[5],
                pdf_url=row[6],
                issued_at=row[7],
                text=row[8] or "",
                char_count=int(row[9] or 0),
                page_count=int(row[10] or 0),
            )
        )
    return docs


def _entity_label(entity: Any) -> tuple[str, str]:
    text = getattr(entity, "text", None) or (entity.get("text") if isinstance(entity, dict) else str(entity))
    label = (
        getattr(entity, "label_", None)
        or getattr(entity, "label", None)
        or (entity.get("label") if isinstance(entity, dict) else "Entity")
    )
    return str(text).strip(), str(label).strip() or "Entity"


def _map_ner_class(label: str) -> str:
    return NER_LABEL_TO_CLASS.get(label.upper(), _slug(label).title().replace("_", "") or "Entity")


def _add_entity(
    bundle: ExtractionBundle,
    *,
    etype: str,
    name: str,
    label: str,
    properties: dict[str, Any],
    entity_names: set[tuple[str, str]],
) -> None:
    key = (etype, name.lower())
    if key in entity_names:
        return
    entity_names.add(key)
    bundle.entities.append(
        {
            "type": etype,
            "name": name,
            "label": label,
            "properties": properties,
        }
    )


def _extract_regulatory_patterns(
    bundle: ExtractionBundle,
    *,
    doc: SourceDocument,
    excerpt: str,
    entity_names: set[tuple[str, str]],
    rel_counter: Counter[str],
) -> None:
    """Domain patterns that matter for regulatory ontologies (beyond generic NER)."""
    for i, match in enumerate(OBLIGATION_RE.finditer(excerpt)):
        if i >= 12:
            break
        sent = re.sub(r"\s+", " ", match.group("sent")).strip()
        oid = f"obligation:{doc.doc_id}:{i}"
        _add_entity(
            bundle,
            etype="Obligation",
            name=oid,
            label=sent[:180],
            properties={"sourceDoc": doc.doc_id, "modality": "shall_or_must"},
            entity_names=entity_names,
        )
        bundle.relationships.append({"type": "imposes", "source": doc.doc_id, "target": oid})
        rel_counter["imposes"] += 1

    for i, match in enumerate(DEFINITION_RE.finditer(excerpt)):
        if i >= 8:
            break
        sent = re.sub(r"\s+", " ", match.group("sent")).strip()
        did = f"definition:{doc.doc_id}:{i}"
        _add_entity(
            bundle,
            etype="Definition",
            name=did,
            label=sent[:180],
            properties={"sourceDoc": doc.doc_id},
            entity_names=entity_names,
        )
        bundle.relationships.append({"type": "defines", "source": doc.doc_id, "target": did})
        rel_counter["defines"] += 1

    seen_refs: set[str] = set()
    for i, match in enumerate(CROSS_REF_RE.finditer(excerpt)):
        if i >= 20:
            break
        ref = match.group(0).strip()
        key = ref.lower()
        if key in seen_refs or len(ref) > 80:
            continue
        seen_refs.add(key)
        rid = f"ref:{_slug(ref)}"
        _add_entity(
            bundle,
            etype="LegalReference",
            name=rid,
            label=ref,
            properties={"sourceDoc": doc.doc_id},
            entity_names=entity_names,
        )
        bundle.relationships.append({"type": "cites", "source": doc.doc_id, "target": rid})
        rel_counter["cites"] += 1


def _fast_dep_triplets(spacy_doc: Any, *, limit: int = 25) -> list[tuple[str, str, str]]:
    """Cheap subject–verb–object triples from spaCy deps (avoids Semantica RelationExtractor)."""
    out: list[tuple[str, str, str]] = []
    for token in spacy_doc:
        if token.dep_ not in {"nsubj", "nsubjpass"} or token.head.pos_ != "VERB":
            continue
        subj = token.text.strip()
        pred = (token.head.lemma_ or token.head.text).strip().lower()
        if not re.fullmatch(r"[a-z][a-z_-]{1,40}", pred):
            continue
        objs = [
            c.text.strip()
            for c in token.head.children
            if c.dep_ in {"dobj", "attr", "pobj", "dative", "oprd"} and c.text.strip()
        ]
        if not subj or not objs:
            continue
        for obj in objs[:2]:
            if (
                2 <= len(subj) <= 80
                and 2 <= len(obj) <= 80
                and re.search(r"[A-Za-z]", subj)
                and re.search(r"[A-Za-z]", obj)
            ):
                out.append((subj, pred, obj))
                if len(out) >= limit:
                    return out
    return out



def _turbo_chunk_worker(chunk: list[dict[str, Any]]) -> dict[str, Any]:
    """Process a chunk of docs with regex-only regulatory patterns (no spaCy)."""
    entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    rel_counter: Counter[str] = Counter()
    entity_names: set[tuple[str, str]] = set()
    extracted = 0

    class _Bundle:
        pass

    for item in chunk:
        doc = SourceDocument(
            doc_id=item["doc_id"],
            title=item["title"],
            hierarchy=item["hierarchy"],
            status=item["status"],
            official_id=item.get("official_id"),
            source_url=item.get("source_url"),
            pdf_url=item.get("pdf_url"),
            issued_at=item.get("issued_at"),
            text=item.get("text") or "",
            char_count=int(item.get("char_count") or 0),
            page_count=int(item.get("page_count") or 0),
        )
        excerpt = item.get("excerpt") or ""
        fake = ExtractionBundle(corpus=item.get("corpus") or "unknown")
        # reuse pattern helper via a tiny shim bundle
        _extract_regulatory_patterns(
            fake,
            doc=doc,
            excerpt=excerpt,
            entity_names=entity_names,
            rel_counter=rel_counter,
        )
        entities.extend(fake.entities)
        relationships.extend(fake.relationships)
        extracted += 1
    return {
        "entities": entities,
        "relationships": relationships,
        "rel_counter": dict(rel_counter),
        "extracted": extracted,
    }


def extract_turbo(
    docs: list[SourceDocument],
    *,
    corpus: str,
    text_chars: int = 2000,
    n_process: int = 8,
    chunk_size: int = 500,
) -> ExtractionBundle:
    """CPU-only turbo extract: structural nodes + obligation/definition/citation regex."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    bundle = ExtractionBundle(corpus=corpus, documents=docs)
    entity_names: set[tuple[str, str]] = set()
    rel_counter: Counter[str] = Counter()

    for doc in docs:
        hier = _slug(doc.hierarchy).title().replace("_", "") or "RegulatoryInstrument"
        _add_entity(
            bundle,
            etype=hier,
            name=doc.doc_id,
            label=doc.title[:200],
            properties={
                "hierarchy": doc.hierarchy,
                "status": doc.status,
                "officialId": doc.official_id,
                "sourceUrl": doc.source_url,
                "pdfUrl": doc.pdf_url,
                "issuedAt": doc.issued_at,
                "charCount": doc.char_count,
                "pageCount": doc.page_count,
                "hasPdf": pdf_path_for(corpus, doc.doc_id).is_file(),
            },
            entity_names=entity_names,
        )
        _add_entity(
            bundle,
            etype="InstrumentHierarchy",
            name=f"hierarchy:{doc.hierarchy}",
            label=doc.hierarchy,
            properties={},
            entity_names=entity_names,
        )
        bundle.relationships.append(
            {"type": "inHierarchy", "source": doc.doc_id, "target": f"hierarchy:{doc.hierarchy}"}
        )

    payloads: list[dict[str, Any]] = []
    for doc in docs:
        text_body = (doc.text or "").strip()
        if not text_body:
            continue
        payloads.append(
            {
                "corpus": corpus,
                "doc_id": doc.doc_id,
                "title": doc.title,
                "hierarchy": doc.hierarchy,
                "status": doc.status,
                "official_id": doc.official_id,
                "source_url": doc.source_url,
                "pdf_url": doc.pdf_url,
                "issued_at": doc.issued_at,
                "text": "",
                "char_count": doc.char_count,
                "page_count": doc.page_count,
                "excerpt": text_body[:text_chars],
            }
        )

    chunks = [payloads[i : i + chunk_size] for i in range(0, len(payloads), chunk_size)]
    workers = max(1, min(n_process, os.cpu_count() or 1, len(chunks) or 1))
    extracted_docs = 0
    print(f"  turbo: {len(payloads)} docs, {len(chunks)} chunks, {workers} workers", flush=True)

    if workers == 1 or len(chunks) <= 1:
        results = [_turbo_chunk_worker(c) for c in chunks]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_turbo_chunk_worker, c) for c in chunks]
            done_n = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done_n += 1
                if done_n % max(1, len(chunks) // 10) == 0 or done_n == len(chunks):
                    print(f"  turbo chunks {done_n}/{len(chunks)}...", flush=True)

    for res in results:
        extracted_docs += int(res.get("extracted") or 0)
        for ent in res.get("entities") or []:
            _add_entity(
                bundle,
                etype=str(ent["type"]),
                name=str(ent["name"]),
                label=str(ent.get("label") or ent["name"]),
                properties=dict(ent.get("properties") or {}),
                entity_names=entity_names,
            )
        for rel in res.get("relationships") or []:
            bundle.relationships.append(rel)
        for k, v in (res.get("rel_counter") or {}).items():
            rel_counter[k] += int(v)

    # Dedup relationships
    seen: set[tuple[str, str, str]] = set()
    dedup_rels = []
    for rel in bundle.relationships:
        key = (str(rel["type"]), str(rel["source"]), str(rel["target"]))
        if key in seen:
            continue
        seen.add(key)
        dedup_rels.append(rel)
    bundle.relationships = dedup_rels

    bundle.stats = {
        "documents": len(docs),
        "documentsWithText": sum(1 for d in docs if d.text.strip()),
        "documentsExtracted": extracted_docs,
        "entities": len(bundle.entities),
        "relationships": len(bundle.relationships),
        "uniqueConcepts": len(entity_names),
        "predicateCounts": dict(rel_counter.most_common(30)),
        "source": "postgres+turbo-regex",
        "extractMethod": "turbo",
        "nerMethod": "none",
        "tripletMethod": "regulatory-patterns-only",
        "spacyModel": None,
        "textChars": text_chars,
        "batchSize": chunk_size,
        "nProcess": workers,
        "includeDepTriples": False,
        "llmProvider": None,
        "llmModel": None,
        "llmDocsUsed": 0,
        "llmAvailable": False,
    }
    print(f"  turbo done: entities={bundle.stats['entities']} rels={bundle.stats['relationships']}", flush=True)
    return bundle


def extract_with_semantica(
    docs: list[SourceDocument],
    *,
    corpus: str,
    method: str = "serious",
    text_chars: int = 3000,
    llm_doc_budget: int = 80,
    spacy_model: str = "en_core_web_sm",
    batch_size: int = 64,
    n_process: int = 4,
    include_dep_triples: bool = False,
    prior_bundle: ExtractionBundle | None = None,
    checkpoint_every: int = 250,
) -> ExtractionBundle:
    """Run serious Semantica extraction over source document text (fast spaCy path)."""
    bundle = ExtractionBundle(corpus=corpus, documents=docs)
    provider, llm_model = detect_llm_provider()
    use_llm = method in {"serious", "llm"} and provider is not None

    # Skip Semantica TripletExtractor/RelationExtractor (too slow).
    # Default: spaCy NER-only + regulatory patterns; optional dep triples need parser.
    use_spacy = method != "pattern"
    nlp = None
    ner = None
    workers = 1
    if use_spacy:
        import spacy

        try:
            nlp = spacy.load(spacy_model)
        except OSError:
            nlp = spacy.load("en_core_web_sm")
            spacy_model = "en_core_web_sm"
        disable = ["lemmatizer", "textcat"]
        if not include_dep_triples:
            disable.extend(["parser", "attribute_ruler", "tagger"])
        for pipe in disable:
            if pipe in nlp.pipe_names:
                nlp.disable_pipe(pipe)
        workers = max(1, min(n_process, os.cpu_count() or 1))
        ner_method = "ml-spacy-ner-batch"
        triplet_method = "spacy-dep" if include_dep_triples else "regulatory-patterns-only"
    else:
        ner = NERExtractor(method="pattern")
        ner_method = "pattern"
        triplet_method = "none"

    llm_triplets = None
    if use_llm:
        llm_triplets = TripletExtractor(
            method="llm",
            provider=provider,
            llm_model=llm_model,
        )
        triplet_method = f"{triplet_method}+llm:{provider}"

    entity_names: set[tuple[str, str]] = set()
    rel_counter: Counter[str] = Counter()
    extracted_docs = 0
    llm_docs_used = 0
    completed_ids: list[str] = []

    for doc in docs:
        hier = _slug(doc.hierarchy).title().replace("_", "") or "RegulatoryInstrument"
        _add_entity(
            bundle,
            etype=hier,
            name=doc.doc_id,
            label=doc.title[:200],
            properties={
                "hierarchy": doc.hierarchy,
                "status": doc.status,
                "officialId": doc.official_id,
                "sourceUrl": doc.source_url,
                "pdfUrl": doc.pdf_url,
                "issuedAt": doc.issued_at,
                "charCount": doc.char_count,
                "pageCount": doc.page_count,
                "hasPdf": pdf_path_for(corpus, doc.doc_id).is_file(),
            },
            entity_names=entity_names,
        )
        _add_entity(
            bundle,
            etype="InstrumentHierarchy",
            name=f"hierarchy:{doc.hierarchy}",
            label=doc.hierarchy,
            properties={},
            entity_names=entity_names,
        )
        bundle.relationships.append(
            {"type": "inHierarchy", "source": doc.doc_id, "target": f"hierarchy:{doc.hierarchy}"}
        )

    work: list[tuple[SourceDocument, str]] = []
    for doc in docs:
        text_body = (doc.text or "").strip()
        if not text_body:
            continue
        work.append((doc, text_body[:text_chars]))

    def _consume_entities(doc: SourceDocument, ents: list[Any]) -> None:
        for ent in ents[:60]:
            name, etype = _entity_label(ent)
            if len(name) < 2 or len(name) > 120:
                continue
            mapped = _map_ner_class(etype)
            concept = f"concept:{_slug(name)}"
            _add_entity(
                bundle,
                etype=mapped,
                name=concept,
                label=name,
                properties={"nerLabel": etype, "sourceDoc": doc.doc_id},
                entity_names=entity_names,
            )
            bundle.relationships.append(
                {"type": "mentions", "source": doc.doc_id, "target": concept}
            )
            rel_counter["mentions"] += 1

    def _consume_trips(doc: SourceDocument, trips: list[tuple[str, str, str]]) -> None:
        for subj, pred, obj in trips[:40]:
            if not subj or not obj or len(subj) > 120 or len(obj) > 120:
                continue
            rel_counter[pred] += 1
            for node_name in (subj, obj):
                _add_entity(
                    bundle,
                    etype="Entity",
                    name=f"concept:{_slug(node_name)}",
                    label=node_name,
                    properties={"sourceDoc": doc.doc_id},
                    entity_names=entity_names,
                )
            bundle.relationships.append(
                {
                    "type": _slug(pred) or "related_to",
                    "source": f"concept:{_slug(subj)}",
                    "target": f"concept:{_slug(obj)}",
                }
            )
            bundle.relationships.append(
                {
                    "type": "evidences",
                    "source": doc.doc_id,
                    "target": f"concept:{_slug(subj)}",
                }
            )

    if nlp is not None:
        texts = [excerpt for _, excerpt in work]
        pipe_iter = nlp.pipe(texts, batch_size=batch_size, n_process=workers)
        for i, ((doc, excerpt), spacy_doc) in enumerate(zip(work, pipe_iter), start=1):
            ents = list(spacy_doc.ents)
            _consume_entities(doc, ents)
            _extract_regulatory_patterns(
                bundle,
                doc=doc,
                excerpt=excerpt,
                entity_names=entity_names,
                rel_counter=rel_counter,
            )
            if include_dep_triples:
                _consume_trips(doc, _fast_dep_triplets(spacy_doc))

            if use_llm and llm_triplets is not None and llm_docs_used < llm_doc_budget:
                llm_docs_used += 1
                try:
                    llm_trips = llm_triplets.extract(excerpt[:3000], entities=ents[:30] or None)
                except Exception:
                    llm_trips = []
                parsed: list[tuple[str, str, str]] = []
                for trip in llm_trips or []:
                    parsed.append(
                        (
                            str(getattr(trip, "subject", "") or "").strip(),
                            str(getattr(trip, "predicate", "") or "related_to").strip(),
                            str(getattr(trip, "object", "") or "").strip(),
                        )
                    )
                _consume_trips(doc, parsed)

            extracted_docs += 1
            completed_ids.append(doc.doc_id)
            if i % 250 == 0 or i == len(work):
                print(f"  extracted {i}/{len(work)} documents...", flush=True)
            if checkpoint_every and (i % checkpoint_every == 0 or i == len(work)):
                # Snapshot partial stats for checkpoint payload.
                bundle.stats = {
                    "documents": len(docs),
                    "documentsWithText": len(work),
                    "documentsExtracted": extracted_docs,
                    "entities": len(bundle.entities),
                    "relationships": len(bundle.relationships),
                    "extractMethod": method,
                    "nerMethod": ner_method,
                    "tripletMethod": triplet_method,
                    "nProcess": workers,
                }
                ck = save_extract_checkpoint(
                    corpus,
                    bundle,
                    prior=prior_bundle,
                    completed_ids=completed_ids,
                    note=f"partial {i}/{len(work)}",
                )
                print(f"  checkpoint saved ({i}/{len(work)}): {ck}", flush=True)
    else:
        assert ner is not None
        for i, (doc, excerpt) in enumerate(work, start=1):
            try:
                ents = ner.extract(excerpt)
            except Exception:
                ents = []
            if not isinstance(ents, list):
                ents = []
            _consume_entities(doc, ents)
            _extract_regulatory_patterns(
                bundle,
                doc=doc,
                excerpt=excerpt,
                entity_names=entity_names,
                rel_counter=rel_counter,
            )
            extracted_docs += 1
            completed_ids.append(doc.doc_id)
            if i % 250 == 0 or i == len(work):
                print(f"  extracted {i}/{len(work)} documents...", flush=True)
            if checkpoint_every and (i % checkpoint_every == 0 or i == len(work)):
                bundle.stats = {
                    "documents": len(docs),
                    "documentsWithText": len(work),
                    "documentsExtracted": extracted_docs,
                    "entities": len(bundle.entities),
                    "relationships": len(bundle.relationships),
                    "extractMethod": method,
                    "nerMethod": ner_method,
                    "tripletMethod": triplet_method,
                    "nProcess": 1,
                }
                ck = save_extract_checkpoint(
                    corpus,
                    bundle,
                    prior=prior_bundle,
                    completed_ids=completed_ids,
                    note=f"partial {i}/{len(work)}",
                )
                print(f"  checkpoint saved ({i}/{len(work)}): {ck}", flush=True)

    seen: set[tuple[str, str, str]] = set()
    dedup_rels = []
    for rel in bundle.relationships:
        key = (str(rel["type"]), str(rel["source"]), str(rel["target"]))
        if key in seen:
            continue
        seen.add(key)
        dedup_rels.append(rel)
    bundle.relationships = dedup_rels

    seen_e: set[tuple[str, str]] = set()
    dedup_e = []
    for ent in bundle.entities:
        key = (str(ent["type"]), str(ent["name"]))
        if key in seen_e:
            continue
        seen_e.add(key)
        dedup_e.append(ent)
    bundle.entities = dedup_e

    bundle.stats = {
        "documents": len(docs),
        "documentsWithText": sum(1 for d in docs if d.text.strip()),
        "documentsExtracted": extracted_docs,
        "entities": len(bundle.entities),
        "relationships": len(bundle.relationships),
        "uniqueConcepts": len(entity_names),
        "predicateCounts": dict(rel_counter.most_common(30)),
        "source": "postgres+semantica-extract",
        "extractMethod": method,
        "nerMethod": ner_method,
        "tripletMethod": triplet_method,
        "spacyModel": spacy_model if use_spacy else None,
        "textChars": text_chars,
        "batchSize": batch_size if use_spacy else None,
        "nProcess": workers if use_spacy else None,
        "includeDepTriples": include_dep_triples if use_spacy else False,
        "llmProvider": provider if use_llm else None,
        "llmModel": llm_model if use_llm else None,
        "llmDocsUsed": llm_docs_used,
        "llmAvailable": provider is not None,
    }
    return bundle



def _llm_refine_tbox(bundle: ExtractionBundle, ontology: dict[str, Any]) -> dict[str, Any]:
    provider, model = detect_llm_provider()
    if not provider:
        return ontology
    try:
        engine = OntologyEngine()
        # Prefer compact digest over raw dumps.
        class_names = [c.get("name") for c in (ontology.get("classes") or []) if c.get("name")]
        prop_names = [p.get("name") for p in (ontology.get("properties") or []) if p.get("name")]
        top_concepts = [
            e.get("label")
            for e in bundle.entities
            if str(e.get("type")) not in {"InstrumentHierarchy"} and e.get("label")
        ][:80]
        digest = (
            f"Regulatory corpus: {bundle.corpus}\n"
            f"Existing classes: {', '.join(map(str, class_names[:40]))}\n"
            f"Existing properties: {', '.join(map(str, prop_names[:40]))}\n"
            f"Key concepts: {', '.join(map(str, top_concepts))}\n"
            "Produce a concise Indian regulatory ontology suitable for compliance reasoning. "
            "Include Obligation, Definition, LegalReference, Regulator, and instrument hierarchies."
        )
        refined = engine.from_text(
            digest,
            provider=provider,
            model=model,
            name=f"{bundle.corpus.title().replace('_', '')}RegulatoryOntology",
            base_uri=f"https://ontology.metareasoning.ai/regulatory/{bundle.corpus}/",
        )
        if isinstance(refined, dict) and (refined.get("classes") or refined.get("properties")):
            refined.setdefault("metadata", {})
            refined["metadata"].update(ontology.get("metadata") or {})
            refined["metadata"]["tboxSource"] = f"llm:{provider}"
            return refined
    except Exception as exc:
        print(f"  LLM TBox refine skipped: {exc}", flush=True)
    return ontology


def generate_semantica_ontology(bundle: ExtractionBundle, *, refine_llm: bool = True) -> dict[str, Any]:
    base_uri = f"https://ontology.metareasoning.ai/regulatory/{bundle.corpus}/"
    generator = OntologyGenerator(base_uri=base_uri)
    type_counts: dict[str, int] = defaultdict(int)
    tbox_entities = []
    # Keep TBox projection small even on full corpora (speed + useful schema).
    per_type_cap = 40 if bundle.stats.get("extractMethod") == "turbo" else 120
    for ent in bundle.entities:
        typ = str(ent["type"])
        if typ in {"InstrumentHierarchy", "Obligation", "Definition", "LegalReference"} or type_counts[typ] < per_type_cap:
            tbox_entities.append(ent)
            type_counts[typ] += 1
    rel_counts: dict[str, int] = defaultdict(int)
    tbox_rels = []
    rel_cap = 60 if bundle.stats.get("extractMethod") == "turbo" else 150
    for rel in bundle.relationships:
        rtype = str(rel["type"])
        if rel_counts[rtype] < rel_cap:
            tbox_rels.append(rel)
            rel_counts[rtype] += 1

    ontology = generator.generate_ontology(
        {"entities": tbox_entities, "relationships": tbox_rels},
        name=f"{bundle.corpus.title().replace('_', '')}RegulatoryOntology",
        build_hierarchy=True,
    )
    ontology.setdefault("metadata", {})
    ontology["metadata"].update(
        {
            "corpus": bundle.corpus,
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "source": "semantica-extract-from-regulatory-files",
            "corpusStats": bundle.stats,
            "tboxSource": "OntologyGenerator",
        }
    )
    if refine_llm:
        ontology = _llm_refine_tbox(bundle, ontology)
    return ontology


def materialize_graph(bundle: ExtractionBundle, ontology: dict[str, Any]) -> Graph:
    g = Graph()
    g.bind("reg", REG_NS)
    g.bind("core", CORE_NS)
    base = Namespace(f"https://ontology.metareasoning.ai/regulatory/{bundle.corpus}/")
    g.bind(bundle.corpus[:8], base)

    for cls in ontology.get("classes") or []:
        name = str(cls.get("name") or "")
        if not name:
            continue
        cls_uri = URIRef(_iri(str(base), "class", _slug(name)))
        g.add((cls_uri, RDF.type, OWL.Class))
        g.add((cls_uri, RDFS.label, Literal(cls.get("label") or name)))
        parent = cls.get("parent") or cls.get("subClassOf")
        if parent and parent != name:
            g.add((cls_uri, RDFS.subClassOf, URIRef(_iri(str(base), "class", _slug(str(parent))))))
        else:
            g.add((cls_uri, RDFS.subClassOf, CORE_NS.Concept))

    for prop in ontology.get("properties") or []:
        name = str(prop.get("name") or "")
        if not name:
            continue
        prop_uri = URIRef(_iri(str(base), "property", _slug(name)))
        g.add(
            (
                prop_uri,
                RDF.type,
                OWL.ObjectProperty if prop.get("type") == "object" else OWL.DatatypeProperty,
            )
        )
        g.add((prop_uri, RDFS.label, Literal(prop.get("label") or name)))

    type_index = {str(e["name"]): str(e["type"]) for e in bundle.entities}
    for ent in bundle.entities:
        name = str(ent["name"])
        typ = str(ent["type"])
        uri = URIRef(_iri(str(base), "instance", _slug(typ), _slug(name, max_len=160)))
        g.add((uri, RDF.type, URIRef(_iri(str(base), "class", _slug(typ)))))
        g.add((uri, RDF.type, CORE_NS.Entity))
        g.add((uri, RDFS.label, Literal(ent.get("label") or name)))
        for key, value in (ent.get("properties") or {}).items():
            if value is None or value == "" or isinstance(value, (dict, list)):
                continue
            g.add((uri, URIRef(_iri(str(base), "property", _slug(str(key)))), Literal(value)))

    for rel in bundle.relationships:
        src, tgt, rtype = str(rel["source"]), str(rel["target"]), str(rel["type"])
        src_uri = URIRef(
            _iri(str(base), "instance", _slug(type_index.get(src, "Entity")), _slug(src, max_len=160))
        )
        tgt_uri = URIRef(
            _iri(str(base), "instance", _slug(type_index.get(tgt, "Entity")), _slug(tgt, max_len=160))
        )
        g.add((src_uri, URIRef(_iri(str(base), "property", _slug(rtype))), tgt_uri))
    return g


def sync_graph_to_store(graph: Graph, store_path: Path, *, batch_size: int = 50_000) -> int:
    import shutil

    if store_path.exists():
        shutil.rmtree(store_path)
    store_path.mkdir(parents=True, exist_ok=True)
    store = TripletStore(backend="oxigraph", path=str(store_path))
    batch: list[Triplet] = []
    processed = 0
    for s, p, o in graph:
        batch.append(Triplet(subject=str(s), predicate=str(p), object=str(o)))
        if len(batch) >= batch_size:
            status = store.add_triplets(batch)
            processed += int(status.get("processed", len(batch)))
            batch.clear()
    if batch:
        status = store.add_triplets(batch)
        processed += int(status.get("processed", len(batch)))
    return processed


def export_outputs(
    corpus: str,
    ontology: dict[str, Any],
    graph: Graph,
    stats: dict[str, Any],
    bundle: ExtractionBundle | None = None,
) -> dict[str, Path]:
    out_dir = REPO_ROOT / "build" / "ontology" / "regulatory" / corpus
    out_dir.mkdir(parents=True, exist_ok=True)
    ttl_path = out_dir / "ontology.ttl"
    json_path = out_dir / "semantica-ontology.json"
    stats_path = out_dir / "stats.json"
    extract_path = out_dir / "extract-graph.json"
    graph.serialize(destination=str(ttl_path), format="turtle")
    json_path.write_text(json.dumps(ontology, indent=2, default=str), encoding="utf-8")
    stats_path.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    if bundle is not None:
        extract_path.write_text(
            json.dumps(
                {
                    "corpus": corpus,
                    "entities": bundle.entities,
                    "relationships": bundle.relationships,
                    "stats": bundle.stats,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    module_dir = REPO_ROOT / "ontology" / "regulatory"
    module_dir.mkdir(parents=True, exist_ok=True)
    module_ttl = module_dir / f"{corpus}.ttl"
    OntologyEngine().export_owl(ontology, str(module_ttl), format="turtle")
    paths = {"ttl": ttl_path, "module_ttl": module_ttl, "json": json_path, "stats": stats_path}
    if bundle is not None:
        paths["extract"] = extract_path
    return paths


def load_existing_extract(corpus: str) -> ExtractionBundle | None:
    path = REPO_ROOT / "build" / "ontology" / "regulatory" / corpus / "extract-graph.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    bundle = ExtractionBundle(corpus=corpus)
    bundle.entities = list(payload.get("entities") or [])
    bundle.relationships = list(payload.get("relationships") or [])
    bundle.stats = dict(payload.get("stats") or {})
    return bundle


def instrument_ids_from_bundle(bundle: ExtractionBundle) -> set[str]:
    ids: set[str] = set()
    for ent in bundle.entities:
        name = str(ent.get("name") or "")
        if name.startswith(("concept:", "hierarchy:", "obligation:", "definition:", "ref:")):
            continue
        props = ent.get("properties") or {}
        if any(k in props for k in ("hierarchy", "officialId", "charCount", "hasPdf", "status")):
            ids.add(name)
    return ids


def merge_extraction_bundles(base: ExtractionBundle, extra: ExtractionBundle) -> ExtractionBundle:
    out = ExtractionBundle(corpus=base.corpus, documents=list(base.documents) + list(extra.documents))
    seen_e: set[tuple[str, str]] = set()
    for ent in list(base.entities) + list(extra.entities):
        key = (str(ent.get("type")), str(ent.get("name")))
        if key in seen_e:
            continue
        seen_e.add(key)
        out.entities.append(ent)
    seen_r: set[tuple[str, str, str]] = set()
    for rel in list(base.relationships) + list(extra.relationships):
        key = (str(rel.get("type")), str(rel.get("source")), str(rel.get("target")))
        if key in seen_r:
            continue
        seen_r.add(key)
        out.relationships.append(rel)
    rel_counter: Counter[str] = Counter()
    for rel in out.relationships:
        rel_counter[str(rel.get("type") or "related_to")] += 1
    out.stats = {
        **(base.stats or {}),
        **(extra.stats or {}),
        "documents": int(base.stats.get("documents") or 0) + int(extra.stats.get("documents") or 0),
        "documentsWithText": int(base.stats.get("documentsWithText") or 0)
        + int(extra.stats.get("documentsWithText") or 0),
        "documentsExtracted": int(base.stats.get("documentsExtracted") or 0)
        + int(extra.stats.get("documentsExtracted") or 0),
        "entities": len(out.entities),
        "relationships": len(out.relationships),
        "uniqueConcepts": len(out.entities),
        "predicateCounts": dict(rel_counter.most_common(30)),
        "resumedFrom": int(base.stats.get("documentsExtracted") or 0),
        "newlyExtracted": int(extra.stats.get("documentsExtracted") or 0),
    }
    return out


def save_extract_checkpoint(
    corpus: str,
    bundle: ExtractionBundle,
    *,
    prior: ExtractionBundle | None = None,
    completed_ids: list[str] | None = None,
    note: str = "",
) -> Path:
    """Atomically persist extract-graph so runs can resume without data loss."""
    out_dir = REPO_ROOT / "build" / "ontology" / "regulatory" / corpus
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "extract-graph.json"
    tmp = out_dir / "extract-graph.json.tmp"
    meta_path = out_dir / "checkpoint.json"
    to_save = merge_extraction_bundles(prior, bundle) if prior is not None else bundle
    # Union completed IDs from prior checkpoint + this session.
    prior_ids = set(load_completed_ids(corpus))
    session_ids = set(completed_ids or [])
    all_ids = sorted(prior_ids | session_ids | instrument_ids_from_bundle(to_save))
    # Prefer explicit completed_ids for resume correctness when provided.
    resume_ids = sorted(prior_ids | session_ids) if completed_ids is not None else all_ids
    to_save.stats = {
        **(to_save.stats or {}),
        "entities": len(to_save.entities),
        "relationships": len(to_save.relationships),
        "completedDocIds": resume_ids,
        "documentsExtracted": len(resume_ids),
        "checkpointNote": note,
        "checkpointAt": datetime.now(timezone.utc).isoformat(),
    }
    payload = {
        "corpus": corpus,
        "entities": to_save.entities,
        "relationships": to_save.relationships,
        "stats": to_save.stats,
    }
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    tmp.replace(path)
    meta = {
        "corpus": corpus,
        "completed": len(resume_ids),
        "entities": len(to_save.entities),
        "relationships": len(to_save.relationships),
        "note": note,
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    ledger = out_dir / "processed_ids.jsonl"
    ledger.write_text("\n".join(resume_ids) + ("\n" if resume_ids else ""), encoding="utf-8")
    return path


def load_completed_ids(corpus: str) -> set[str]:
    """IDs fully extracted (checkpoint ledger / extract stats), not merely structural."""
    out_dir = REPO_ROOT / "build" / "ontology" / "regulatory" / corpus
    ids: set[str] = set()
    ledger = out_dir / "processed_ids.jsonl"
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                ids.add(line)
    extract = out_dir / "extract-graph.json"
    if extract.is_file():
        try:
            payload = json.loads(extract.read_text(encoding="utf-8"))
            stats = payload.get("stats") or {}
            for x in stats.get("completedDocIds") or []:
                ids.add(str(x))
            # Backward-compat: infer completed docs from evidence edges, not all instruments.
            if not ids:
                for rel in payload.get("relationships") or []:
                    if str(rel.get("type")) in {"mentions", "imposes", "defines", "cites", "evidences"}:
                        src = str(rel.get("source") or "")
                        if src and not src.startswith(
                            ("concept:", "hierarchy:", "obligation:", "definition:", "ref:")
                        ):
                            ids.add(src)
        except Exception:
            pass
    return ids


def generate_from_sources(
    corpora: Iterable[str] | None = None,
    *,
    limit: int | None = None,
    method: str = "serious",
    sync_store: bool = True,
    full: bool = False,
    llm_doc_budget: int = 80,
    refine_llm: bool = True,
    reuse_existing: bool = True,
    resume: bool = False,
    n_process: int = 4,
    text_chars: int = 3000,
    spacy_model: str = "en_core_web_sm",
) -> dict[str, Any]:
    selected = list(corpora or CORPORA)
    provider, llm_model = detect_llm_provider()
    summary: dict[str, Any] = {
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "mode": "semantica-serious-from-source-files",
        "method": method,
        "llmAvailable": provider is not None,
        "llmProvider": provider,
        "llmModel": llm_model,
        "corpora": {},
    }
    if method in {"serious", "llm"} and provider is None:
        print(
            "NOTE: No ANTHROPIC_API_KEY / OPENAI_API_KEY in environment. "
            "Running serious ML path (spaCy) + regulatory patterns; "
            "LLM triplet/TBox refinement disabled.",
            flush=True,
        )

    merged = Graph()
    merged.bind("reg", REG_NS)
    merged.bind("core", CORE_NS)
    backbone = REPO_ROOT / "ontology" / "regulatory" / "namespace.ttl"
    if backbone.is_file():
        merged.parse(backbone, format="turtle")

    # Reuse previously generated corpora not in this run (e.g. only income_tax --full).
    if reuse_existing:
        prior_summary_path = REPO_ROOT / "build" / "ontology" / "regulatory" / "summary.json"
        prior = {}
        if prior_summary_path.is_file():
            try:
                prior = json.loads(prior_summary_path.read_text(encoding="utf-8")).get("corpora") or {}
            except Exception:
                prior = {}
        for corpus in CORPORA:
            if corpus in selected:
                continue
            ttl = REPO_ROOT / "build" / "ontology" / "regulatory" / corpus / "ontology.ttl"
            if not ttl.is_file():
                continue
            print(f"reusing existing graph: {corpus} ({ttl})", flush=True)
            merged.parse(ttl, format="turtle")
            if corpus in prior:
                summary["corpora"][corpus] = {**prior[corpus], "reused": True}

    for corpus in selected:
        print(f"\n=== Semantica serious: {corpus} ===", flush=True)
        corpus_limit = limit
        if corpus_limit is None and not full:
            corpus_limit = DEFAULT_DOC_LIMITS.get(corpus)
        docs = fetch_source_documents(corpus, limit=corpus_limit)
        print(
            f"loaded {len(docs)} instruments from Postgres"
            + (f" (limit={corpus_limit})" if corpus_limit else " (full)"),
            flush=True,
        )

        prior_bundle: ExtractionBundle | None = None
        if resume:
            prior_bundle = load_existing_extract(corpus)
            done_ids = load_completed_ids(corpus)
            if prior_bundle is not None or done_ids:
                before = len(docs)
                docs = [d for d in docs if d.doc_id not in done_ids]
                print(
                    f"resume: skipping {len(done_ids)} already extracted "
                    f"({before - len(docs)} overlapped); remaining {len(docs)}",
                    flush=True,
                )
            else:
                print("resume: no existing extract/checkpoint; processing all loaded docs", flush=True)

        if not docs and prior_bundle is not None:
            print("resume: nothing remaining; rebuilding outputs from existing extract", flush=True)
            bundle = prior_bundle
        else:
            bundle = (
                extract_turbo(
                    docs,
                    corpus=corpus,
                    text_chars=min(text_chars, 2000),
                    n_process=n_process,
                )
                if method == "turbo"
                else extract_with_semantica(
                    docs,
                    corpus=corpus,
                    method=method,
                    llm_doc_budget=llm_doc_budget,
                    n_process=n_process,
                    text_chars=text_chars,
                    spacy_model=spacy_model,
                    prior_bundle=prior_bundle,
                    checkpoint_every=250,
                )
            )
            if prior_bundle is not None:
                bundle = merge_extraction_bundles(prior_bundle, bundle)

        print(
            f"extract: entities={bundle.stats['entities']} "
            f"relationships={bundle.stats['relationships']} "
            f"ner={bundle.stats.get('nerMethod')} "
            f"triplets={bundle.stats.get('tripletMethod')} "
            f"nProcess={bundle.stats.get('nProcess')} "
            f"llmDocs={bundle.stats.get('llmDocsUsed')}",
            flush=True,
        )
        ontology = generate_semantica_ontology(bundle, refine_llm=refine_llm and provider is not None)
        graph = materialize_graph(bundle, ontology)
        paths = export_outputs(corpus, ontology, graph, bundle.stats, bundle=bundle)
        loaded = 0
        if sync_store:
            loaded = sync_graph_to_store(
                graph, REPO_ROOT / ".semantica" / "oxigraph-regulatory" / corpus
            )
        for triple in graph:
            merged.add(triple)
        summary["corpora"][corpus] = {
            **bundle.stats,
            "classes": len(ontology.get("classes") or []),
            "properties": len(ontology.get("properties") or []),
            "triples": len(graph),
            "tripletsLoaded": loaded,
            "docLimit": corpus_limit,
            "reused": False,
            "resumed": bool(resume and prior_bundle is not None),
            "paths": {k: str(v) for k, v in paths.items()},
        }
        print(
            f"{corpus}: classes={summary['corpora'][corpus]['classes']} "
            f"triples={summary['corpora'][corpus]['triples']}",
            flush=True,
        )

    merged_path = REPO_ROOT / "build" / "ontology" / "regulatory" / "complete.ttl"
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    merged.serialize(destination=str(merged_path), format="turtle")
    if sync_store:
        sync_graph_to_store(merged, REPO_ROOT / ".semantica" / "oxigraph-regulatory" / "complete")
    summary["mergedTriples"] = len(merged)
    summary["mergedTtl"] = str(merged_path)
    summary_path = REPO_ROOT / "build" / "ontology" / "regulatory" / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
