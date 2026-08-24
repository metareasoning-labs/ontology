"""Shared helpers for regulatory corpus text normalization."""

from __future__ import annotations

import re
from html import unescape

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_html_text(html: str) -> str:
    """Strip scripts/styles/tags and return readable page text."""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def sanitize_corpus_text(text: str) -> str:
    """Normalize text for Postgres UTF-8 storage (NUL bytes, broken surrogates)."""
    cleaned = text.replace("\x00", "")
    return cleaned.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")
