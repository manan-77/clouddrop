"""Cleaning and deterministic chunking of extracted text."""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

# NUL breaks Postgres text columns; the other control characters are extraction noise.
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_SEPARATORS = re.compile(r"[\x0b\x0c]")


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
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", _SEPARATORS.sub(" ", text))
    # Lone surrogates (seen in extracted PDF text) cannot be stored as UTF-8.
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _split(text: str, size: int, overlap: int) -> list[str]:
    """Cuts text that has no structure at all (no paragraphs or sentences) into windows of at most
    `size` characters, at a space when it can, with `overlap` characters shared between windows."""
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


_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n\s*")
# A sentence ends at . ! ? (or their full-width forms) followed by whitespace. "3.5" and "e.g."
# followed by a lowercase word are not boundaries; a capital, digit or quote after the space is.
_SENTENCE_END = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+(?=[\"'(\[]?[A-Z0-9\u00c0-\u024f])")
_PARAGRAPH_JOIN = "\n\n"
_SENTENCE_JOIN = " "


@dataclass(frozen=True)
class _Unit:
    """A piece that is never cut again, and what separates it from the one before it."""

    text: str
    join: str


def _units(text: str, size: int, overlap: int) -> list[_Unit]:
    """Paragraphs, or sentences where a paragraph is too long, or words where a sentence is."""
    units: list[_Unit] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces = [paragraph]
        if len(paragraph) > size:
            pieces = [p.strip() for p in _SENTENCE_END.split(paragraph) if p.strip()]
        join = _PARAGRAPH_JOIN
        for piece in pieces:
            # No structure left to follow: the window cut, whose windows share `overlap` characters.
            for part in [piece] if len(piece) <= size else _split(piece, size, overlap):
                units.append(_Unit(part, join))
                join = _SENTENCE_JOIN
    return units


def _tail(units: list[_Unit], overlap: int) -> list[_Unit]:
    """Whole units from the end of a chunk, up to `overlap` characters, never the whole chunk."""
    tail: list[_Unit] = []
    used = 0
    for unit in reversed(units[1:]):
        cost = len(unit.text) + len(unit.join)
        if used + cost > overlap:
            break
        tail.insert(0, unit)
        used += cost
    return tail


def _render(units: list[_Unit]) -> str:
    return "".join((unit.join if index else "") + unit.text for index, unit in enumerate(units))


def _pack(text: str, size: int, overlap: int) -> list[str]:
    """Chunks of whole paragraphs and sentences, at most `size` characters each.

    A chunk takes units while they fit. The next chunk starts with the last whole sentences of the
    previous one (up to `overlap` characters), so it never begins in the middle of a sentence and
    an answer that straddles a boundary is still in one chunk.
    """
    units = _units(text, size, overlap)
    chunks: list[str] = []
    current: list[_Unit] = []
    fresh = 0  # units of `current` that are new (not carried over from the previous chunk)
    for unit in units:
        candidate = [*current, unit]
        if len(_render(candidate)) > size and fresh > 0:
            chunks.append(_render(current))
            current = _tail(current, overlap)
            fresh = 0
            candidate = [*current, unit]
            if len(_render(candidate)) > size:  # the carried text does not leave room: drop it
                current = []
                candidate = [unit]
        current = candidate
        fresh += 1
    if fresh > 0:
        chunks.append(_render(current))
    return chunks


def chunk_sections(sections: Sequence[Section], size: int, overlap: int) -> list[Chunk]:
    """The same input always gives the same chunks (indexes, boundaries and hashes)."""
    chunks: list[Chunk] = []
    for section in sections:
        for content in _pack(clean_text(section.text), size, overlap):
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            chunks.append(Chunk(len(chunks), section.page, content, digest))
    return chunks
