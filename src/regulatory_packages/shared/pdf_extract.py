"""Extract plain text from regulatory PDF bytes."""

from __future__ import annotations

import io
import logging
from contextlib import contextmanager
from typing import Any

_PDF_LOGGERS = ("pdfminer", "pypdf", "PyPDF2")
logger = logging.getLogger(__name__)


@contextmanager
def _quiet_pdf_loggers():
    """Suppress noisy font/xref warnings from PDF parsers during extraction."""
    previous: dict[str, int] = {}
    for name in _PDF_LOGGERS:
        log = logging.getLogger(name)
        previous[name] = log.level
        log.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)


def _extract_with_reader(reader: Any, *, method: str, max_pages: int | None) -> dict[str, Any]:
    pages = reader.pages
    page_count = len(pages)
    limit = page_count if max_pages is None else min(page_count, max_pages)
    parts: list[str] = []
    for index in range(limit):
        try:
            page_text = pages[index].extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            parts.append(page_text)
    text = "\n\n".join(parts).strip()
    return {
        "text": text,
        "pageCount": page_count,
        "method": method,
        "charCount": len(text),
    }


def _extract_with_pdfminer(data: bytes) -> dict[str, Any]:
    from pdfminer.high_level import extract_text

    text = extract_text(io.BytesIO(data)).strip()
    return {
        "text": text,
        "pageCount": 0,
        "method": "pdfminer",
        "charCount": len(text),
    }


def extract_pdf_text(data: bytes, *, max_pages: int | None = None) -> dict[str, Any]:
    """Return extracted text, page count, and method used."""
    if not data:
        return {"text": "", "pageCount": 0, "method": "empty", "charCount": 0}

    parsers: list[tuple[str, Any]] = []
    with _quiet_pdf_loggers():
        try:
            from pypdf import PdfReader

            parsers.append(("pypdf", PdfReader))
        except Exception:
            pass
        try:
            import PyPDF2  # type: ignore[import-untyped]

            parsers.append(("PyPDF2", PyPDF2.PdfReader))
        except Exception:
            pass

        last_error: Exception | None = None
        best_partial: dict[str, Any] | None = None
        for method, reader_cls in parsers:
            try:
                result = _extract_with_reader(
                    reader_cls(io.BytesIO(data)),
                    method=method,
                    max_pages=max_pages,
                )
                if result["charCount"] >= 200:
                    return result
                if result["charCount"] > 0 and (
                    best_partial is None or result["charCount"] > best_partial["charCount"]
                ):
                    best_partial = result
            except Exception as exc:
                last_error = exc
                logger.debug("PDF parse failed with %s: %s", method, exc)

        try:
            miner_result = _extract_with_pdfminer(data)
            if miner_result["charCount"] >= 200:
                return miner_result
            if miner_result["charCount"] > 0 and (
                best_partial is None or miner_result["charCount"] > best_partial["charCount"]
            ):
                best_partial = miner_result
        except Exception as exc:
            last_error = exc
            logger.debug("PDF parse failed with pdfminer: %s", exc)

        if best_partial and best_partial.get("charCount", 0) > 0:
            return best_partial

    if last_error is not None:
        logger.debug("All PDF parsers failed; returning empty text (%s)", last_error)
    return {"text": "", "pageCount": 0, "method": "unreadable", "charCount": 0}
