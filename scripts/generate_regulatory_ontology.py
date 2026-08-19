#!/usr/bin/env python3
"""Generate Semantica ontologies from actual regulatory source text (Postgres + PDFs)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        action="append",
        choices=["sebi", "rbi", "gst", "insurance", "income_tax"],
        help="Restrict to corpus (repeatable). Default: all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max documents per corpus (overrides serious defaults).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Process all documents (including full Income Tax ~57k).",
    )
    parser.add_argument(
        "--method",
        choices=["serious", "ml", "llm", "pattern", "turbo"],
        default="serious",
        help="Extraction profile (turbo = regex-only multiprocess, no spaCy).",
    )
    parser.add_argument(
        "--llm-docs",
        type=int,
        default=80,
        help="Max documents per corpus to send through LLM triplet extraction when a key is set.",
    )
    parser.add_argument(
        "--no-llm-tbox",
        action="store_true",
        help="Skip LLM TBox refinement even if an API key is present.",
    )
    parser.add_argument("--no-store", action="store_true", help="Skip Oxigraph sync.")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="spaCy nlp.pipe worker processes (default: 4).",
    )
    parser.add_argument(
        "--text-chars",
        type=int,
        default=3000,
        help="Chars of each document to analyze (default: 3000).",
    )
    parser.add_argument(
        "--spacy-model",
        default="en_core_web_sm",
        help="spaCy model (default: en_core_web_sm for speed; use en_core_web_md for quality).",
    )
    parser.add_argument(
        "--no-reuse-existing",
        action="store_true",
        help="Do not merge previously generated corpora when running a subset.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip documents already present in extract-graph.json; merge new results.",
    )
    args = parser.parse_args()
    _load_env()

    from ontology_lib.regulatory_semantica import generate_from_sources

    summary = generate_from_sources(
        args.corpus,
        limit=args.limit,
        method=args.method,
        sync_store=not args.no_store,
        full=args.full,
        llm_doc_budget=args.llm_docs,
        refine_llm=not args.no_llm_tbox,
        reuse_existing=not args.no_reuse_existing,
        resume=args.resume,
        n_process=args.workers,
        text_chars=args.text_chars,
        spacy_model=args.spacy_model,
    )
    print("\n=== Summary ===", flush=True)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
