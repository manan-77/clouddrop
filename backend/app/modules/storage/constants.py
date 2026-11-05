from enum import StrEnum


class FileStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    SCANNING = "scanning"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    INFECTED = "infected"
    NEEDS_OCR = "needs_ocr"


# The owner may fetch anything that finished uploading except malware.
DOWNLOADABLE_STATUSES = frozenset(
    {
        FileStatus.UPLOADED,
        FileStatus.SCANNING,
        FileStatus.PROCESSING,
        FileStatus.READY,
        FileStatus.FAILED,
        FileStatus.NEEDS_OCR,
    }
)
