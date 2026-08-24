"""Vocab-normalize + grammar-route + FTS/postings RRF search."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from regulatory_packages.shared.corpus_port import _connect
from regulatory_packages.shared.paths import package_dir
from regulatory_packages.shared.store_factory import make_store

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-_/.]{1,64}", re.I)


@dataclass
class SearchHit:
    doc_id: str
    title: str
    score: float
    sources: list[str] = field(default_factory=list)
    hierarchy: str | None = None
    snippet: str | None = None
    related: list[dict[str, str]] = field(default_factory=list)


@dataclass
class SearchResult:
    corpus: str
    query: str
    normalized_codes: list[dict[str, str]]
    intent: str
    hits: list[SearchHit]
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "query": self.query,
            "normalized_codes": self.normalized_codes,
            "intent": self.intent,
            "latency_ms": self.latency_ms,
            "hits": [asdict(h) for h in self.hits],
        }


def _rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return fused


def _build_alias_index(vocab: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Sorted longest-first phrases: (phrase_lower, kind, code)."""
    rows: list[tuple[str, str, str]] = []

    def add(phrase: str, kind: str, code: str) -> None:
        p = phrase.strip().lower()
        if len(p) < 2:
            return
        rows.append((p, kind, code))

    for ent in vocab.get("entities") or []:
        if isinstance(ent, str):
            add(ent, "entity", ent)
            continue
        code = str(ent.get("code") or ent.get("id") or ent.get("label") or "")
        if not code:
            continue
        add(code, "entity", code)
        if ent.get("label"):
            add(str(ent["label"]), "entity", code)
        for alias in ent.get("aliases") or []:
            add(str(alias), "entity", code)

    for topic in vocab.get("topics") or []:
        if isinstance(topic, str):
            add(topic, "topic", topic)
            continue
        code = str(topic.get("id") or topic.get("code") or topic.get("label") or "")
        if not code:
            continue
        add(code, "topic", code)
        if topic.get("label"):
            add(str(topic["label"]), "topic", code)
        for kw in topic.get("keywords") or []:
            add(str(kw), "topic", code)

    rows.sort(key=lambda r: len(r[0]), reverse=True)
    return rows


def normalize_query(query: str, vocab: dict[str, Any]) -> list[dict[str, str]]:
    q = query.lower()
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for phrase, kind, code in _build_alias_index(vocab):
        if phrase in q and (kind, code) not in seen:
            seen.add((kind, code))
            found.append({"kind": kind, "code": code, "matched": phrase})
    # token fallback
    for tok in _TOKEN.findall(q):
        for phrase, kind, code in _build_alias_index(vocab):
            if phrase == tok.lower() and (kind, code) not in seen:
                seen.add((kind, code))
                found.append({"kind": kind, "code": code, "matched": phrase})
    return found


def route_intent(query: str, grammar: dict[str, Any] | None) -> str:
    q = query.lower()
    intents = (grammar or {}).get("queryIntents") or {}
    # Prefer explicit grammar intents when keywords overlap.
    best = "general_search"
    best_hits = 0
    if isinstance(intents, dict):
        for name, spec in intents.items():
            kws = []
            if isinstance(spec, dict):
                kws = list(spec.get("keywords") or spec.get("examples") or [])
            elif isinstance(spec, list):
                kws = spec
            hits = sum(1 for kw in kws if isinstance(kw, str) and kw.lower() in q)
            if hits > best_hits:
                best_hits = hits
                best = str(name)
    if any(w in q for w in ("section", "sec.", "u/s", "rule")):
        return "section_lookup"
    if any(w in q for w in ("circular", "notification", "master direction")):
        return "instrument_lookup"
    if best_hits:
        return best
    return "general_search"


def _fts_search(corpus: str, query: str, *, limit: int = 50) -> list[tuple[str, float, str]]:
    # plainto_tsquery is safer for free text
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.doc_id, ts_rank_cd(f.tsv, plainto_tsquery('english', %s)) AS rank, f.title
            FROM mc_regulatory_doc_fts f
            WHERE f.corpus = %s
              AND f.tsv @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            (query, corpus, query, limit),
        ).fetchall()
    return [(r[0], float(r[1]), r[2]) for r in rows]


