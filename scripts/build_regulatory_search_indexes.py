#!/usr/bin/env python3
"""Build FTS + vocab posting indexes for regulatory agent search."""

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

from regulatory_packages.retrieval.indexes import build_indexes  # noqa: E402
from regulatory_packages.shared.rebuild import CORPORA  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        action="append",
        choices=[*CORPORA, "all"],
        help="Corpus to index (repeatable). Default: all that have packages.",
    )
    args = parser.parse_args()
    selected = args.corpus or ["all"]
    targets = list(CORPORA) if "all" in selected else selected
    summary = {}
    for name in targets:
        print(f"indexing {name}...", flush=True)
        summary[name] = build_indexes(name)
        print(json.dumps(summary[name]), flush=True)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
