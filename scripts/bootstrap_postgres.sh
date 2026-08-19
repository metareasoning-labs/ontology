#!/usr/bin/env bash
# Apply regulatory corpus schema and optionally sync rows from multicatalyst Postgres.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

: "${DATABASE_URL:=postgresql://ontology:ontology_dev_password@127.0.0.1:5432/ontology}"

# libpq URL (strip SQLAlchemy async driver prefix if present)
PGURL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
PGURL="${PGURL/postgresql+psycopg:\/\//postgresql:\/\/}"

echo "Using DATABASE_URL → ${PGURL%%@*}@***"

psql "$PGURL" -v ON_ERROR_STOP=1 -f "$ROOT/corpus/regulatory/schema.sql"

if [[ "${1:-}" == "--sync-from-multicatalyst" ]]; then
  SRC_URL="${MULTICATALYST_DATABASE_URL:-postgresql://mc:mc_dev_password@127.0.0.1:5432/multicatalyst}"
  DUMP="$(mktemp -t ontology_regulatory_XXXXXX.dump)"
  echo "Dumping regulatory tables from multicatalyst…"
  pg_dump "$SRC_URL" --format=custom --no-owner --no-acl \
    -t mc_regulatory_corpus_documents \
    -t mc_regulatory_corpus_blobs \
    -t mc_regulatory_corpus_text \
    -t mc_regulatory_corpus_relationships \
    -f "$DUMP"
  echo "Restoring into ontology DB…"
  psql "$PGURL" -v ON_ERROR_STOP=1 <<'SQL'
DROP TABLE IF EXISTS mc_regulatory_corpus_relationships CASCADE;
DROP TABLE IF EXISTS mc_regulatory_corpus_text CASCADE;
DROP TABLE IF EXISTS mc_regulatory_corpus_blobs CASCADE;
DROP TABLE IF EXISTS mc_regulatory_corpus_documents CASCADE;
SQL
  pg_restore --dbname="$PGURL" --no-owner --no-acl "$DUMP"
  rm -f "$DUMP"
fi

echo "Corpus counts:"
psql "$PGURL" -c "
SELECT corpus, COUNT(*) AS docs
FROM mc_regulatory_corpus_documents
GROUP BY corpus
ORDER BY 1;
"
