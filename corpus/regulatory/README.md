# Regulatory corpus

This folder holds **source regulatory material** and Semantica outputs derived from it.

## Source of truth

| Path | Contents |
|------|----------|
| `files/{sebi,rbi,gst,insurance,income_tax}/documents/<id>/source.pdf` | Actual regulator PDFs |
| Postgres `mc_regulatory_corpus_*` | Document metadata + extracted text |
| `schema.sql` | Postgres DDL |

Configure DB via `.env` (`DATABASE_URL`). Bootstrap:

```bash
./scripts/bootstrap_postgres.sh --sync-from-multicatalyst
```

## Generate ontology with Semantica (from sources)

Semantica is **not** only a viewer. Serious pipeline:

1. Read instrument text from Postgres (backed by the PDFs above)
2. spaCy ML NER (`en_core_web_md`) + regulatory obligation/definition/citation patterns
3. Optional LLM triplets + TBox refine if `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set
4. Semantica `OntologyGenerator` → OWL classes/properties
5. Export Turtle + Oxigraph

```bash
# one-time ML/LLM deps
pip install -e ".[regulatory]"
python -m spacy download en_core_web_md
python -m spacy download en_core_web_sm

# serious generation (default). Income Tax capped at 3k richest docs unless --full.
python scripts/generate_regulatory_ontology.py

# pilot
python scripts/generate_regulatory_ontology.py --corpus gst --limit 50

# enable LLM upgrade (add key to .env first)
# ANTHROPIC_API_KEY=... SEMANTICA_LLM_PROVIDER=anthropic
python scripts/generate_regulatory_ontology.py --corpus gst --llm-docs 100
```

Outputs:

- `ontology/regulatory/{corpus}.ttl` — Semantica TBox modules
- `build/ontology/regulatory/{corpus}/ontology.ttl` — instance graph
- `build/ontology/regulatory/complete.ttl` — merged graph
- `.semantica/oxigraph-regulatory/` — queryable store

Explorer (view/query layer on top of that graph):

```bash
python scripts/export_explorer_graph.py   # only after generation
semantica explorer start --graph build/ontology/regulatory/explorer-graph.json
```

## Not kept here

Pre-built multicatalyst `ontology.json` / `vocabulary.json` / `grammar.json` /
`catalog.json` packages are **not** source regulatory files and are not used.
