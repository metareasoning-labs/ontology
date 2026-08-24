#!/usr/bin/env python3
"""Rebuild regulatory ontology/vocabulary/grammar packages from Postgres corpus."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_env() -> None:
    from dotenv import dotenv_values

    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for key, value in dotenv_values(env_path).items():
        if value is None or key in os.environ:
            continue
        os.environ[key] = value
    url = os.environ.get("DATABASE_URL", "")
    if "@postgres:" in url:
        pg_port = os.environ.get("POSTGRES_HOST_PORT", "5432")
        os.environ["DATABASE_URL"] = url.replace("@postgres:5432", f"@127.0.0.1:{pg_port}")


_load_env()

from regulatory_packages.shared.rebuild import CORPORA, rebuild_corpus  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        action="append",
        choices=[*CORPORA, "all"],
        help="Corpus to rebuild (repeatable). Default: all.",
    )
    parser.add_argument("--workspace", type=Path, default=None, help="Override package output dir.")
    args = parser.parse_args()

    selected = args.corpus or ["all"]
    if "all" in selected:
        targets = list(CORPORA)
    else:
        targets = selected

    summary: dict[str, dict] = {}
    for name in targets:
        print(f"\n=== Rebuilding {name} ===", flush=True)
        result = rebuild_corpus(name, workspace=args.workspace)
        summary[name] = result
        print(
            f"{name}: v{result.get('ontologyVersion')} · "
            f"{result.get('documentsAnalyzed', 0)} analyzed · "
            f"{result.get('textEdges', 0)} text edges · "
            f"corpus {result.get('corpusStats', {})}",
            flush=True,
        )
    print("\n=== Summary ===", flush=True)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
