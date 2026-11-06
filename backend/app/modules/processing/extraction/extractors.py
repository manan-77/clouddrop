"""Text extraction from untrusted documents. Every limit comes from ExtractionLimits."""

import logging
from collections.abc import Callable
from typing import IO

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

from app.modules.processing.extraction.chunking import Section
from app.modules.processing.extraction.errors import ExtractionError, ExtractionLimits
from app.modules.processing.extraction.zipsafety import check_zip

logger = logging.getLogger(__name__)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEXT_TYPES = frozenset({"text/plain", "text/markdown", "text/csv"})
# Image files carry no extractable text; they need text recognition (OCR), which is not built.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg"})


def _pdf(fileobj: IO[bytes], limits: ExtractionLimits) -> list[Section]:
    reader = PdfReader(fileobj)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ExtractionError("encrypted_file")
    if len(reader.pages) > limits.max_pages:
        raise ExtractionError("too_large_to_extract")
    sections: list[Section] = []
    total = 0
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        total += len(text)
        if total > limits.max_chars:
            raise ExtractionError("too_large_to_extract")
        sections.append(Section(number, text))
    return sections


def _docx(fileobj: IO[bytes], limits: ExtractionLimits) -> list[Section]:
    check_zip(fileobj, limits, "word/document.xml")
    fileobj.seek(0)
    document = Document(fileobj)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        parts.extend("\t".join(cell.text for cell in row.cells) for row in table.rows)
    text = "\n".join(parts)
    if len(text) > limits.max_chars:
        raise ExtractionError("too_large_to_extract")
    return [Section(None, text)]


def _xlsx(fileobj: IO[bytes], limits: ExtractionLimits) -> list[Section]:
    check_zip(fileobj, limits, "xl/workbook.xml")
    fileobj.seek(0)
    workbook = load_workbook(fileobj, read_only=True, data_only=True)
    try:
        sections: list[Section] = []
        cells = 0
        chars = 0
        for number, sheet in enumerate(workbook.worksheets[: limits.max_sheets], start=1):
            lines: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells += len(row)
                if cells > limits.max_cells:
                    raise ExtractionError("too_large_to_extract")
                line = "\t".join("" if value is None else str(value) for value in row)
                chars += len(line)
                if chars > limits.max_chars:
                    raise ExtractionError("too_large_to_extract")
                lines.append(line)
            sections.append(Section(number, "\n".join(lines)))
        return sections
    finally:
        workbook.close()


def _text(fileobj: IO[bytes], limits: ExtractionLimits) -> list[Section]:
    # UTF-8 text is at most four bytes per character, so this bounds the read.
    data = fileobj.read(limits.max_chars * 4 + 1)
    if len(data) > limits.max_chars * 4:
        raise ExtractionError("too_large_to_extract")
    text = data.decode("utf-8", errors="replace")
    if len(text) > limits.max_chars:
        raise ExtractionError("too_large_to_extract")
    return [Section(None, text)]


_EXTRACTORS: dict[str, Callable[[IO[bytes], ExtractionLimits], list[Section]]] = {
    "application/pdf": _pdf,
    DOCX: _docx,
    XLSX: _xlsx,
    **dict.fromkeys(TEXT_TYPES, _text),
}


def extract(content_type: str, fileobj: IO[bytes], limits: ExtractionLimits) -> list[Section]:
    extractor = _EXTRACTORS.get(content_type)
    if extractor is None:
        raise ExtractionError("unsupported_type")
    try:
        return extractor(fileobj, limits)
    except ExtractionError:
        raise
    except (
        Exception
    ) as exc:  # a parser fed untrusted bytes can fail in any way; same input, same failure
        logger.warning("Extraction failed for a %s document: %s", content_type, type(exc).__name__)
        raise ExtractionError("corrupt_file") from exc
