"""Build Postgres FTS + vocab posting indexes from packages + corpus text."""

from __future__ import annotations

import re
from typing import Any

from regulatory_packages.shared.corpus_port import _connect
from regulatory_packages.shared.paths import package_dir
from regulatory_packages.shared.store_factory import make_store

_SEARCH_DDL = """
CREATE TABLE IF NOT EXISTS mc_regulatory_doc_fts (
    document_id UUID PRIMARY KEY
        REFERENCES mc_regulatory_corpus_documents (id) ON DELETE CASCADE,
    corpus VARCHAR(64) NOT NULL,
    doc_id VARCHAR(256) NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    tsv tsvector NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_regulatory_doc_fts_corpus_doc UNIQUE (corpus, doc_id)
);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_doc_fts_corpus
    ON mc_regulatory_doc_fts (corpus);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_doc_fts_tsv
    ON mc_regulatory_doc_fts USING GIN (tsv);

CREATE TABLE IF NOT EXISTS mc_regulatory_vocab_postings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    code VARCHAR(512) NOT NULL,
    doc_id VARCHAR(256) NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    CONSTRAINT uq_regulatory_vocab_postings UNIQUE (corpus, kind, code, doc_id)
);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_vocab_postings_lookup
    ON mc_regulatory_vocab_postings (corpus, kind, code);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_vocab_postings_doc
    ON mc_regulatory_vocab_postings (corpus, doc_id);
"""


def ensure_search_schema() -> None:
    with _connect() as conn:
        conn.execute(_SEARCH_DDL)
        conn.commit()


