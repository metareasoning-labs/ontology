"""Shared filesystem paths for regulatory agent packages."""

from __future__ import annotations

from pathlib import Path

# src/regulatory_packages/shared/paths.py → repo root is parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES_ROOT = REPO_ROOT / "packages" / "regulatory"
BUILD_PACKAGES_ROOT = REPO_ROOT / "build" / "packages" / "regulatory"

CORPUS_PACKAGE_DIRS: dict[str, str] = {
    "sebi": "sebi",
    "rbi": "rbi",
    "gst": "gst",
    "insurance": "insurance",
    "income_tax": "income_tax",
}

CATALOG_FILE = "catalog.json"
ONTOLOGY_FILE = "ontology.json"
TAXONOMY_FILE = "taxonomy.json"
VOCABULARY_FILE = "vocabulary.json"
GRAMMAR_FILE = "grammar.json"


def package_dir(corpus: str, base: Path | None = None) -> Path:
    if base is not None:
        root = base.resolve()
    else:
        root = (PACKAGES_ROOT / CORPUS_PACKAGE_DIRS.get(corpus, corpus)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root
