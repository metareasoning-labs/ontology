#!/usr/bin/env python3
"""Export Semantica ContextGraph JSON from generated extract graphs.

Reads `build/ontology/regulatory/{corpus}/extract-graph.json` produced by
`scripts/generate_regulatory_ontology.py` (source PDFs/Postgres → Semantica).

Writes:
  build/ontology/regulatory/{corpus}/explorer-graph.json   # per-regulator relation graph
  build/ontology/regulatory/explorer-graph.json            # optional merged hub graph

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

    by_name = {
        str(ent.get("name") or "").strip(): ent
        for ent in raw_entities
        if str(ent.get("name") or "").strip()
    }
    ranked = sorted(raw_entities, key=rank)

    # Seed with preferred instrument/hierarchy nodes, then expand via edges so the
    # capped graph stays connected (otherwise mentions/cites endpoints are dropped).
    seed_budget = entity_limit if entity_limit is not None else len(ranked)
    seed_budget = max(1, seed_budget // 2) if entity_limit is not None else seed_budget
    selected_names: list[str] = []
    for ent in ranked:
        name = str(ent.get("name") or "").strip()
        if not name or _prefix(corpus, name) in keep_ids:
            continue
        selected_names.append(name)
        if len(selected_names) >= seed_budget:
            break

    def add_entity(name: str) -> str | None:
        ent = by_name.get(name)
        if ent is None:
            return None
        eid = _prefix(corpus, name)
        if eid in keep_ids:
            return eid
        if entity_limit is not None and len(keep_ids) >= entity_limit + 1:  # + regulator hub
            return None
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
        return eid

    for name in selected_names:
        add_entity(name)

    rank_map = {t: i for i, t in enumerate(PREFERRED_EDGE_TYPES)}
    candidate_edges: list[tuple[int, str, str, str]] = []
    for rel in raw_rels:
        src_name = str(rel.get("source") or "").strip()
        tgt_name = str(rel.get("target") or "").strip()
        if not src_name or not tgt_name:
            continue
        etype = str(rel.get("type") or "related_to")
        candidate_edges.append((rank_map.get(etype, 100), etype, src_name, tgt_name))
    candidate_edges.sort(key=lambda row: (row[0], row[1]))

    usable: list[tuple[str, str, str]] = []
    for _prio, etype, src_name, tgt_name in candidate_edges:
        src = _prefix(corpus, src_name)
        tgt = _prefix(corpus, tgt_name)
        if src not in keep_ids and tgt not in keep_ids:
            continue
        if src not in keep_ids:
            if add_entity(src_name) is None:
                continue
        if tgt not in keep_ids:
            if add_entity(tgt_name) is None:
                continue
        if src in keep_ids and tgt in keep_ids:
            usable.append((etype, src, tgt))
            if edge_limit is not None and len(usable) >= edge_limit:
                break

    # Fill remaining entity budget with leftover ranked nodes.
    if entity_limit is not None:
        for ent in ranked:
            if len(keep_ids) >= entity_limit + 1:
                break
            name = str(ent.get("name") or "").strip()
            if name:
                add_entity(name)

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
        "entitiesInGraph": max(0, len(keep_ids) - 1),
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


def _save_graph(
    entities: list[dict],
    relationships: list[dict],
    out: Path,
    *,
    mode: str,
    corpora_stats: dict[str, dict],
) -> dict:
    from semantica.context.context_graph import ContextGraph

    seen: set[str] = set()
    dedup_entities: list[dict] = []
    for ent in entities:
        eid = ent["id"]
        if eid in seen:
            continue
        seen.add(eid)
        dedup_entities.append(ent)

    print(
        f"building ContextGraph → {out.name}: entities={len(dedup_entities)} "
        f"relationships={len(relationships)}",
        flush=True,
    )
    cg = ContextGraph()
    cg.build_from_entities_and_relationships(dedup_entities, relationships)
    out.parent.mkdir(parents=True, exist_ok=True)
    cg.save_to_file(str(out))
    stats = cg.to_dict().get("statistics") or {}
    manifest = {
        "path": str(out),
        "bytes": out.stat().st_size,
        "mode": mode,
        "corpora": corpora_stats,
        "graph": stats,
    }
    manifest_path = out.with_suffix(".manifest.json")
    # explorer-graph.json → explorer-graph.manifest.json
    if out.name == "explorer-graph.json":
        manifest_path = out.parent / "explorer-graph.manifest.json"
    else:
        manifest_path = out.with_name(out.stem + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB)", flush=True)
    return manifest


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
    parser.add_argument(
        "--combined-only",
        action="store_true",
        help="Only write the merged hub explorer-graph.json (skip per-regulator files).",
    )
    parser.add_argument(
        "--separate-only",
        action="store_true",
        help="Only write per-regulator explorer graphs (skip merged hub file).",
    )
    args = parser.parse_args()
    if args.combined_only and args.separate_only:
        print("Choose at most one of --combined-only / --separate-only", file=sys.stderr)
        return 2

    wanted = set(args.corpora) if args.corpora else None
    write_separate = not args.combined_only
    write_combined = not args.separate_only

    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    per_corpus: dict[str, dict] = {}
    separate_manifests: dict[str, dict] = {}

    meta_hub = "hub:india-regulatory-corpus"
    mode = "full" if args.full else "explorer"
    if write_combined:
        all_entities.append(
            {
                "id": meta_hub,
                "type": "hub",
                "label": "India Regulatory Corpus",
                "text": "SEBI · RBI · GST · IRDAI · Income Tax",
                "corpus": "all",
                "mode": mode,
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

        if write_separate:
            out = ROOT / "build" / "ontology" / "regulatory" / corpus / "explorer-graph.json"
            separate_manifests[corpus] = _save_graph(
                entities,
                relationships,
                out,
                mode=mode,
                corpora_stats={corpus: stats},
            )

        if write_combined:
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

    combined_manifest = None
    if write_combined:
        out = ROOT / "build" / "ontology" / "regulatory" / "explorer-graph.json"
        combined_manifest = _save_graph(
            all_entities,
            all_relationships,
            out,
            mode=mode,
            corpora_stats=per_corpus,
        )

    summary = {
        "mode": mode,
        "separate": {k: {"path": v["path"], "graph": v["graph"]} for k, v in separate_manifests.items()},
        "combined": (
            {"path": combined_manifest["path"], "graph": combined_manifest["graph"]}
            if combined_manifest
            else None
        ),
    }
    summary_path = ROOT / "build" / "ontology" / "regulatory" / "explorer-graphs.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")
    raise SystemExit(main())
