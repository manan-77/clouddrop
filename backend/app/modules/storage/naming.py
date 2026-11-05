import re
import unicodedata

from app.core.errors import UnprocessableError

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PATH_SEPARATORS = re.compile(r"[/\\]")
MAX_NAME_LENGTH = 255


def sanitize_name(raw: str) -> str:
    "User-supplied names are metadata only; they never become part of an S3 key or path."
    name = unicodedata.normalize("NFC", raw)
    name = _PATH_SEPARATORS.sub("_", _CONTROL_CHARS.sub("", name)).strip()
    if name in {"", ".", ".."}:
        raise UnprocessableError("Invalid name", code="invalid_name")
    return name[:MAX_NAME_LENGTH]
