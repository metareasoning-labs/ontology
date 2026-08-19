-- Regulatory corpus schema (mirrors multicatalyst-agents mc_regulatory_corpus_*).
-- Applied automatically by docker compose on first boot, or via:
--   psql "$DATABASE_URL" -f corpus/regulatory/schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS mc_regulatory_corpus_documents (
    id UUID PRIMARY KEY,
    corpus VARCHAR(64) NOT NULL,
    doc_id VARCHAR(256) NOT NULL,
    title TEXT NOT NULL,
    hierarchy VARCHAR(64) NOT NULL,
    official_id VARCHAR(512),
    source_url TEXT,
    pdf_url TEXT,
    issued_at VARCHAR(64),
    status VARCHAR(64) NOT NULL DEFAULT 'in_force',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    pdf_sha256 VARCHAR(64),
    ingested_at TIMESTAMPTZ,
    text_extracted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_regulatory_corpus_documents_corpus_doc UNIQUE (corpus, doc_id)
);

CREATE INDEX IF NOT EXISTS ix_mc_regulatory_corpus_documents_corpus
    ON mc_regulatory_corpus_documents (corpus);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_corpus_documents_hierarchy
    ON mc_regulatory_corpus_documents (corpus, hierarchy);

CREATE TABLE IF NOT EXISTS mc_regulatory_corpus_blobs (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES mc_regulatory_corpus_documents (id) ON DELETE CASCADE,
    blob_kind VARCHAR(32) NOT NULL DEFAULT 'source_pdf',
    storage_key TEXT NOT NULL,
    content_type VARCHAR(128) NOT NULL DEFAULT 'application/pdf',
    byte_size BIGINT NOT NULL DEFAULT 0,
    sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_regulatory_corpus_blobs_doc_kind UNIQUE (document_id, blob_kind)
);

CREATE TABLE IF NOT EXISTS mc_regulatory_corpus_text (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL UNIQUE REFERENCES mc_regulatory_corpus_documents (id) ON DELETE CASCADE,
    text TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    extract_method VARCHAR(32) NOT NULL DEFAULT 'pypdf',
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_mc_regulatory_corpus_text_document_id
    ON mc_regulatory_corpus_text (document_id);

CREATE TABLE IF NOT EXISTS mc_regulatory_corpus_relationships (
    id UUID PRIMARY KEY,
    corpus VARCHAR(64) NOT NULL,
    source_document_id UUID NOT NULL REFERENCES mc_regulatory_corpus_documents (id) ON DELETE CASCADE,
    source_doc_id VARCHAR(256) NOT NULL,
    target_doc_id VARCHAR(256) NOT NULL,
    rel_type VARCHAR(64) NOT NULL,
    evidence TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    source_kind VARCHAR(32) NOT NULL DEFAULT 'text',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_regulatory_corpus_relationships_edge
        UNIQUE (corpus, source_doc_id, target_doc_id, rel_type)
);

CREATE INDEX IF NOT EXISTS ix_mc_regulatory_corpus_relationships_corpus
    ON mc_regulatory_corpus_relationships (corpus);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_corpus_relationships_source
    ON mc_regulatory_corpus_relationships (corpus, source_doc_id);
CREATE INDEX IF NOT EXISTS ix_mc_regulatory_corpus_relationships_target
    ON mc_regulatory_corpus_relationships (corpus, target_doc_id);
