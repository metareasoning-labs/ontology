#!/usr/bin/env python3
"""Run the regulatory package search API (default http://127.0.0.1:8091)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import dotenv_values


def _load_env() -> None:
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

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("REGULATORY_SEARCH_HOST", "127.0.0.1")
    port = int(os.environ.get("REGULATORY_SEARCH_PORT", "8091"))
    uvicorn.run("regulatory_packages.api:app", host=host, port=port, reload=False)
