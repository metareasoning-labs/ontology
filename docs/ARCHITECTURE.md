# Architecture

## Purpose

This repository holds **shared domain vocabulary** — not application code. Downstream repos (verification, agents, dashboards) import these IRIs to align terminology.

## Layers

1. **Ontology sources** (`ontology/`) — Turtle files, reviewed like schema migrations.
2. **Library** (`src/ontology_lib/`) — thin loaders and future validators (SHACL, OWL-RL).
3. **Tests** — parse checks and spot assertions on critical classes.

## Extension guidelines

- Add classes under `ontology/core/` or new modules (e.g. `ontology/finance/`).
- Prefer reusing `:Entity` and `:Concept` branches before creating orphan roots.
- Breaking IRI changes require a version bump in `namespace.ttl` and a migration note.
