from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "semantica.yaml"


@dataclass(frozen=True)
class SemanticaSettings:
    base_uri: str
    source_dir: Path
    store_backend: str
    store_path: Path
    merged_ttl_path: Path


def load_semantica_settings(config_path: Path | None = None) -> SemanticaSettings:
    path = config_path or DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    ontology = raw.get("ontology", {})
    storage = raw.get("storage", {})
    export = raw.get("export", {})
    return SemanticaSettings(
        base_uri=str(ontology.get("base_uri", "https://ontology.metareasoning.ai/core#")),
        source_dir=REPO_ROOT / str(ontology.get("source_dir", "ontology/core")),
        store_backend=str(storage.get("backend", "oxigraph")),
        store_path=REPO_ROOT / str(storage.get("path", ".semantica/oxigraph")),
        merged_ttl_path=REPO_ROOT / str(export.get("merged_ttl", "build/ontology/core.ttl")),
    )
