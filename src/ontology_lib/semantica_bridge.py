from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph
from semantica.ontology import OntologyValidator
from semantica.semantic_extract.types import Triplet
from semantica.triplet_store import TripletStore

from ontology_lib.config import SemanticaSettings, load_semantica_settings
from ontology_lib.loader import CORE_ONTOLOGY_DIR, load_core_graph


@dataclass(frozen=True)
class SemanticaValidationReport:
    valid: bool
    consistent: bool
    satisfiable: bool
    errors: list[str]
    warnings: list[str]

    @classmethod
    def from_result(cls, result) -> SemanticaValidationReport:
        return cls(
            valid=bool(result.valid),
            consistent=bool(result.consistent),
            satisfiable=bool(result.satisfiable),
            errors=list(result.errors or []),
            warnings=list(result.warnings or []),
        )


@dataclass(frozen=True)
class BootstrapReport:
    validation: SemanticaValidationReport
    triplets_loaded: int
    store_path: Path
    merged_ttl_path: Path


def graph_to_triplets(graph: Graph) -> list[Triplet]:
    return [
        Triplet(subject=str(subject), predicate=str(predicate), object=str(obj))
        for subject, predicate, obj in graph
    ]


def validate_with_semantica(source_dir: Path | None = None) -> SemanticaValidationReport:
    directory = source_dir or CORE_ONTOLOGY_DIR
    result = OntologyValidator().validate(str(directory))
    return SemanticaValidationReport.from_result(result)


def export_merged_ttl(output_path: Path | None = None) -> Path:
    settings = load_semantica_settings()
    destination = output_path or settings.merged_ttl_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    graph = load_core_graph()
    destination.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    return destination


def sync_core_to_triplet_store(
    settings: SemanticaSettings | None = None,
) -> tuple[TripletStore, dict]:
    config = settings or load_semantica_settings()
    config.store_path.mkdir(parents=True, exist_ok=True)
    graph = load_core_graph()
    triplets = graph_to_triplets(graph)
    store = TripletStore(backend=config.store_backend, path=str(config.store_path))
    status = store.add_triplets(triplets)
    return store, status


def bootstrap_semantica(settings: SemanticaSettings | None = None) -> BootstrapReport:
    config = settings or load_semantica_settings()
    validation = validate_with_semantica(config.source_dir)
    if not validation.valid:
        raise ValueError(
            "Semantica ontology validation failed: "
            + "; ".join(validation.errors or ["unknown error"])
        )
    _, status = sync_core_to_triplet_store(config)
    merged = export_merged_ttl(config.merged_ttl_path)
    return BootstrapReport(
        validation=validation,
        triplets_loaded=int(status.get("processed", 0)),
        store_path=config.store_path,
        merged_ttl_path=merged,
    )
