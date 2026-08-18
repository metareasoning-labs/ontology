from __future__ import annotations

from pathlib import Path

from rdflib import Graph

CORE_ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "ontology" / "core"
CORE_BASE_URI = "https://ontology.metareasoning.ai/core#"


def load_core_graph() -> Graph:
    graph = Graph()
    for path in sorted(CORE_ONTOLOGY_DIR.glob("*.ttl")):
        graph.parse(path, format="turtle")
    return graph
