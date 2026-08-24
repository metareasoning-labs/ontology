# Regulatory corpus

Source regulatory material, **agent packages** (vocab/grammar/ontology JSON), and optional Semantica OWL exports.

## Two layers

| Layer | Purpose | Hot path for agents? |
|-------|---------|----------------------|
| **Packages** (`packages/regulatory/{corpus}/`) | Multicatalyst-style `catalog` / `ontology` / `vocabulary` / `grammar` | **Yes** — navigate & search |
| **Semantica OWL** (`ontology/regulatory/*.ttl`, Oxigraph) | Formal TBox / SPARQL | No — optional formal export |

## Source of truth

| Path | Contents |
|------|----------|
| `files/{sebi,rbi,gst,insurance,income_tax}/documents/<id>/source.pdf` | Regulator PDFs |
| Postgres `mc_regulatory_corpus_*` | Document metadata + extracted text |
| `schema.sql` | Corpus + FTS/posting index DDL |

```bash
./scripts/bootstrap_postgres.sh --sync-from-multicatalyst
```

## Agent packages (ported from multicatalyst-agents)

Builders live in `src/regulatory_packages/` (no crawlers). Rebuild from Postgres:

```bash
pip install -e ".[regulatory-packages]"

# rebuild ontology + vocabulary + grammar JSON
python scripts/rebuild_regulatory_packages.py --corpus gst
# or: --corpus all

# build Postgres FTS + vocab posting indexes
python scripts/build_regulatory_search_indexes.py --corpus gst

# search (vocab normalize → grammar route → FTS + postings → RRF)
python scripts/search_regulatory.py --corpus gst "input tax credit registration"

# optional search API
pip install -e ".[regulatory-packages-api]"
python scripts/run_regulatory_search_api.py   # http://127.0.0.1:8091/search
```

Outputs under `packages/regulatory/{corpus}/`:

- `catalog.json`, `ontology.json`, `taxonomy.json`, `vocabulary.json`, `grammar.json`

Search indexes (Postgres):

- `mc_regulatory_doc_fts` — title + text `tsvector`
- `mc_regulatory_vocab_postings` — entity / topic / section_ref → doc_id

## Semantica OWL (optional formal path)

```bash
pip install -e ".[regulatory]"
python -m spacy download en_core_web_md
python scripts/generate_regulatory_ontology.py --corpus gst --limit 50
```

Explorer (OWL graph UI, not agent search):

```bash
export SEMANTICA_ALLOW_ANONYMOUS=true
python scripts/bootstrap_explorer.py --corpus gst
```

## Upgrade path

At multi-million-doc scale, move document recall to OpenSearch while keeping vocab/grammar posting lists and Postgres (or Neo4j) for bounded relationship hops. Semantica/Oxigraph remains optional for SPARQL.
