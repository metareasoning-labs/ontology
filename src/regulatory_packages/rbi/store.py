"""Persist rbi ontology artifacts under packages/regulatory/rbi/."""

from __future__ import annotations

from regulatory_packages.shared.store_factory import make_store

_store = make_store("rbi")

default_workspace = _store.default_workspace
workspace_dir = _store.workspace_dir
catalog_path = _store.catalog_path
ontology_path = _store.ontology_path
taxonomy_path = _store.taxonomy_path
vocabulary_path = _store.vocabulary_path
grammar_path = _store.grammar_path
save_catalog = _store.save_catalog
save_ontology = _store.save_ontology
load_catalog = _store.load_catalog
load_ontology = _store.load_ontology
load_vocabulary = _store.load_vocabulary
load_grammar = _store.load_grammar
publish_catalog_to_ui = _store.publish_catalog_to_ui
publish_ontology_to_ui = _store.publish_ontology_to_ui
