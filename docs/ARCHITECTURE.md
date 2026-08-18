# Architecture

## Purpose

This repository holds **shared domain vocabulary** — not application code. Downstream repos (verification, agents, dashboards) import these IRIs to align terminology.

## Layers

1. **Ontology sources** (`ontology/`) — Turtle files, reviewed like schema migrations.
2. **Semantica bridge** (`src/ontology_lib/semantica_bridge.py`) — validates TTL, syncs to Oxigraph, exports merged graphs.
3. **Library** (`src/ontology_lib/`) — rdflib loaders plus Semantica-backed validation.
4. **Tests** — parse checks, class assertions, and Semantica bootstrap integration.

## Semantica stack

[Semantica](https://github.com/semantica-agi/semantica) provides:

- **OntologyValidator** — validate Turtle directories under `ontology/core/`
- **TripletStore (Oxigraph)** — local embedded RDF store at `.semantica/oxigraph`
- **Future hooks** — reasoning (`semantica.reasoning`), provenance (`semantica.provenance`), and Knowledge Explorer

Configuration lives in `config/semantica.yaml`. Run `scripts/bootstrap_semantica.py` after changing TTL sources.

## Extension guidelines

- Add classes under `ontology/core/` or new modules (e.g. `ontology/finance/`).
- Prefer reusing `:Entity` and `:Concept` branches before creating orphan roots.
- Re-run `./scripts/validate.sh` before opening a PR.
- Breaking IRI changes require a version bump in `namespace.ttl` and a migration note.
