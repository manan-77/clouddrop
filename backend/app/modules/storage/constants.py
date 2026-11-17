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


# Ancestor walks (breadcrumbs, access checks) stop here, so a corrupted parent chain can never
# loop or run long, and folders cannot be nested deeper than this.
MAX_FOLDER_DEPTH = 50

# The owner may fetch anything that finished uploading except malware.
# FAILED is excluded: a failed upload has no object behind it.
DOWNLOADABLE_STATUSES = frozenset(
    {
        FileStatus.UPLOADED,
        FileStatus.SCANNING,
        FileStatus.PROCESSING,
        FileStatus.READY,
        FileStatus.NEEDS_OCR,
    }
)
