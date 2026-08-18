from pathlib import Path

import pytest

pytest.importorskip("semantica")

from ontology_lib.config import load_semantica_settings
from ontology_lib.semantica_bridge import (
    bootstrap_semantica,
    export_merged_ttl,
    validate_with_semantica,
)


def test_semantica_config_loads():
    settings = load_semantica_settings()
    assert settings.base_uri.endswith("#")
    assert settings.source_dir.is_dir()


def test_semantica_validates_core_ontology():
    report = validate_with_semantica()
    assert report.valid is True
    assert report.consistent is True
    assert report.satisfiable is True


def test_semantica_bootstrap_exports_and_syncs(tmp_path: Path):
    settings = load_semantica_settings()
    settings = settings.__class__(
        base_uri=settings.base_uri,
        source_dir=settings.source_dir,
        store_backend=settings.store_backend,
        store_path=tmp_path / "oxigraph",
        merged_ttl_path=tmp_path / "core.ttl",
    )
    report = bootstrap_semantica(settings)
    assert report.triplets_loaded > 0
    assert report.merged_ttl_path.is_file()
    assert "VerifierCheck" in report.merged_ttl_path.read_text()


def test_export_merged_ttl(tmp_path: Path):
    output = export_merged_ttl(tmp_path / "merged.ttl")
    assert output.exists()
    assert output.stat().st_size > 0
