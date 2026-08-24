"""Thin FastAPI search service for agentic regulatory retrieval."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = Path(__file__).resolve().parent / "ui"


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

from regulatory_packages.retrieval.search import search  # noqa: E402
from regulatory_packages.shared.rebuild import CORPORA  # noqa: E402

app = FastAPI(title="Regulatory package search", version="0.1.0")


class SearchRequest(BaseModel):
    corpus: str = Field(..., description="sebi|rbi|gst|insurance|income_tax")
    query: str
    limit: int = Field(20, ge=1, le=100)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search")
def post_search(body: SearchRequest) -> dict[str, Any]:
    if body.corpus not in CORPORA:
        raise HTTPException(status_code=400, detail=f"Unknown corpus: {body.corpus}")
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    return search(body.corpus, body.query.strip(), limit=body.limit).to_dict()


@app.get("/")
def ui() -> FileResponse:
    index = UI_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(index)


if UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")
