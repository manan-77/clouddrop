"""Checks on zip containers (DOCX and XLSX) before any parser opens them."""

import zipfile
from typing import IO

from app.modules.processing.extraction.errors import ExtractionError, ExtractionLimits


def check_zip(fileobj: IO[bytes], limits: ExtractionLimits, required_member: str) -> None:
    try:
        archive = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as exc:
        raise ExtractionError("corrupt_file") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > limits.max_zip_entries:
            raise ExtractionError("too_large_to_extract")
        total = 0
        for entry in entries:
            if entry.filename.startswith(("/", "\\")) or ".." in entry.filename.split("/"):
                raise ExtractionError("corrupt_file")
            total += entry.file_size
            if total > limits.max_uncompressed_bytes:
                raise ExtractionError("too_large_to_extract")
            # A tiny compressed size that expands enormously is the signature of a zip bomb.
            if entry.file_size > 0 and (
                entry.compress_size == 0 or entry.file_size / entry.compress_size > limits.max_ratio
            ):
                raise ExtractionError("too_large_to_extract")
        if required_member not in {entry.filename for entry in entries}:
            raise ExtractionError("type_mismatch")
