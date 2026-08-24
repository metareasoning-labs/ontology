"""Rebuild multicatalyst-style ontology/vocab/grammar packages from Postgres."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from regulatory_packages.shared import corpus_port

CORPORA = ("sebi", "rbi", "gst", "insurance", "income_tax")


def _loaders(corpus: str) -> tuple[Callable, Callable, Callable, Callable, Any]:
    if corpus == "sebi":
        from regulatory_packages.sebi.document_analysis import analyze_corpus
        from regulatory_packages.sebi.ontology import build_ontology
        from regulatory_packages.sebi import store
        from regulatory_packages.sebi.text_relationships import merge_relationships

        return analyze_corpus, merge_relationships, build_ontology, store, corpus
    if corpus == "rbi":
        from regulatory_packages.rbi.document_analysis import analyze_corpus
        from regulatory_packages.rbi.ontology import build_ontology
        from regulatory_packages.rbi import store
        from regulatory_packages.rbi.text_relationships import merge_relationships

        return analyze_corpus, merge_relationships, build_ontology, store, corpus
    if corpus == "gst":
        from regulatory_packages.gst.document_analysis import analyze_corpus
        from regulatory_packages.gst.ontology import build_ontology
        from regulatory_packages.gst import store
        from regulatory_packages.gst.text_relationships import merge_relationships

        return analyze_corpus, merge_relationships, build_ontology, store, corpus
    if corpus == "insurance":
        from regulatory_packages.insurance.document_analysis import analyze_corpus
        from regulatory_packages.insurance.ontology import build_ontology
        from regulatory_packages.insurance import store
        from regulatory_packages.insurance.text_relationships import merge_relationships

        return analyze_corpus, merge_relationships, build_ontology, store, corpus
    if corpus == "income_tax":
        from regulatory_packages.income_tax.document_analysis import analyze_corpus
        from regulatory_packages.income_tax.ontology import build_ontology
        from regulatory_packages.income_tax import store
        from regulatory_packages.income_tax.text_relationships import merge_relationships

        return analyze_corpus, merge_relationships, build_ontology, store, corpus
    raise ValueError(f"Unknown corpus: {corpus}")


def rebuild_corpus(corpus: str, *, workspace: Path | None = None) -> dict[str, Any]:
    analyze_corpus, merge_relationships, build_ontology, store, _ = _loaders(corpus)
    base = workspace or store.default_workspace()

    catalog = store.load_catalog(base)
    if not catalog or not catalog.get("documents"):
        catalog = corpus_port.catalog_from_postgres(corpus)
    else:
        catalog = corpus_port.merge_catalog_pdf_urls(catalog, corpus)

    text_by_id = corpus_port.fetch_text_map(corpus)
    stats = corpus_port.corpus_stats(corpus)
    document_analyses = analyze_corpus(catalog.get("documents", []), text_by_id)
    edges = merge_relationships(catalog.get("documents", []), text_by_id=text_by_id)
    ontology = build_ontology(
        catalog,
        text_by_id=text_by_id,
        edges=edges,
        corpus_stats=stats,
        document_analyses=document_analyses,
    )
    cat_path = store.save_catalog(catalog, base)
    ont_path = store.save_ontology(ontology, base)
    store.publish_catalog_to_ui(base)
    store.publish_ontology_to_ui(base)
    return {
        "corpus": corpus,
        "catalogPath": str(cat_path),
        "ontologyPath": str(ont_path),
        "corpusStats": stats,
        "textEdges": sum(1 for edge in edges if edge.get("sourceKind") == "text"),
        "documentsAnalyzed": sum(1 for a in document_analyses.values() if a.get("textAnalyzed")),
        "ontologyVersion": ontology.get("version"),
    }
