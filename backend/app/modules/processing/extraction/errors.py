from dataclasses import dataclass

from app.core.config import Settings


class ExtractionError(Exception):
    """The document cannot be read; `code` is a short value that is safe to store."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExtractionLimits:
    max_pages: int
    max_chars: int
    max_uncompressed_bytes: int
    max_ratio: int
    max_zip_entries: int
    max_xml_part_bytes: int
    max_sheets: int
    max_cells: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "ExtractionLimits":
        return cls(
            max_pages=settings.extract_max_pages,
            max_chars=settings.extract_max_chars,
            max_uncompressed_bytes=settings.extract_max_uncompressed_bytes,
            max_ratio=settings.extract_max_compression_ratio,
            max_zip_entries=settings.extract_max_zip_entries,
            max_xml_part_bytes=settings.extract_max_xml_part_bytes,
            max_sheets=settings.extract_max_sheets,
            max_cells=settings.extract_max_cells,
        )
