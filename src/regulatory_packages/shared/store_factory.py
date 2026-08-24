"""Generic JSON package store under packages/regulatory/{corpus}/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from regulatory_packages.shared.paths import (
    CATALOG_FILE,
    GRAMMAR_FILE,
    ONTOLOGY_FILE,
    TAXONOMY_FILE,
    VOCABULARY_FILE,
    package_dir,
)


def make_store(corpus: str):
    """Return store helpers bound to a corpus package directory."""

    def workspace_dir(base: Path | None = None) -> Path:
        return package_dir(corpus, base)

    def default_workspace() -> Path:
        return package_dir(corpus)

    def catalog_path(base: Path | None = None) -> Path:
        return workspace_dir(base) / CATALOG_FILE

    def ontology_path(base: Path | None = None) -> Path:
        return workspace_dir(base) / ONTOLOGY_FILE

    def taxonomy_path(base: Path | None = None) -> Path:
        return workspace_dir(base) / TAXONOMY_FILE

    def vocabulary_path(base: Path | None = None) -> Path:
        return workspace_dir(base) / VOCABULARY_FILE

    def grammar_path(base: Path | None = None) -> Path:
        return workspace_dir(base) / GRAMMAR_FILE

    def save_catalog(catalog: dict[str, Any], base: Path | None = None) -> Path:
        path = catalog_path(base)
        path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def save_ontology(ontology: dict[str, Any], base: Path | None = None) -> Path:
        path = ontology_path(base)
        path.write_text(json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8")
        taxonomy_path(base).write_text(
            json.dumps(ontology.get("taxonomy", {}), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        llm = ontology.get("llm") or {}
        if llm.get("vocabulary"):
            vocabulary_path(base).write_text(
                json.dumps(llm["vocabulary"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        if llm.get("grammar"):
            grammar_path(base).write_text(
                json.dumps(llm["grammar"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return path

    def load_catalog(base: Path | None = None) -> dict[str, Any] | None:
        path = catalog_path(base)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_ontology(base: Path | None = None) -> dict[str, Any] | None:
        path = ontology_path(base)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_vocabulary(base: Path | None = None) -> dict[str, Any] | None:
        path = vocabulary_path(base)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_grammar(base: Path | None = None) -> dict[str, Any] | None:
        path = grammar_path(base)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def publish_catalog_to_ui(base: Path | None = None) -> Path | None:
        """No-op publish (ontology repo has no user-app). Kept for API compat."""
        return catalog_path(base) if catalog_path(base).is_file() else None

    def publish_ontology_to_ui(base: Path | None = None) -> Path | None:
        return ontology_path(base) if ontology_path(base).is_file() else None

    return type(
        "CorpusStore",
        (),
        {
            "default_workspace": staticmethod(default_workspace),
            "workspace_dir": staticmethod(workspace_dir),
            "catalog_path": staticmethod(catalog_path),
            "ontology_path": staticmethod(ontology_path),
            "taxonomy_path": staticmethod(taxonomy_path),
            "vocabulary_path": staticmethod(vocabulary_path),
            "grammar_path": staticmethod(grammar_path),
            "save_catalog": staticmethod(save_catalog),
            "save_ontology": staticmethod(save_ontology),
            "load_catalog": staticmethod(load_catalog),
            "load_ontology": staticmethod(load_ontology),
            "load_vocabulary": staticmethod(load_vocabulary),
            "load_grammar": staticmethod(load_grammar),
            "publish_catalog_to_ui": staticmethod(publish_catalog_to_ui),
            "publish_ontology_to_ui": staticmethod(publish_ontology_to_ui),
        },
    )
