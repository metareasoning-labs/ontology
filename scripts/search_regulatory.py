#!/usr/bin/env python3
"""Search regulatory packages via vocab/grammar routing + Postgres FTS."""

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

from regulatory_packages.retrieval.search import search  # noqa: E402
from regulatory_packages.shared.rebuild import CORPORA  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, choices=list(CORPORA))
    parser.add_argument("query", nargs="+", help="Search query text")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    result = search(args.corpus, " ".join(args.query), limit=args.limit)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