def _postings_search(
    corpus: str, codes: list[dict[str, str]], *, limit: int = 50
) -> list[tuple[str, float]]:
    if not codes:
        return []
    scores: dict[str, float] = {}
    with _connect() as conn:
        for item in codes:
            rows = conn.execute(
                """
                SELECT doc_id, weight
                FROM mc_regulatory_vocab_postings
                WHERE corpus = %s AND kind = %s AND lower(code) = lower(%s)
                LIMIT %s
                """,
                (corpus, item["kind"], item["code"], limit),
            ).fetchall()
            for doc_id, weight in rows:
                scores[doc_id] = scores.get(doc_id, 0.0) + float(weight)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return ranked


def _bounded_hops(corpus: str, doc_ids: list[str], *, limit_per: int = 3) -> dict[str, list[dict[str, str]]]:
    if not doc_ids:
        return {}
    out: dict[str, list[dict[str, str]]] = {d: [] for d in doc_ids}
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT source_doc_id, target_doc_id, rel_type
            FROM mc_regulatory_corpus_relationships
            WHERE corpus = %s
              AND (source_doc_id = ANY(%s) OR target_doc_id = ANY(%s))
              AND rel_type = ANY(%s)
            LIMIT %s
            """,
            (
                corpus,
                doc_ids,
                doc_ids,
                ["implements", "amends", "repeals", "supersedes", "cites", "related_to"],
                max(20, len(doc_ids) * limit_per * 2),
            ),
        ).fetchall()
    for src, tgt, rel in rows:
        if src in out and len(out[src]) < limit_per:
            out[src].append({"doc_id": tgt, "rel": rel, "direction": "out"})
        if tgt in out and len(out[tgt]) < limit_per:
            out[tgt].append({"doc_id": src, "rel": rel, "direction": "in"})
    return out


def _titles(corpus: str, doc_ids: list[str]) -> dict[str, tuple[str, str | None]]:
    if not doc_ids:
        return {}
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, title, hierarchy
            FROM mc_regulatory_corpus_documents
            WHERE corpus = %s AND doc_id = ANY(%s)
            """,
            (corpus, doc_ids),
        ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def search(corpus: str, query: str, *, limit: int = 20) -> SearchResult:
    import time

    t0 = time.perf_counter()
    store = make_store(corpus)
    base = package_dir(corpus)
    vocab = store.load_vocabulary(base) or {}
    grammar = store.load_grammar(base) or {}

    codes = normalize_query(query, vocab)
    intent = route_intent(query, grammar)

    fts_rows = _fts_search(corpus, query, limit=max(limit * 2, 40))
    post_rows = _postings_search(corpus, codes, limit=max(limit * 2, 40))

    fts_ranked = [doc_id for doc_id, _, _ in fts_rows]
    post_ranked = [doc_id for doc_id, _ in post_rows]
    fused = _rrf_fuse([fts_ranked, post_ranked])

    # Boost docs that hit both channels
    fts_set, post_set = set(fts_ranked), set(post_ranked)
    for doc_id in list(fused):
        if doc_id in fts_set and doc_id in post_set:
            fused[doc_id] *= 1.25

    top_ids = [doc_id for doc_id, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
    titles = _titles(corpus, top_ids)
    hops = _bounded_hops(corpus, top_ids[: min(10, len(top_ids))])

    fts_title = {doc_id: title for doc_id, _, title in fts_rows}
    sources_map: dict[str, list[str]] = {}
    for doc_id in fts_ranked:
        sources_map.setdefault(doc_id, []).append("fts")
    for doc_id in post_ranked:
        sources_map.setdefault(doc_id, []).append("postings")

    hits: list[SearchHit] = []
    for doc_id in top_ids:
        title, hierarchy = titles.get(doc_id, (fts_title.get(doc_id, doc_id), None))
        hits.append(
            SearchHit(
                doc_id=doc_id,
                title=title,
                score=round(fused.get(doc_id, 0.0), 6),
                sources=sources_map.get(doc_id, []),
                hierarchy=hierarchy,
                related=hops.get(doc_id, []),
            )
        )

    return SearchResult(
        corpus=corpus,
        query=query,
        normalized_codes=codes,
        intent=intent,
        hits=hits,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
