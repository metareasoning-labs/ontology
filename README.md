# Ontology

Shared domain ontology for MetaReasoning — formal concept models that connect agents, verifiers, and financial knowledge graphs.

Built on [Semantica](https://github.com/semantica-agi/semantica) for SHACL-aware validation, Oxigraph storage, and future graph-native reasoning.

## Layout

```
ontology/          # RDF/Turtle source files (versioned truth)
config/            # Semantica integration settings
src/ontology_lib/  # Python helpers — load, validate, sync to graph store
tests/             # rdflib + Semantica integration checks
scripts/           # Bootstrap and validation entrypoints
docs/              # Architecture and contribution guides
```

## Quick start

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./scripts/validate.sh
```

`validate.sh` runs Semantica validation, syncs triples into a local Oxigraph store (`.semantica/oxigraph`), exports a merged Turtle file to `build/ontology/core.ttl`, then runs pytest.

## Semantica integration

| Step | Command / module | Purpose |
|------|------------------|---------|
| Validate TTL | `ontology_lib.semantica_bridge.validate_with_semantica()` | SHACL/consistency via Semantica `OntologyValidator` |
| Bootstrap store | `python scripts/bootstrap_semantica.py` | Load core ontology into Oxigraph |
| Config | `config/semantica.yaml` | Base URI, source dir, store path |

```python
from ontology_lib.semantica_bridge import bootstrap_semantica

report = bootstrap_semantica()
print(report.triplets_loaded, report.merged_ttl_path)
```

Optional CLI health check after install:

```bash
semantica doctor
```

## Conventions

- **Namespace:** `https://ontology.metareasoning.ai/core#`
- **Format:** Turtle (`.ttl`) with stable IRIs; JSON-LD exports via Semantica when needed.
- **Changes:** Extend existing classes/properties before inventing parallel vocabularies; document rationale in PR descriptions.

## License

MIT — see [LICENSE](LICENSE).
