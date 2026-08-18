# Ontology sources

Place authoritative Turtle files here. Suggested layout:

- `core/namespace.ttl` — prefix declarations and ontology header
- `core/classes.ttl` — class hierarchy
- `core/properties.ttl` — object and datatype properties

Keep files small and modular; compose with `owl:imports` or explicit merges in `scripts/validate.sh`.
