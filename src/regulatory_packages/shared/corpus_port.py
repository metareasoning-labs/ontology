"""Sync Postgres access for regulatory corpus (no multicatalyst db/storage)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import psycopg


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    title: str
    hierarchy: str
    official_id: str | None
    source_url: str | None
    pdf_url: str | None
    issued_at: str | None
    status: str
    metadata: dict[str, Any]
    text: str


def database_url() -> str:
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("REGULATORY_CORPUS_DATABASE_URL")
        or ""
    ).strip()
    if not url:
        raise RuntimeError("DATABASE_URL (or REGULATORY_CORPUS_DATABASE_URL) must be set")
    # Accept async URLs from sibling projects.
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    url = url.replace("@postgres:", "@127.0.0.1:")
    return url


def _connect() -> psycopg.Connection:
    return psycopg.connect(database_url())


def corpus_stats(corpus: str) -> dict[str, int]:
    with _connect() as conn:
        docs = conn.execute(
            "SELECT COUNT(*) FROM mc_regulatory_corpus_documents WHERE corpus = %s",
            (corpus,),
        ).fetchone()[0]
        texts = conn.execute(
            """
            SELECT COUNT(*)
            FROM mc_regulatory_corpus_text t
            JOIN mc_regulatory_corpus_documents d ON d.id = t.document_id
            WHERE d.corpus = %s AND length(t.text) > 0
            """,
            (corpus,),
        ).fetchone()[0]
        pdfs = conn.execute(
            """
            SELECT COUNT(*)
            FROM mc_regulatory_corpus_blobs b
            JOIN mc_regulatory_corpus_documents d ON d.id = b.document_id
            WHERE d.corpus = %s
            """,
            (corpus,),
        ).fetchone()[0]
    return {"documents": int(docs), "textExtracted": int(texts), "pdfsStored": int(pdfs)}


def fetch_text_map(corpus: str) -> dict[str, str]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT d.doc_id, t.text
            FROM mc_regulatory_corpus_documents d
            JOIN mc_regulatory_corpus_text t ON t.document_id = d.id
            WHERE d.corpus = %s AND length(t.text) > 0
            """,
            (corpus,),
        ).fetchall()
    return {doc_id: text or "" for doc_id, text in rows}


def fetch_documents(corpus: str, *, limit: int | None = None) -> list[CorpusDocument]:
    sql = """
        SELECT
            d.doc_id, d.title, d.hierarchy, d.official_id, d.source_url, d.pdf_url,
            d.issued_at, d.status, d.metadata_json, COALESCE(t.text, '')
        FROM mc_regulatory_corpus_documents d
        LEFT JOIN mc_regulatory_corpus_text t ON t.document_id = d.id
        WHERE d.corpus = %s
        ORDER BY length(COALESCE(t.text, '')) DESC, d.doc_id
    """
    params: list[Any] = [corpus]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    out: list[CorpusDocument] = []
    with _connect() as conn:
        for row in conn.execute(sql, params).fetchall():
            meta = row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}")
            out.append(
                CorpusDocument(
                    doc_id=row[0],
                    title=row[1],
                    hierarchy=row[2],
                    official_id=row[3],
                    source_url=row[4],
                    pdf_url=row[5],
                    issued_at=row[6],
                    status=row[7] or "in_force",
                    metadata=meta,
                    text=row[9] or "",
                )
            )
    return out


def catalog_from_postgres(corpus: str) -> dict[str, Any]:
    """Synthesize a minimal multicatalyst-style catalog when none is on disk."""
    docs = fetch_documents(corpus)
    documents = []
    for d in docs:
        entry: dict[str, Any] = {
            "id": d.doc_id,
            "title": d.title,
            "hierarchy": d.hierarchy,
            "status": d.status,
        }
        if d.official_id:
            entry["officialId"] = d.official_id
        if d.source_url:
            entry["sourceUrl"] = d.source_url
        if d.pdf_url:
            entry["pdfUrl"] = d.pdf_url
        if d.issued_at:
            entry["issuedAt"] = d.issued_at
        # Carry through known metadata fields used by builders.
        for key in ("entities", "topics", "summary", "section", "nicknames"):
            if key in d.metadata:
                entry[key] = d.metadata[key]
        documents.append(entry)
    return {
        "version": 1,
        "corpus": corpus,
        "source": "postgres",
        "documents": documents,
        "stats": corpus_stats(corpus),
    }


def merge_catalog_pdf_urls(catalog: dict[str, Any], corpus: str) -> dict[str, Any]:
    """Refresh pdfUrl/sourceUrl from Postgres onto an existing catalog."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, pdf_url, source_url
            FROM mc_regulatory_corpus_documents
            WHERE corpus = %s
            """,
            (corpus,),
        ).fetchall()
    by_id = {doc_id: {"pdfUrl": pdf, "sourceUrl": src} for doc_id, pdf, src in rows}
    for doc in catalog.get("documents") or []:
        meta = by_id.get(doc.get("id") or "")
        if not meta:
            continue
        if meta.get("pdfUrl"):
            doc["pdfUrl"] = meta["pdfUrl"]
        if meta.get("sourceUrl") and not doc.get("sourceUrl"):
            doc["sourceUrl"] = meta["sourceUrl"]
    return catalog
