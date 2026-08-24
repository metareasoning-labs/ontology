#!/usr/bin/env python3
"""Restart Semantica Explorer with a clean regulatory graph + ontology/vocab.

Supports separate regulator views:

  python scripts/bootstrap_explorer.py --corpus sebi
  python scripts/bootstrap_explorer.py --corpus rbi
  python scripts/bootstrap_explorer.py --corpus all   # merged hub (default)

Also:
- re-exports per-regulator (+ optional merged) explorer graphs
- builds per-regulator SKOS vocabularies
- loads only the matching ontology modules for the selected corpus
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("EXPLORER_URL", "http://127.0.0.1:5173")
PORT = int(os.environ.get("EXPLORER_PORT", "5173"))

REGULATORS = ("sebi", "rbi", "gst", "insurance", "income_tax")

CORE_ONTOLOGY = [
    ROOT / "ontology/core/namespace.ttl",
    ROOT / "ontology/core/classes.ttl",
    ROOT / "ontology/core/properties.ttl",
    ROOT / "ontology/regulatory/namespace.ttl",
]

CORPUS_ONTOLOGY = {
    "sebi": ROOT / "ontology/regulatory/sebi.ttl",
    "rbi": ROOT / "ontology/regulatory/rbi.ttl",
    "gst": ROOT / "ontology/regulatory/gst.ttl",
    "insurance": ROOT / "ontology/regulatory/insurance.ttl",
    "income_tax": ROOT / "ontology/regulatory/income_tax.ttl",
}


def graph_path(corpus: str) -> Path:
    if corpus == "all":
        return ROOT / "build/ontology/regulatory/explorer-graph.json"
    return ROOT / "build/ontology/regulatory" / corpus / "explorer-graph.json"


def vocab_paths(corpus: str) -> list[Path]:
    vocab_dir = ROOT / "ontology/regulatory/vocabulary"
    if corpus == "all":
        combined = ROOT / "ontology/regulatory/vocabulary.ttl"
        return [combined] if combined.is_file() else sorted(vocab_dir.glob("*.ttl"))
    paths = [
        vocab_dir / "core.ttl",
        vocab_dir / "regulatory.ttl",
        vocab_dir / f"{corpus}.ttl",
    ]
    return [p for p in paths if p.is_file()]


def ontology_files(corpus: str) -> list[Path]:
    files = list(CORE_ONTOLOGY)
    if corpus == "all":
        files.extend(CORPUS_ONTOLOGY[c] for c in REGULATORS)
        files.append(ROOT / "ontology/regulatory/vocabulary.ttl")
    else:
        files.append(CORPUS_ONTOLOGY[corpus])
        files.extend(vocab_paths(corpus))
    return [p for p in files if p.is_file()]


def _req(method: str, path: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 120):
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers=headers or {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        if not body:
            return resp.status, None
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body.decode("utf-8", errors="replace")


def wait_health(timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            status, payload = _req("GET", "/api/health", timeout=5)
            if status == 200 and (payload or {}).get("status") == "ok":
                return
            last = payload
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.5)
    raise RuntimeError(f"Explorer did not become healthy: {last}")


def stop_explorer() -> None:
    env = os.environ.copy()
    env.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")
    subprocess.run(
        ["semantica", "explorer", "stop"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["pkill", "-f", "semantica.explorer|semantica-explorer|uvicorn.*explorer"],
        check=False,
    )
    try:
        out = subprocess.check_output(["lsof", f"-tiTCP:{PORT}", "-sTCP:LISTEN"], text=True)
        for pid in out.split():
            subprocess.run(["kill", "-9", pid.strip()], check=False)
    except subprocess.CalledProcessError:
        pass
    time.sleep(1.5)


def build_vocabularies() -> None:
    print("building per-regulator SKOS vocabularies...", flush=True)
    subprocess.check_call(
        [sys.executable, str(ROOT / "scripts/build_regulatory_vocabularies.py")],
        cwd=ROOT,
    )


def export_graphs(corpus: str) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "scripts/export_explorer_graph.py"),
        "--entity-cap",
        "1200",
        "--edge-cap",
        "3500",
    ]
    if corpus == "all":
        print("re-exporting all regulator graphs + merged hub...", flush=True)
    else:
        print(f"re-exporting {corpus} explorer graph...", flush=True)
        cmd.extend(["--corpus", corpus, "--separate-only"])
    subprocess.check_call(cmd, cwd=ROOT)


def start_explorer(corpus: str) -> None:
    path = graph_path(corpus)
    if not path.is_file():
        raise FileNotFoundError(path)
    env = os.environ.copy()
    env["SEMANTICA_ALLOW_ANONYMOUS"] = "true"
    log = Path("/tmp/semantica-explorer.log")
    with log.open("w", encoding="utf-8") as fh:
        subprocess.Popen(
            [
                "semantica",
                "explorer",
                "start",
                "--port",
                str(PORT),
                "--graph",
                str(path),
            ],
            cwd=ROOT,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    wait_health()
    print(f"explorer healthy at {BASE} (corpus={corpus}, graph={path})", flush=True)


def load_ontologies(corpus: str) -> None:
    for path in ontology_files(corpus):
        content = path.read_text(encoding="utf-8")
        payload = json.dumps({"content": content, "format": "turtle"}).encode()
        try:
            status, data = _req(
                "POST",
                "/api/ontology/load",
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=180,
            )
            print(f"ontology load {path.name}: {status} {json.dumps(data)[:180]}", flush=True)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            print(f"ontology load FAILED {path.name}: {exc.code} {detail}", flush=True)


def import_vocabularies(corpus: str) -> None:
    for path in vocab_paths(corpus):
        boundary = "----ExplorerBootstrapBoundary"
        raw = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: text/turtle\r\n\r\n"
        ).encode() + raw + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="format"\r\n\r\n'
            f"turtle\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        status, data = _req(
            "POST",
            "/api/vocabulary/import",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=120,
        )
        print(f"vocabulary import {path.name}: {status} {data}", flush=True)


def cleanup_registry() -> None:
    status, registry = _req("GET", "/api/ontology/registry", timeout=30)
    if status != 200 or not isinstance(registry, list):
        print(f"registry list failed: {status} {registry}", flush=True)
        return
    for entry in registry:
        uri = entry.get("uri") or ""
        name = entry.get("name") or ""
        class_count = entry.get("class_count") or 0
        junk = (not uri) or name.startswith("tmp") or (class_count == 0 and "tmp" in name)
        if not junk:
            continue
        path = "/api/ontology/" + urllib.parse.quote(uri, safe="")
        if not uri:
            path = "/api/ontology/"
        try:
            st, data = _req("DELETE", path, timeout=30)
            print(f"removed junk registry entry uri={uri!r} name={name!r}: {st} {data}", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"could not remove junk {uri!r}/{name!r}: {exc.code}", flush=True)


def verify(corpus: str) -> dict:
    report: dict = {"corpus": corpus}
    status, stats = _req("GET", "/api/graph/stats", timeout=30)
    report["graph_stats"] = {
        "status": status,
        "node_count": (stats or {}).get("node_count"),
        "edge_count": (stats or {}).get("edge_count"),
    }

    status, nodes = _req("GET", "/api/graph/nodes?type=entity&limit=20", timeout=30)
    entity_ids = [n.get("id") for n in (nodes or {}).get("nodes", [])]
    report["demo_pollution"] = [i for i in entity_ids if i in {"Alzheimer's", "Metformin"}]

    status, schemes = _req("GET", "/api/vocabulary/schemes", timeout=30)
    report["vocabulary_schemes"] = {"status": status, "count": len(schemes or []), "schemes": schemes}

    status, skos = _req("GET", "/api/ontology/skos/schemes", timeout=30)
    report["ontology_skos_schemes"] = {"status": status, "count": len(skos or []), "schemes": skos}

    status, registry = _req("GET", "/api/ontology/registry", timeout=30)
    report["registry"] = [
        {"uri": e.get("uri"), "name": e.get("name"), "class_count": e.get("class_count")}
        for e in (registry or [])
    ]

    t0 = time.time()
    try:
        status, analytics = _req("GET", "/api/analytics?metrics=connectivity,centrality", timeout=60)
        report["analytics_light"] = {
            "status": status,
            "seconds": round(time.time() - t0, 2),
            "has_connectivity": bool((analytics or {}).get("connectivity")),
            "has_centrality": bool((analytics or {}).get("centrality")),
        }
    except Exception as exc:  # noqa: BLE001
        report["analytics_light"] = {"error": str(exc), "seconds": round(time.time() - t0, 2)}

    status, decisions = _req("GET", "/api/decisions", timeout=30)
    report["decisions"] = {"status": status, "count": len(decisions or [])}

    payload = json.dumps({"query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 3"}).encode()
    status, sparql = _req(
        "POST", "/api/sparql", data=payload, headers={"Content-Type": "application/json"}, timeout=30
    )
    report["sparql"] = {"status": status, "rows": len((sparql or {}).get("rows") or [])}

    payload = json.dumps({"format": "json"}).encode()
    status, exported = _req(
        "POST", "/api/export", data=payload, headers={"Content-Type": "application/json"}, timeout=60
    )
    report["export"] = {"status": status, "type": type(exported).__name__}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default="all",
        choices=["all", *REGULATORS],
        help="Regulator to load into Explorer (default: all / merged hub).",
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Reuse existing explorer-graph.json files.",
    )
    args = parser.parse_args()
    corpus = args.corpus

    os.chdir(ROOT)
    os.environ.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")

    stop_explorer()
    build_vocabularies()
    if not args.skip_export:
        export_graphs(corpus)
    start_explorer(corpus)
    load_ontologies(corpus)
    import_vocabularies(corpus)
    cleanup_registry()
    report = verify(corpus)

    out = ROOT / "build/ontology/regulatory/explorer-bootstrap-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"wrote {out}", flush=True)

    problems = []
    if report.get("demo_pollution"):
        problems.append(f"demo nodes still present: {report['demo_pollution']}")
    if (report.get("vocabulary_schemes") or {}).get("count", 0) < 1:
        problems.append("vocabulary schemes empty")
    if (report.get("ontology_skos_schemes") or {}).get("count", 0) < 1:
        problems.append("ontology skos schemes empty")
    if any(
        (e.get("uri") in (None, "") or str(e.get("name", "")).startswith("tmp"))
        for e in report.get("registry") or []
    ):
        problems.append("junk registry entries remain")
    if (report.get("analytics_light") or {}).get("status") != 200:
        problems.append("light analytics failed")
    if problems:
        print("ISSUES: " + "; ".join(problems), flush=True)
        return 1
    print(f"Explorer tabs look healthy (corpus={corpus}).", flush=True)
    print(f"Open {BASE}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
