from rdflib import URIRef
from rdflib.namespace import OWL, RDF

from ontology_lib.loader import CORE_ONTOLOGY_DIR, load_core_graph

VERIFIER_CHECK = URIRef("https://ontology.metareasoning.ai/core#VerifierCheck")


def test_core_ttl_files_exist():
    assert list(CORE_ONTOLOGY_DIR.glob("*.ttl"))


def test_core_graph_loads():
    graph = load_core_graph()
    assert len(graph) > 0


def test_verifier_check_class_present():
    graph = load_core_graph()
    assert (VERIFIER_CHECK, RDF.type, OWL.Class) in graph