def _load_package(corpus: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    store = make_store(corpus)
    base = package_dir(corpus)
    catalog = store.load_catalog(base) or {"documents": []}
    vocab = store.load_vocabulary(base) or {}
    ontology = store.load_ontology(base) or {}
    return catalog, vocab, ontology


def _alias_map(vocab: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """token/phrase lower → [(kind, code), ...]"""
    out: dict[str, list[tuple[str, str]]] = {}

    def add(phrase: str, kind: str, code: str) -> None:
        key = phrase.strip().lower()
        if len(key) < 2:
            return
        out.setdefault(key, []).append((kind, code))

    for ent in vocab.get("entities") or []:
        if isinstance(ent, str):
            add(ent, "entity", ent)
            continue
        code = str(ent.get("code") or ent.get("id") or ent.get("label") or "")
        if not code:
            continue
        add(code, "entity", code)
        if ent.get("label"):
            add(str(ent["label"]), "entity", code)
        for alias in ent.get("aliases") or []:
            add(str(alias), "entity", code)

    for topic in vocab.get("topics") or []:
        if isinstance(topic, str):
            add(topic, "topic", topic)
            continue
        code = str(topic.get("id") or topic.get("code") or topic.get("label") or "")
        if not code:
            continue
        add(code, "topic", code)
        if topic.get("label"):
            add(str(topic["label"]), "topic", code)
        for kw in topic.get("keywords") or []:
            add(str(kw), "topic", code)

    return out


def _doc_entity_topic_codes(doc: dict[str, Any], alias_map: dict[str, list[tuple[str, str]]]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for field in ("entities", "topics"):
        for item in doc.get(field) or []:
            if isinstance(item, str):
                key = item.lower()
                for pair in alias_map.get(key, [("entity" if field == "entities" else "topic", item)]):
                    found.add(pair)
            elif isinstance(item, dict):
                code = str(item.get("code") or item.get("id") or item.get("label") or "")
                if code:
                    found.add(("entity" if field == "entities" else "topic", code))
    return found


def _section_refs_from_doc(doc: dict[str, Any], analysis: dict[str, Any] | None) -> set[str]:
    refs: set[str] = set()
    for key in ("sectionRefs", "sections", "section"):
        val = doc.get(key)
        if isinstance(val, str) and val.strip():
            refs.add(val.strip())
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    refs.add(item.strip())
                elif isinstance(item, dict) and item.get("ref"):
                    refs.add(str(item["ref"]).strip())
    if analysis:
        for item in analysis.get("sectionRefs") or analysis.get("citations") or []:
            if isinstance(item, str):
                refs.add(item.strip())
            elif isinstance(item, dict):
                ref = item.get("ref") or item.get("citation") or item.get("text")
                if ref:
                    refs.add(str(ref).strip())
    return {r for r in refs if r}


def build_indexes(corpus: str) -> dict[str, Any]:
    ensure_search_schema()
    catalog, vocab, ontology = _load_package(corpus)
    alias_map = _alias_map(vocab)
    analyses = ((ontology.get("llm") or {}).get("documentAnalyses")) or ontology.get("documentAnalyses") or {}

    with _connect() as conn:
        conn.execute("DELETE FROM mc_regulatory_doc_fts WHERE corpus = %s", (corpus,))
        conn.execute("DELETE FROM mc_regulatory_vocab_postings WHERE corpus = %s", (corpus,))

        # FTS from live corpus text joined to documents
        conn.execute(
            """
            INSERT INTO mc_regulatory_doc_fts (document_id, corpus, doc_id, title, tsv, updated_at)
            SELECT
                d.id,
                d.corpus,
                d.doc_id,
                d.title,
                setweight(to_tsvector('english', coalesce(d.title, '')), 'A')
                  || setweight(to_tsvector('english', coalesce(left(t.text, 200000), '')), 'B'),
                now()
            FROM mc_regulatory_corpus_documents d
            LEFT JOIN mc_regulatory_corpus_text t ON t.document_id = d.id
            WHERE d.corpus = %s
            ON CONFLICT (document_id) DO UPDATE SET
                title = EXCLUDED.title,
                tsv = EXCLUDED.tsv,
                updated_at = now()
            """,
            (corpus,),
        )

        posting_rows: list[tuple[str, str, str, str, float]] = []
        for doc in catalog.get("documents") or []:
            doc_id = str(doc.get("id") or "")
            if not doc_id:
                continue
            analysis = analyses.get(doc_id) if isinstance(analyses, dict) else None
            for kind, code in _doc_entity_topic_codes(doc, alias_map):
                posting_rows.append((corpus, kind, code, doc_id, 1.0))
            for ref in _section_refs_from_doc(doc, analysis if isinstance(analysis, dict) else None):
                posting_rows.append((corpus, "section_ref", ref, doc_id, 1.0))

        # Also index vocabulary codes mentioned in titles via alias scan (light).
        for doc in catalog.get("documents") or []:
            doc_id = str(doc.get("id") or "")
            title = str(doc.get("title") or "").lower()
            if not doc_id or not title:
                continue
            for phrase, pairs in alias_map.items():
                if len(phrase) >= 4 and phrase in title:
                    for kind, code in pairs:
                        posting_rows.append((corpus, kind, code, doc_id, 0.5))

        # Dedupe
        seen: set[tuple[str, str, str, str]] = set()
        unique_rows: list[tuple[str, str, str, str, float]] = []
        for row in posting_rows:
            key = row[:4]
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)

        if unique_rows:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO mc_regulatory_vocab_postings (corpus, kind, code, doc_id, weight)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (corpus, kind, code, doc_id) DO UPDATE SET weight = EXCLUDED.weight
                    """,
                    unique_rows,
                )
        conn.commit()

        fts_count = conn.execute(
            "SELECT COUNT(*) FROM mc_regulatory_doc_fts WHERE corpus = %s", (corpus,)
        ).fetchone()[0]
        post_count = conn.execute(
            "SELECT COUNT(*) FROM mc_regulatory_vocab_postings WHERE corpus = %s", (corpus,)
        ).fetchone()[0]

    return {
        "corpus": corpus,
        "ftsRows": int(fts_count),
        "postingRows": int(post_count),
        "aliasPhrases": len(alias_map),
    }
