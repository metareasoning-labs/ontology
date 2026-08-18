#!/usr/bin/env python3
"""Validate core TTL with Semantica and sync into the local Oxigraph store."""

from __future__ import annotations

from ontology_lib.semantica_bridge import bootstrap_semantica


def main() -> None:
    report = bootstrap_semantica()
    print("Semantica bootstrap complete")
    print(f"  valid: {report.validation.valid}")
    print(f"  triplets loaded: {report.triplets_loaded}")
    print(f"  store: {report.store_path}")
    print(f"  merged ttl: {report.merged_ttl_path}")


if __name__ == "__main__":
    main()
