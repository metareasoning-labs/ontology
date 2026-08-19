#!/usr/bin/env python3
"""Export a Semantica ContextGraph JSON from generated extract graphs.

Reads `build/ontology/regulatory/{corpus}/extract-graph.json` produced by
`scripts/generate_regulatory_ontology.py` (source PDFs/Postgres → Semantica).
Does not use multicatalyst ontology.json packages.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CORPORA = [
    ("sebi", "SEBI"),
    ("rbi", "RBI"),
    ("gst", "GST"),
    ("insurance", "IRDAI / Insurance"),
    ("income_tax", "Income Tax"),
]

DEFAULT_ENTITY_CAPS = {
    "sebi": 2500,
    "rbi": 2000,
    "gst": 2000,
    "insurance": 2000,
    "income_tax": 2500,
}
DEFAULT_EDGE_CAPS = {
    "sebi": 8000,
    "rbi": 6000,
    "gst": 6000,
    "insurance": 6000,
    "income_tax": 8000,
}
PREFERRED_EDGE_TYPES = (
    "inHierarchy",
    "mentions",
    "evidences",
    "related_to",
    "located_in",
)


def _extract_path(corpus: str) -> Path:
    return ROOT / "build" / "ontology" / "regulatory" / corpus / "extract-graph.json"


def _prefix(corpus: str, node_id: str) -> str:
    if node_id.startswith(("hub:", f"{corpus}:")):
        return node_id
    return f"{corpus}:{node_id}"


def load_corpus(
    corpus: str,
    label: str,
    *,
    entity_limit: int | None,
    edge_limit: int | None,
) -> tuple[list[dict], list[dict], dict]:
    path = _extract_path(corpus)
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing Semantica extract graph for {corpus}: {path}\n"
            f"Run: python scripts/generate_regulatory_ontology.py --corpus {corpus}"
        )

    print(f"loading {corpus} from {path} ({path.stat().st_size / 1e6:.1f} MB)...", flush=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_entities = list(payload.get("entities") or [])
    raw_rels = list(payload.get("relationships") or [])

    entities: list[dict] = []
    relationships: list[dict] = []
    keep_ids: set[str] = set()

    root_hub = f"hub:regulator:{corpus}"
    entities.append(
        {
            "id": root_hub,
            "type": "regulator",
            "label": label,
            "text": f"{label} ({payload.get('stats', {}).get('documents', len(raw_entities))} instruments)",
            "corpus": corpus,
        }
    )
    keep_ids.add(root_hub)

    # Prefer instrument + hierarchy nodes, then concepts.
    def rank(ent: dict) -> tuple[int, str]:
        etype = str(ent.get("type") or "")
        name = str(ent.get("name") or "")
        if etype not in {"Entity", "Person", "Date", "Circular"} and not name.startswith("concept:"):
            return (0, name)
        if name.startswith("hierarchy:"):
            return (1, name)
        return (2, name)

    ranked = sorted(raw_entities, key=rank)
    if entity_limit is not None:
        ranked = ranked[:entity_limit]

    for ent in ranked:
        name = str(ent.get("name") or "").strip()
        if not name:
            continue
        eid = _prefix(corpus, name)
        props = ent.get("properties") or {}
        entities.append(
            {
                "id": eid,
                "type": str(ent.get("type") or "Entity"),
                "label": str(ent.get("label") or name)[:200],
                "text": str(ent.get("label") or name)[:200],
                "corpus": corpus,
                **{k: v for k, v in props.items() if k in {"hierarchy", "status", "officialId", "hasPdf"}},
            }
        )
        keep_ids.add(eid)
        if not name.startswith(("concept:", "hierarchy:")):
            relationships.append(
                {
                    "source_id": root_hub,
                    "target_id": eid,
                    "type": "includes_instrument",
                    "confidence": 1.0,
                    "corpus": corpus,
                }
            )

    usable = []
    for rel in raw_rels:
        src = _prefix(corpus, str(rel.get("source") or ""))
        tgt = _prefix(corpus, str(rel.get("target") or ""))
        etype = str(rel.get("type") or "related_to")
        if src in keep_ids and tgt in keep_ids:
            usable.append((etype, src, tgt))

    if edge_limit is not None and len(usable) > edge_limit:
        rank_map = {t: i for i, t in enumerate(PREFERRED_EDGE_TYPES)}
        usable.sort(key=lambda row: (rank_map.get(row[0], 100), row[0]))
        usable = usable[:edge_limit]

    for etype, src, tgt in usable:
        relationships.append(
            {
                "source_id": src,
                "target_id": tgt,
                "type": etype,
                "confidence": 1.0,
                "corpus": corpus,
            }
        )

    stats = {
        "entitiesTotal": len(raw_entities),
        "entitiesInGraph": len(ranked),
        "edgesTotal": len(raw_rels),
        "edgesInGraph": len(usable),
        "entityLimit": entity_limit,
        "edgeLimit": edge_limit,
        "sourceStats": payload.get("stats") or {},
    }
    print(
        f"  {corpus}: entities {stats['entitiesInGraph']}/{stats['entitiesTotal']} · "
        f"edges {stats['edgesInGraph']}/{stats['edgesTotal']}",
        flush=True,
    )
    return entities, relationships, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include all entities/edges (may be slow in Explorer UI).",
    )
    parser.add_argument("--entity-cap", type=int, default=None, help="Override per-corpus entity cap.")
    parser.add_argument("--edge-cap", type=int, default=None, help="Override per-corpus edge cap.")
    parser.add_argument(
        "--corpus",
        action="append",
        dest="corpora",
        help="Limit to one or more corpora (repeatable). Default: all that have extract graphs.",
    )
    args = parser.parse_args()

    from semantica.context.context_graph import ContextGraph

    wanted = set(args.corpora) if args.corpora else None
    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    per_corpus: dict[str, dict] = {}

    meta_hub = "hub:india-regulatory-corpus"
    all_entities.append(
        {
            "id": meta_hub,
            "type": "hub",
            "label": "India Regulatory Corpus",
            "text": "SEBI · RBI · GST · IRDAI · Income Tax",
            "corpus": "all",
            "mode": "full" if args.full else "explorer",
        }
    )

    for corpus, label in CORPORA:
        if wanted is not None and corpus not in wanted:
            continue
        if not _extract_path(corpus).is_file():
            print(f"skip {corpus}: no extract-graph.json yet", flush=True)
            continue
        if args.full:
            entity_limit = None
            edge_limit = None
        else:
            entity_limit = args.entity_cap if args.entity_cap is not None else DEFAULT_ENTITY_CAPS[corpus]
            edge_limit = args.edge_cap if args.edge_cap is not None else DEFAULT_EDGE_CAPS[corpus]
        entities, relationships, stats = load_corpus(
            corpus, label, entity_limit=entity_limit, edge_limit=edge_limit
        )
        per_corpus[corpus] = stats
        all_entities.extend(entities)
        all_relationships.extend(relationships)
        all_relationships.append(
            {
                "source_id": meta_hub,
                "target_id": f"hub:regulator:{corpus}",
                "type": "includes_regulator",
                "confidence": 1.0,
            }
        )

    if not per_corpus:
        print(
            "No Semantica extract graphs found. Generate first:\n"
            "  python scripts/generate_regulatory_ontology.py --corpus gst --limit 50",
            file=sys.stderr,
        )
        return 1

    seen: set[str] = set()
    dedup_entities: list[dict] = []
    for ent in all_entities:
        eid = ent["id"]
        if eid in seen:
            continue
        seen.add(eid)
        dedup_entities.append(ent)

    print(
        f"\nbuilding ContextGraph: entities={len(dedup_entities)} "
        f"relationships={len(all_relationships)}",
        flush=True,
    )
    cg = ContextGraph()
    cg.build_from_entities_and_relationships(dedup_entities, all_relationships)

    out = ROOT / "build" / "ontology" / "regulatory" / "explorer-graph.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cg.save_to_file(str(out))
    stats = cg.to_dict().get("statistics") or {}
    manifest = {
        "path": str(out),
        "bytes": out.stat().st_size,
        "mode": "full" if args.full else "explorer",
        "corpora": per_corpus,
        "graph": stats,
    }
    (out.parent / "explorer-graph.manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB)", flush=True)
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")
    raise SystemExit(main())
