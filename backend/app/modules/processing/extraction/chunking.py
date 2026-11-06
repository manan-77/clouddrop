"""Cleaning and deterministic chunking of extracted text."""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

# NUL breaks Postgres text columns; the other control characters are extraction noise.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class Section:
    """A page, a sheet, or the whole document when it has no natural parts."""

    page: int | None
    text: str


@dataclass(frozen=True)
class Chunk:
    index: int
    page: int | None
    content: str
    content_hash: str


def clean_text(text: str) -> str:
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    # Lone surrogates (seen in extracted PDF text) cannot be stored as UTF-8.
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _split(text: str, size: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to cut at whitespace in the second half of the window, never mid-word.
            cut = max(
                text.rfind(" ", start + size // 2, end), text.rfind("\n", start + size // 2, end)
            )
            if cut > start:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def chunk_sections(sections: Sequence[Section], size: int, overlap: int) -> list[Chunk]:
    """The same input always gives the same chunks (indexes, boundaries and hashes)."""
    chunks: list[Chunk] = []
    for section in sections:
        for content in _split(clean_text(section.text), size, overlap):
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            chunks.append(Chunk(len(chunks), section.page, content, digest))
    return chunks
