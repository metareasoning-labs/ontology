#!/usr/bin/env python3
"""Build separate SKOS vocabularies per regulator (+ a shared combined file).

Writes:
  ontology/regulatory/vocabulary/{sebi,rbi,gst,insurance,income_tax}.ttl
  ontology/regulatory/vocabulary.ttl   (union of all schemes)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, SKOS, Graph, Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]

CORPORA = [
    ("core", "Core", [ROOT / "ontology/core/classes.ttl"]),
    ("regulatory", "Regulatory (shared)", [ROOT / "ontology/regulatory/namespace.ttl"]),
    ("sebi", "SEBI", [ROOT / "ontology/regulatory/sebi.ttl"]),
    ("rbi", "RBI", [ROOT / "ontology/regulatory/rbi.ttl"]),
    ("gst", "GST", [ROOT / "ontology/regulatory/gst.ttl"]),
    ("insurance", "Insurance / IRDAI", [ROOT / "ontology/regulatory/insurance.ttl"]),
    ("income_tax", "Income Tax", [ROOT / "ontology/regulatory/income_tax.ttl"]),
]

REGULATOR_KEYS = ("sebi", "rbi", "gst", "insurance", "income_tax")


def _scheme_uri(key: str) -> URIRef:
    return URIRef(f"https://ontology.metareasoning.ai/regulatory/vocabulary/{key}/scheme")


def _top_uri(key: str) -> URIRef:
    return URIRef(f"https://ontology.metareasoning.ai/regulatory/vocabulary/{key}")


def build_scheme(key: str, label: str, ttl_files: list[Path]) -> Graph:
    g = Graph()
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)

    scheme = _scheme_uri(key)
    top = _top_uri(key)
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal(f"{label} Vocabulary", lang="en")))
    g.add(
        (
            scheme,
            DCTERMS.description,
            Literal(f"SKOS view of the {label} ontology classes.", lang="en"),
        )
    )
    g.add((top, RDF.type, SKOS.Concept))
    g.add((top, SKOS.prefLabel, Literal(label, lang="en")))
    g.add((top, SKOS.inScheme, scheme))
    g.add((top, SKOS.topConceptOf, scheme))
    g.add((scheme, SKOS.hasTopConcept, top))

    seen: set[str] = set()
    for path in ttl_files:
        if not path.is_file():
            continue
        src = Graph()
        src.parse(path, format="turtle")
        for subject in src.subjects(RDF.type, OWL.Class):
            uri = str(subject)
            if uri in seen:
                continue
            if uri.endswith(("OwlThing", "#Thing")) or "owl#Thing" in uri:
                continue
            seen.add(uri)
            label_txt = next((str(o) for o in src.objects(subject, RDFS.label)), None)
            if not label_txt:
                label_txt = uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            comment = next((str(o) for o in src.objects(subject, RDFS.comment)), None)
            concept = URIRef(uri)
            g.add((concept, RDF.type, SKOS.Concept))
            g.add((concept, SKOS.prefLabel, Literal(label_txt, lang="en")))
            if comment:
                g.add((concept, SKOS.definition, Literal(comment, lang="en")))
            g.add((concept, SKOS.inScheme, scheme))
            g.add((concept, SKOS.broader, top))
            g.add((top, SKOS.narrower, concept))
    return g


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        action="append",
        dest="corpora",
        choices=[*REGULATOR_KEYS, "core", "regulatory"],
        help="Limit to selected schemes (repeatable). Default: all.",
    )
    args = parser.parse_args()

    wanted = set(args.corpora) if args.corpora else {key for key, _, _ in CORPORA}
    out_dir = ROOT / "ontology" / "regulatory" / "vocabulary"
    out_dir.mkdir(parents=True, exist_ok=True)

    combined = Graph()
    combined.bind("skos", SKOS)
    combined.bind("dcterms", DCTERMS)

    written: list[str] = []
    for key, label, files in CORPORA:
        if key not in wanted:
            continue
        graph = build_scheme(key, label, files)
        if key in REGULATOR_KEYS or key in {"core", "regulatory"}:
            path = out_dir / f"{key}.ttl"
            graph.serialize(path, format="turtle")
            written.append(str(path.relative_to(ROOT)))
            print(f"wrote {path} triples={len(graph)}", flush=True)
        combined += graph

    # Combined file kept for convenience / full Explorer bootstrap.
    combined_path = ROOT / "ontology" / "regulatory" / "vocabulary.ttl"
    combined.serialize(combined_path, format="turtle")
    written.append(str(combined_path.relative_to(ROOT)))
    print(f"wrote {combined_path} triples={len(combined)}", flush=True)
    print(f"schemes={len(written)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
