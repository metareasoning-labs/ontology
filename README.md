# Ontology

Shared domain ontology for MetaReasoning — formal concept models that connect agents, verifiers, and financial knowledge graphs.

## Layout

```
ontology/          # RDF/Turtle source files (versioned truth)
src/ontology_lib/  # Python helpers — load, validate, export
tests/             # Shape and namespace checks
scripts/           # Local validation entrypoints
docs/              # Architecture and contribution guides
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
./scripts/validate.sh
```

## Conventions

- **Namespace:** `https://ontology.metareasoning.ai/core#`
- **Format:** Turtle (`.ttl`) with stable IRIs; add JSON-LD exports only when a consumer needs them.
- **Changes:** Extend existing classes/properties before inventing parallel vocabularies; document rationale in PR descriptions.

## License

MIT — see [LICENSE](LICENSE).
