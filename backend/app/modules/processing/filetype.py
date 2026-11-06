"""Content-based file type checks. The declared type and the file name are never trusted."""

_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    # DOCX and XLSX are zip containers; telling them apart needs the archive, done at extraction.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
}
_TEXT_TYPES = frozenset({"text/plain", "text/markdown", "text/csv"})
# A read of the first bytes can cut a multi-byte character in half.
_MAX_TRUNCATED_UTF8_BYTES = 3


def looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc.start >= len(head) - _MAX_TRUNCATED_UTF8_BYTES
    return True


def matches_declared_type(head: bytes, content_type: str) -> bool:
    signatures = _SIGNATURES.get(content_type)
    if signatures is not None:
        return head.startswith(signatures)
    if content_type in _TEXT_TYPES:
        return looks_like_text(head)
    return False  # a type with no check is not accepted for processing
